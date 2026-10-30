"""Relays the UE3 game traffic between test clients and a listen host and records every datagram, to study the
protocol (feasibility of a lightweight fake client). Point fake_battle.json target_listen at the proxy port while it runs.

    python tools/udp_proxy.py --listen 17778 --target 127.0.0.1:7777

Each client address gets its own upstream socket, so the host sees one connection per client. Records go as JSON lines
(time, client, direction c2s/s2c, hex payload) to dust_server/logs/udp_proxy.jsonl (git-ignored: game traffic).
"""
import argparse
import json
import selectors
import socket
import time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", type=int, default=17778)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--target", default="127.0.0.1:7777")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "dust_server" / "logs" / "udp_proxy.jsonl"))
    args = ap.parse_args()
    host, port = args.target.rsplit(":", 1)
    target = (host, int(port))

    sel = selectors.DefaultSelector()
    front = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    front.bind((args.bind, args.listen))
    sel.register(front, selectors.EVENT_READ, None)
    upstream = {}                                   # client address -> socket towards the host
    counts = {}
    out = open(args.out, "a", encoding="utf-8")
    print("relaying %s:%d -> %s:%d, log %s" % (args.bind, args.listen, *target, args.out), flush=True)
    last_report = time.time()
    while True:
        for key, _ in sel.select(1.0):
            sock, client = key.fileobj, key.data
            data, addr = sock.recvfrom(65535)
            if client is None:                      # from a client
                client = addr
                if client not in upstream:
                    up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    up.bind(("127.0.0.1", 0))
                    sel.register(up, selectors.EVENT_READ, client)
                    upstream[client] = up
                    print("new client %s:%d via port %d" % (*client, up.getsockname()[1]), flush=True)
                upstream[client].sendto(data, target)
                direction = "c2s"
            else:                                   # from the host, back to its client
                front.sendto(data, client)
                direction = "s2c"
            out.write(json.dumps({"t": round(time.time(), 4), "client": "%s:%d" % client, "dir": direction,
                                  "hex": data.hex()}) + "\n")
            counts[direction] = counts.get(direction, 0) + 1
        if time.time() - last_report > 10:
            out.flush()
            print(time.strftime("%H:%M:%S"), counts, flush=True)
            last_report = time.time()


if __name__ == "__main__":
    main()
