"""Heap footprint of the game over time, from the RPCS3 log of the host.

UE3 keeps its heap in a sys_vm area at 0x40000000 (sys_vm_memory_map vsize 256 MB, psize 146 MB). RPCS3 backs all of it, so
the process RAM and a memory dump show the full 256 MB. The allocator announces every 64K page it takes into use with
sys_vm_touch and every page it gives back with sys_vm_invalidate (both logged as warnings), so their running balance is
the committed heap. 256 MB is the hard limit in the emulator (RPCS3 does not enforce psize: sys_vm_get_statistics reports
nothing used).

    python tools/vm_footprint.py                    # D:\\rpcs3\\log\\RPCS3.log, one line per 30 s
    python tools/vm_footprint.py --step 10 path\\to\\RPCS3.log

The wall clock is estimated from the log's modification time and its last timestamp (the log is written live).
"""
import argparse
import ctypes
import msvcrt
import os
import re
import time

PAGE = 0x10000
VM_SIZE = 0x10000000
LINE = re.compile(r"(\d+):(\d+):(\d+\.\d+) .*sys_vm_(touch|invalidate)\(addr=0x([0-9a-f]+), size=0x([0-9a-f]+)\)")
STAMP = re.compile(r"(\d+):(\d+):(\d+\.\d+) ")


def open_shared(path):
    # RPCS3 keeps its log open for writing; Python's open() is refused, CreateFileW with full sharing is not.
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = ctypes.c_void_p
    handle = k32.CreateFileW(path, 0x80000000, 7, None, 3, 0, None)   # GENERIC_READ, share read|write|delete, OPEN_EXISTING
    if handle in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    return open(msvcrt.open_osfhandle(handle, os.O_RDONLY), encoding="utf-8", errors="replace")


def seconds(m):
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", nargs="?", default=r"D:\rpcs3\log\RPCS3.log")
    ap.add_argument("--step", type=float, default=30, help="seconds of emulator time per line")
    args = ap.parse_args()

    mtime = os.path.getmtime(args.log)
    rows, pages, peak, last_t, bucket = [], set(), 0, 0.0, None
    with open_shared(args.log) as f:
        for line in f:
            stamp = STAMP.search(line[:40])
            if stamp:
                last_t = seconds(stamp)
            m = LINE.search(line)
            if not m:
                continue
            addr, size = int(m[5], 16), int(m[6], 16)
            span = range(addr // PAGE, (addr + size + PAGE - 1) // PAGE)
            (pages.update if m[4] == "touch" else pages.difference_update)(span)
            peak = max(peak, len(pages))
            t = seconds(m)
            if t // args.step != bucket:
                bucket = t // args.step
                rows.append((t, len(pages), peak))
    rows.append((t, len(pages), peak))
    mb = lambda n: n * PAGE / 2**20
    for t, n, p in rows:
        wall = time.strftime("%H:%M:%S", time.localtime(mtime - (last_t - t)))
        print("%s  emu %7.1f s  heap %6.1f MB  peak %6.1f MB  free %6.1f MB" % (wall, t, mb(n), mb(p), mb(VM_SIZE // PAGE - n)))


if __name__ == "__main__":
    main()
