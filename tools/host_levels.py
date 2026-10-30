"""Writes the streaming level names of the running listen host (package name and FName number) to a JSON file for
tools/fake_client.py --levels.

A client reports every visible level with ServerUpdateLevelVisibility(PackageName). The host keeps the names per
connection (ClientVisibleLevelNames) and replicates an actor in a sublevel only to connections that list that level,
compared by FName including the number. Outpost levels are instanced (CS_GA_SecScan01S_LOD0_3, ..._4, ...); a real
client gets the same instance numbers as the host because both create them in the same order. The fake client cannot
derive them (the channel indices it used before matched only 20 of 158 names), so it takes them from this list. The
list is fixed per map.

    python tools/host_levels.py                     # -> research/levels/<world>.json
    python tools/host_levels.py --out levels.json

Layout (guest memory, 2026-10-30): GNames = array of FNameEntry pointers (entry: Index*2, HashNext, ANSI text), found
via the entry of "LevelStreamingKismet"; ULevelStreamingKismet vtable 0x191dc58, PackageName FName at +0x40/+0x44.
"""
import argparse
import json
import struct
from pathlib import Path

import psutil

from host_tick import GUEST_BASE, HEAP, Guest

VTABLE_LEVEL_STREAMING_KISMET = 0x191DC58
OFF_PACKAGE_NAME = 0x40
GWORLD = 0x01CB0FE8                              # UWorld*; +0x50 PersistentLevel, Outer +0x28, Name +0x2c/+0x30


class Names:
    def __init__(self, g):
        self.g = g
        self.base = self._find()

    def u32(self, a):
        return struct.unpack(">I", self.g.read(a, 4))[0]

    def chunks(self):
        for s, e in self.g.regions(*HEAP):
            for c in range(s, e, 1 << 24):
                data = self.g.read(c, min(1 << 24, e - c))
                if data:
                    yield c, data

    def _find(self):
        for c, data in self.chunks():
            i = data.find(b"\0LevelStreamingKismet\0")
            if i < 0:
                continue
            entry = c + i + 1 - 8
            want = struct.pack(">I", entry)
            for c2, data2 in self.chunks():
                j = data2.find(want)
                while j >= 0:
                    base = c2 + j - 4 * (self.u32(entry) >> 1)
                    if j % 4 == 0 and self.g.read(self.u32(base) + 8, 5) == b"None\0":
                        return base
                    j = data2.find(want, j + 1)
        raise SystemExit("name table not found")

    def text(self, index):
        raw = self.g.read(self.u32(self.base + 4 * index) + 8, 128)
        return raw[:raw.find(b"\0")].decode("latin1")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", default=r"D:\rpcs3\rpcs3.exe")
    ap.add_argument("--out", help="default: research/levels/<world>.json")
    args = ap.parse_args()

    pid = next(p.pid for p in psutil.process_iter(["exe"]) if (p.info["exe"] or "").lower() == args.exe.lower())
    g = Guest(pid, GUEST_BASE)
    names = Names(g)
    level = names.u32(names.u32(GWORLD) + 0x50)
    while names.u32(level + 0x28):
        level = names.u32(level + 0x28)
    world = names.text(names.u32(level + 0x2C))

    want, levels = struct.pack(">I", VTABLE_LEVEL_STREAMING_KISMET), set()
    for c, data in names.chunks():
        j = data.find(want)
        while j >= 0:
            if j % 4 == 0:
                index, number = struct.unpack(">ii", g.read(c + j + OFF_PACKAGE_NAME, 8))
                if 0 < index < 1 << 20 and 0 <= number < 10000:
                    levels.add((names.text(index), number))
            j = data.find(want, j + 1)
    out = Path(args.out or Path(__file__).resolve().parent.parent / "research" / "levels" / ("%s.json" % world))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"world": world, "levels": sorted(levels)}, indent=1))
    print("%s: %d streaming levels -> %s" % (world, len(levels), out))


if __name__ == "__main__":
    main()
