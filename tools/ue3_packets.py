"""Decodes UE3 game packets recorded by tools/udp_proxy.py (groundwork for a lightweight fake test client).

    python tools/ue3_packets.py                    summary: packets that parse, busiest channels, opened channel types
    python tools/ue3_packets.py --control          control channel messages (handshake) as hex and text

Packet layout as in stock UE3 UNetConnection::ReceivedPacket, confirmed on every recorded packet (2026-10-30):
LSB-first bit stream ending in a 1 terminator bit; PacketId SerializeInt(16384); then items until the terminator:
bit 1 = ack (PacketId), bit 0 = bunch: bControl [bOpen bClose], bReliable, ChIndex SerializeInt(1023),
[ChSequence SerializeInt(1024) if reliable], [ChType SerializeInt(8) if reliable or open], BunchDataBits
SerializeInt(MaxPacket*8, MaxPacket 512), data. Message payloads use big-endian integers (PS3).
"""
import argparse
import collections
import json
import re
from pathlib import Path

MAX_PACKETID, MAX_CHANNELS, MAX_CHSEQUENCE, CHTYPE_MAX, MAX_PACKET = 16384, 1023, 1024, 8, 512
LOG = Path(__file__).resolve().parent.parent / "dust_server" / "logs" / "udp_proxy.jsonl"


class BitReader:
    def __init__(self, data):
        if not data or not data[-1]:
            raise ValueError("no terminator bit")
        self.data, self.pos = data, 0
        self.end = (len(data) - 1) * 8 + data[-1].bit_length() - 1

    def bit(self):
        if self.pos >= self.end:
            raise ValueError("read past the end")
        v = (self.data[self.pos >> 3] >> (self.pos & 7)) & 1
        self.pos += 1
        return v

    def serialize_int(self, maximum):
        value, mask = 0, 1
        while value + mask < maximum and mask:
            if self.bit():
                value |= mask
            mask <<= 1
        return value

    def take(self, nbits):
        out = bytearray((nbits + 7) // 8)
        for i in range(nbits):
            out[i >> 3] |= self.bit() << (i & 7)
        return bytes(out)


def parse(data):
    """Returns (packet_id, acks, bunches); a bunch is a dict with channel, sequence, type, flags and payload."""
    r = BitReader(data)
    packet_id, acks, bunches = r.serialize_int(MAX_PACKETID), [], []
    while r.pos < r.end:
        if r.bit():
            acks.append(r.serialize_int(MAX_PACKETID))
            continue
        control = r.bit()
        opened = closed = 0
        if control:
            opened, closed = r.bit(), r.bit()
        reliable = r.bit()
        channel = r.serialize_int(MAX_CHANNELS)
        sequence = r.serialize_int(MAX_CHSEQUENCE) if reliable else None
        chtype = r.serialize_int(CHTYPE_MAX) if reliable or opened else None
        nbits = r.serialize_int(MAX_PACKET * 8)
        if r.pos + nbits > r.end:
            raise ValueError("bunch runs past the end")
        bunches.append({"channel": channel, "sequence": sequence, "type": chtype, "reliable": reliable,
                        "open": opened, "close": closed, "bits": nbits, "data": r.take(nbits)})
    return packet_id, acks, bunches


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default=str(LOG))
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()
    records = [json.loads(line) for line in open(args.log, encoding="utf-8")]

    ok, errors = 0, collections.Counter()
    busiest, opened = collections.Counter(), collections.Counter()
    shown = 0
    for rec in records:
        try:
            _, _, bunches = parse(bytes.fromhex(rec["hex"]))
        except ValueError as e:
            errors[str(e)] += 1
            continue
        ok += 1
        for b in bunches:
            busiest[(rec["dir"], b["channel"])] += 1
            if b["open"]:
                opened[(rec["dir"], b["type"])] += 1
            if args.control and b["channel"] == 0 and shown < args.limit:
                text = re.sub(rb"[^ -~]", b".", b["data"]).decode()
                print("%s seq=%s msg=%d bits=%d  %s\n    %s" % (rec["dir"], b["sequence"], b["data"][0], b["bits"],
                                                         b["data"][:32].hex(), text[:160]))
                shown += 1
    for direction in ("c2s", "s2c"):
        sel = [r for r in records if r["dir"] == direction]
        if len(sel) > 1:
            span = sel[-1]["t"] - sel[0]["t"]
            size = sum(len(r["hex"]) // 2 for r in sel)
            print("%s: %d packets in %.0f s, %.1f/s, avg %.0f B, %.1f kB/s" % (direction, len(sel), span, len(sel) / span,
                                                                           size / len(sel), size / span / 1024))
    print("parsed %d of %d packets, errors %s" % (ok, len(records), dict(errors)))
    print("busiest channels (dir, channel):", busiest.most_common(8))
    print("opened channels (dir, type):", dict(opened))


if __name__ == "__main__":
    main()
