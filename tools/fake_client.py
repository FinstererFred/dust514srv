"""Lightweight fake battle client for load tests: joins a listen host over the UE3 net protocol without RPCS3.

    python tools/fake_client.py --bind 127.0.0.20 --seconds 60

Steps: registers a member with the CREST server (POST /dev/battle/fake_member/, the host picks the credential up with
its next members poll), then Hello -> Challenge -> Login (challenge response "0") -> Welcome -> Join on the control
channel, then acks every packet the host sends and keeps the connection alive. It does not spawn or move yet.
Message bytes were copied from a recorded real client (tools/udp_proxy.py, tools/ue3_packets.py); integers inside
messages are big-endian.
"""
import argparse
import json
import socket
import struct
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue3_packets import MAX_CHANNELS, MAX_CHSEQUENCE, CHTYPE_MAX, MAX_PACKET, MAX_PACKETID, parse  # noqa: E402

CHTYPE_CONTROL = 1
MSG_HELLO, MSG_CHALLENGE, MSG_LOGIN, MSG_FAILURE, MSG_JOIN, MSG_WELCOME = 0, 3, 4, 6, 9, 11
HELLO = bytes.fromhex("00080000199100001a2b0000000000000000000000000000000000000000")
JOIN = bytes([MSG_JOIN]) + bytes(8)
LOGIN_HEAD = bytes.fromhex("0400004e2005")       # message type, then fields copied verbatim (NetSpeed 20000 among them)
URL = ("{port}/LoginScene?credential={credential}?Team={team}?LightingMode=MOOD_DAY?DefaultArmor=352592"
       "?Name={name}?SeekFreeLoading=1?Version=2.13.0.249")
MAX_ACKS_PER_PACKET = 32


class BitWriter:
    def __init__(self):
        self.bits = []

    def bit(self, v):
        self.bits.append(1 if v else 0)

    def serialize_int(self, value, maximum):
        mask = 1
        while value + mask < maximum and mask:
            self.bit(value & mask)
            mask <<= 1

    def data(self, payload, nbits):
        for i in range(nbits):
            self.bit((payload[i >> 3] >> (i & 7)) & 1)

    def finish(self):
        bits = self.bits + [1]                      # terminator
        out = bytearray((len(bits) + 7) // 8)
        for i, b in enumerate(bits):
            out[i >> 3] |= b << (i & 7)
        return bytes(out)


def ue3_string(text):
    raw = text.encode("ascii") + b"\0"
    return struct.pack(">i", len(raw)) + raw


class Connection:
    def __init__(self, bind, server):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind, 0))
        self.sock.settimeout(0.02)
        self.server = server
        self.packet_id = 0
        self.control_seq = 0
        self.pending_acks = []
        self.last_send = 0.0
        self.stats = {"recv": 0, "sent": 0, "bytes_in": 0, "opened": 0, "closed": 0, "bunches": 0, "errors": 0}

    def send(self, bunches=()):
        """bunches: (channel, payload) pairs for the control channel, sent reliable."""
        w = BitWriter()
        w.serialize_int(self.packet_id % MAX_PACKETID, MAX_PACKETID)
        acks, self.pending_acks = self.pending_acks[:MAX_ACKS_PER_PACKET], self.pending_acks[MAX_ACKS_PER_PACKET:]
        for ack in acks:
            w.bit(1)
            w.serialize_int(ack, MAX_PACKETID)
        for channel, payload in bunches:
            self.control_seq += 1
            w.bit(0)
            opening = self.control_seq == 1         # the first bunch opens the control channel
            w.bit(opening)                          # bControl: open/close flags follow
            if opening:
                w.bit(1)                            # bOpen
                w.bit(0)                            # bClose
            w.bit(1)                                # bReliable
            w.serialize_int(channel, MAX_CHANNELS)
            w.serialize_int(self.control_seq % MAX_CHSEQUENCE, MAX_CHSEQUENCE)
            w.serialize_int(CHTYPE_CONTROL, CHTYPE_MAX)
            w.serialize_int(len(payload) * 8, MAX_PACKET * 8)
            w.data(payload, len(payload) * 8)
        self.sock.sendto(w.finish(), self.server)
        self.packet_id += 1
        self.stats["sent"] += 1
        self.last_send = time.time()

    def receive(self):
        """Returns control messages (bytes) received; acks every packet."""
        messages = []
        while True:
            try:
                data, _ = self.sock.recvfrom(65535)
            except (socket.timeout, ConnectionResetError):
                return messages
            self.stats["recv"] += 1
            self.stats["bytes_in"] += len(data)
            try:
                packet_id, _, bunches = parse(data)
            except ValueError:
                self.stats["errors"] += 1
                continue
            self.pending_acks.append(packet_id)
            for b in bunches:
                self.stats["bunches"] += 1
                self.stats["opened"] += b["open"]
                self.stats["closed"] += b["close"] and b["channel"] != 0
                if b["channel"] == 0 and b["data"]:
                    messages.append(b["data"])
                    if b["close"]:
                        messages.append(b"closed")


