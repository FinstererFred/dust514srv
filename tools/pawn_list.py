"""Lists the pawns of a running RPCS3 host (WorldInfo.PawnList) with controller and location, so spawns and movement of
headless test clients can be checked without a picture. With --watch it repeats and shows how far each pawn moved.

    python tools/pawn_list.py
    python tools/pawn_list.py --watch 2 --seconds 30

Offsets (host and client dumps 2026-10-27): WorldInfo.PawnList +0x4f8, Pawn.Controller +0x1f4, Pawn.NextPawn +0x1f8,
Actor.Location +0x54 (X, Y, Z as floats; the LOD caves read X/Y for the horizontal distance). Firing (uprops.py on the
2026-10-30 dump): Pawn.FlashCount (byte, counts shots, replicated) +0x213, Pawn.Weapon +0x370.
"""
import argparse
import math
import struct
import time

import psutil

from host_tick import GUEST_BASE, Guest, find_worldinfo

OFF_PAWNLIST, OFF_CONTROLLER, OFF_NEXTPAWN, OFF_LOCATION = 0x4F8, 0x1F4, 0x1F8, 0x54
OFF_FLASHCOUNT, OFF_WEAPON = 0x213, 0x370


def u32(g, addr):
    return struct.unpack(">I", g.read(addr, 4))[0]


def pawns(g, wi):
    result, p = [], u32(g, wi + OFF_PAWNLIST)
    while p and len(result) < 256:
        loc = struct.unpack(">3f", g.read(p + OFF_LOCATION, 12))
        result.append((p, u32(g, p), u32(g, p + OFF_CONTROLLER), loc, g.read(p + OFF_FLASHCOUNT, 1)[0],
                       u32(g, p + OFF_WEAPON)))
        p = u32(g, p + OFF_NEXTPAWN)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", default=r"D:\rpcs3\rpcs3.exe", help="RPCS3 of the host (path picks the process)")
    ap.add_argument("--worldinfo", type=lambda s: int(s, 16), help="skip the search, guest address in hex")
    ap.add_argument("--watch", type=float, help="repeat every N seconds")
    ap.add_argument("--seconds", type=float, default=30, help="how long to watch")
    args = ap.parse_args()

    pid = next(p.pid for p in psutil.process_iter(["exe"]) if (p.info["exe"] or "").lower() == args.exe.lower())
    g = Guest(pid, GUEST_BASE)
    wi = args.worldinfo or find_worldinfo(g)
    print("worldinfo", hex(wi), "players", g.num_players(wi))
    last, end = {}, time.time() + args.seconds
    while True:
        print(time.strftime("%H:%M:%S"))
        for p, vtable, ctrl, loc, flash, weapon in pawns(g, wi):
            moved = math.dist(loc, last[p]) if p in last else 0.0
            print("  pawn %#x vtable %#x controller %#x  loc %9.1f %9.1f %9.1f  moved %7.1f  weapon %#x flash %3d"
                  % (p, vtable, ctrl, *loc, moved, weapon, flash))
            last[p] = loc
        if not args.watch or time.time() + args.watch > end:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
