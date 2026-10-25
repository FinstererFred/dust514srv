"""DUST 514 listen server: accepts HTTP and TLS on several ports and logs everything the client sends.

Each connection is logged to the console and to logs/requests.jsonl. TLS connections get their
ClientHello parsed (version, SNI, cipher suites) before a handshake with a self-signed certificate
is attempted, so we can see whether the PS3 client accepts our certificate at all.
"""

import argparse
import base64
import datetime
import json
import os
import socket
import socketserver
import ssl
import struct
import threading
from pathlib import Path

import admin
import server_status
from crest_app import CrestApp, StreamResponse

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
APP = CrestApp()
CERT_FILE = BASE_DIR / "certs" / "server.crt"
KEY_FILE = BASE_DIR / "certs" / "server.key"

_log_lock = threading.Lock()


def log_event(event: dict) -> None:
    event = {"time": datetime.datetime.now().isoformat(timespec="milliseconds"), **event}
    line = json.dumps(event, ensure_ascii=False)
    server_status.record(event)
    with _log_lock:
        print(line, flush=True)
        with open(LOG_DIR / "requests.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")


def encode_body(data: bytes) -> dict:
    try:
        return {"body": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {"body_b64": base64.b64encode(data).decode("ascii")}


def parse_client_hello(data: bytes) -> dict:
    """Extract the interesting fields of a TLS ClientHello (best effort)."""
    info = {"record_version": data[1:3].hex()}
    try:
        pos = 5
        if data[pos] != 0x01:
            return {**info, "error": "not a ClientHello"}
        pos += 4
        info["client_version"] = data[pos:pos + 2].hex()
        pos += 2 + 32
        pos += 1 + data[pos]
        (cs_len,) = struct.unpack(">H", data[pos:pos + 2])
        suites = data[pos + 2:pos + 2 + cs_len]
        info["cipher_suites"] = [suites[i:i + 2].hex() for i in range(0, len(suites), 2)]
        pos += 2 + cs_len
        pos += 1 + data[pos]
        if pos + 2 > len(data):
            return info
        (ext_total,) = struct.unpack(">H", data[pos:pos + 2])
        pos += 2
        end = pos + ext_total
        extensions = []
        while pos + 4 <= end and pos + 4 <= len(data):
            ext_type, ext_len = struct.unpack(">HH", data[pos:pos + 4])
            ext_data = data[pos + 4:pos + 4 + ext_len]
            extensions.append(f"{ext_type:04x}")
            if ext_type == 0 and len(ext_data) > 5:
                (name_len,) = struct.unpack(">H", ext_data[3:5])
                info["sni"] = ext_data[5:5 + name_len].decode("ascii", "replace")
            pos += 4 + ext_len
        info["extensions"] = extensions
    except (IndexError, struct.error) as e:
        info["parse_error"] = repr(e)
    return info


def read_http_request(conn) -> tuple[bytes, bytes] | None:
    """Read one HTTP request; returns (head, body) or None if the peer closed."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = conn.recv(65536)
        if not chunk:
            return (buf, b"") if buf else None
        buf += chunk
    head, body = buf.split(b"\r\n\r\n", 1)
    length = 0
    for line in head.split(b"\r\n")[1:]:
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    while len(body) < length:
        chunk = conn.recv(65536)
        if not chunk:
            break
        body += chunk
    return head, body


def send_stream(conn, status, reason, content_type, stream, meta) -> None:
    """Send a long-lived response with chunked encoding until the client goes away."""
    conn.settimeout(None)
    conn.sendall(f"HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\n"
                 "Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n".encode())
    try:
        for chunk in stream.chunks:
            conn.sendall(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
    except OSError as e:
        log_event({**meta, "kind": "stream_closed", "error": repr(e)})


def handle_http(conn, meta: dict) -> None:
    while True:
        req = read_http_request(conn)
        if req is None:
            return
        head, body = req
        lines = head.decode("latin-1").split("\r\n")
        request_line = lines[0]
        headers = dict(line.split(": ", 1) for line in lines[1:] if ": " in line)
        if not request_line.split(" ")[0].isalpha():
            # Not HTTP at all: keep the raw bytes and stop talking.
            log_event({**meta, "kind": "raw", **encode_body(head + body)})
            return
        method, target = request_line.split(" ")[:2]
        base = f"{'https' if meta.get('tls') else 'http'}://{headers.get('Host', '127.0.0.1')}"
        try:
            status, content_type, payload, source, extra_headers = APP.handle(method, target, headers, body, base,
                                                                              peer=meta["peer"].rsplit(":", 1)[0])
        except Exception as e:
            status, content_type, source, extra_headers = 500, "application/json", f"server_error:{e!r}", {}
            payload = json.dumps({"message": repr(e)}).encode()
        streaming = isinstance(payload, StreamResponse)
        preview = "<stream>" if streaming else payload[:400].decode("utf-8", "replace")
        log_event({**meta, "kind": "http", "request": request_line, "status": status, "source": source,
                   "headers": headers, **encode_body(body), "response": preview})
        reason = {200: "OK", 201: "Created", 404: "Not Found", 500: "Internal Server Error"}.get(status, "OK")
        if streaming:
            send_stream(conn, status, reason, content_type, payload, meta)
            return
        conn.sendall(
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\n".encode()
            + f"Content-Length: {len(payload)}\r\n".encode()
            + "".join(f"{k}: {v}\r\n" for k, v in extra_headers.items()).encode()
            + b"Connection: keep-alive\r\n\r\n"
            + payload
        )


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        sock: socket.socket = self.request
        sock.settimeout(30)
        port = self.server.server_address[1]
        meta = {"port": port, "peer": f"{self.client_address[0]}:{self.client_address[1]}"}
        try:
            first = sock.recv(4096, socket.MSG_PEEK)
        except OSError as e:
            log_event({**meta, "kind": "error", "error": repr(e)})
            return
        if not first:
            log_event({**meta, "kind": "empty_connection"})
            return
        if first[0] == 0x16:
            log_event({**meta, "kind": "tls_client_hello", **parse_client_hello(first), "raw_b64": base64.b64encode(first).decode()})
            try:
                tls = self.server.ssl_context.wrap_socket(sock, server_side=True)
            except (ssl.SSLError, OSError) as e:
                log_event({**meta, "kind": "tls_handshake_failed", "error": repr(e)})
                return
            log_event({**meta, "kind": "tls_handshake_ok", "version": tls.version(), "cipher": tls.cipher()})
            handle_http(tls, {**meta, "tls": True})
        else:
            handle_http(sock, {**meta, "tls": False})


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # The PS3 TLS stack is old; accept everything OpenSSL still offers.
    ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
    ctx.set_ciphers("ALL:@SECLEVEL=0")
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    return ctx


class ClientLogHandler(socketserver.BaseRequestHandler):
    """Receives the client's Python log lines sent by client_patch/dustlogfwd.py."""

    def handle(self):
        data, _ = self.request
        line = data.decode("utf-8", "replace").rstrip("\n")
        stamp = datetime.datetime.now().isoformat(timespec="milliseconds")
        # The sender port tells two clients on this machine apart.
        peer = self.client_address[1]
        with _log_lock:
            print(f"[client {peer}] {line}", flush=True)
            with open(LOG_DIR / "client.log", "a", encoding="utf-8") as f:
                f.write(f"{stamp} [{peer}] {line}\n")


class BattleProbeHandler(socketserver.BaseRequestHandler):
    """Logs UDP packets on the UE3 game port (experiment 1, variant "probe" in fake_battle.json).

    Nothing answers, so we only learn whether and how the client tries to reach a battle server.
    """

    def handle(self):
        data, _ = self.request
        log_event({"port": self.server.server_address[1], "peer": f"{self.client_address[0]}:{self.client_address[1]}",
                   "kind": "battle_probe", "length": len(data), "hex": data[:256].hex()})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--ports", default="80,443,8080,8081",
                        help="comma-separated list of ports (8081: second client, dev commands from dev_commands_8081.json)")
    parser.add_argument("--client-log-port", type=int, default=8514, help="UDP port for client log lines")
    parser.add_argument("--battle-probe-port", type=int, default=17777,
                        help="UDP port logged as a fake battle server (not 7777, which a listen server needs)")
    parser.add_argument("--admin-host", default=os.environ.get("DUST_ADMIN_HOST", "0.0.0.0"), help="web admin address")
    parser.add_argument("--admin-port", type=int, default=int(os.environ.get("DUST_ADMIN_PORT", "8088")),
                        help="web admin port (admin.py), 0 = off")
    args = parser.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    udp = socketserver.ThreadingUDPServer((args.host, args.client_log_port), ClientLogHandler)
    threading.Thread(target=udp.serve_forever, daemon=True).start()
    print(f"client log on udp {args.host}:{args.client_log_port}", flush=True)
    probe = socketserver.ThreadingUDPServer((args.host, args.battle_probe_port), BattleProbeHandler)
    threading.Thread(target=probe.serve_forever, daemon=True).start()
    print(f"battle probe on udp {args.host}:{args.battle_probe_port}", flush=True)
    ssl_context = make_ssl_context()
    for port in (int(p) for p in args.ports.split(",")):
        server = Server((args.host, port), Handler)
        server.ssl_context = ssl_context
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"listening on {args.host}:{port}", flush=True)
    if args.admin_port:
        admin.start(args.admin_host, args.admin_port)
    threading.Event().wait()


if __name__ == "__main__":
    main()