def register(crest, team):
    body = json.dumps({"team": team} if team else {}).encode()
    req = urllib.request.Request(crest + "/dev/battle/fake_member/", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crest", default="http://127.0.0.1:8080")
    ap.add_argument("--bind", default="127.0.0.20", help="local address; one per fake client keeps them apart")
    ap.add_argument("--server", help="host:port of the listen host (default: from the CREST answer)")
    ap.add_argument("--team", choices=["attacker", "defender"])
    ap.add_argument("--wait", type=float, default=8, help="seconds for the host to poll the new member")
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--retries", type=int, default=10, help="new handshakes while the host rejects the credential")
    ap.add_argument("--keepalive", type=float, default=0.05, help="max seconds between our packets")
    args = ap.parse_args()

    member = register(args.crest, args.team)
    host, port = (args.server.rsplit(":", 1) if args.server
                  else (member["server"]["address"], member["server"]["port"]))
    print("member %s, character %s, team %s -> %s:%s" % (member["credential"], member["characterID"], member["team"],
                                                         host, port), flush=True)
    time.sleep(args.wait)
    for attempt in range(args.retries + 1):
        state = run(args, member, host, port)
        if state != "invalid_credential":
            break
        print("host does not know the credential yet, retrying in 3 s", flush=True)
        time.sleep(3)


def run(args, member, host, port):
    conn = Connection(args.bind, (host, int(port)))
    conn.send([(0, HELLO)])
    state, start, last_report = "hello", time.time(), time.time()
    while time.time() - start < args.seconds:
        for msg in conn.receive():
            kind = msg[0] if msg != b"closed" else None
            if kind == MSG_CHALLENGE and state == "hello":
                url = URL.format(port=":%s" % port, credential=member["credential"], team=member["team"],
                                 name="FakeClient")
                conn.send([(0, LOGIN_HEAD + ue3_string("0") + ue3_string(url))])
                state = "login"
                print("challenge -> login", flush=True)
            elif kind == MSG_WELCOME and state == "login":
                conn.send([(0, JOIN)])
                state = "joined"
                print("welcome -> join", flush=True)
            elif kind == MSG_FAILURE or msg == b"closed":
                print("host closed or refused:", msg[:120], flush=True)
                state = "invalid_credential" if b"InvalidCredential" in msg else "failed"
            elif kind not in (20,):
                print("control message %s (%d bytes)" % (kind, len(msg)), flush=True)
        if state in ("failed", "invalid_credential"):
            break
        if conn.pending_acks or time.time() - conn.last_send > args.keepalive:
            conn.send()
        if time.time() - last_report > 5:
            print(time.strftime("%H:%M:%S"), state, conn.stats, flush=True)
            last_report = time.time()
    print("end", state, conn.stats, flush=True)
    conn.sock.close()
    return state


if __name__ == "__main__":
    main()
