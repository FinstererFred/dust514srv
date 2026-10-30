"""Measures the server tick of a running RPCS3 host from outside: reads WorldInfo.RealTimeSeconds of the loaded map
in a tight loop (every change is one engine tick), plus CPU time per RPCS3 thread and the process RAM.

    python tools/host_tick.py --seconds 30 --label "ambush host only" --players 1
    python tools/host_tick.py --exe D:\\rpcs3_b\\rpcs3.exe --seconds 10

num_players is GameInfo.NumPlayers (via WorldInfo.Game) at start and end of the run.
Results go to stdout and, with --log, as one JSON line per run into dust_server/logs/host_tick.jsonl.

The WorldInfo is found by its vtable (DustWorldInfo, EBOOT 0319: 0x01998b10). The heap holds stale copies from
earlier maps, so the candidate whose RealTimeSeconds advances is taken. Offsets (UProperty, PS3): TimeDilation
+0x454, TimeSeconds +0x45c, RealTimeSeconds +0x460, DeltaSeconds +0x468.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import json
import statistics
import struct
import time
from pathlib import Path

import numpy as np
import psutil

VTABLE_WORLDINFO = 0x01998B10
OFF_DILATION, OFF_TIME = 0x454, 0x45C          # TimeSeconds, RealTimeSeconds, AudioTimeSeconds, DeltaSeconds follow
OFF_GAME, OFF_NUMPLAYERS = 0x4DC, 0x228         # WorldInfo.Game, GameInfo.NumPlayers
GUEST_BASE = 0x300000000                        # RPCS3 default (manifest of live_dump.py)
HEAP = (0x30000000, 0x50000000)

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.OpenThread.restype = wt.HANDLE
k32.GetThreadDescription.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
k32.LocalFree.argtypes = [ctypes.c_void_p]


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64), ("AllocationProtect", wt.DWORD),
                ("_a", wt.DWORD), ("RegionSize", ctypes.c_uint64), ("State", wt.DWORD), ("Protect", wt.DWORD),
                ("Type", wt.DWORD), ("_b", wt.DWORD)]


k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_uint64, ctypes.POINTER(MBI), ctypes.c_size_t]


class Guest:
    def __init__(self, pid, base):
        self.h = k32.OpenProcess(0x0400 | 0x0010, False, pid)   # QUERY_INFORMATION | VM_READ
        if not self.h:
            raise SystemExit("OpenProcess failed: %d" % ctypes.get_last_error())
        self.base = base
        self.buf = ctypes.create_string_buffer(1 << 24)
        self.n = ctypes.c_size_t()

    def read(self, addr, size):
        ok = k32.ReadProcessMemory(self.h, self.base + addr, self.buf, size, ctypes.byref(self.n))
        return self.buf.raw[:self.n.value] if ok else None

    def regions(self, lo, hi):
        a, m = self.base + lo, MBI()
        while a < self.base + hi and k32.VirtualQueryEx(self.h, a, ctypes.byref(m), ctypes.sizeof(m)):
            if m.State == 0x1000 and m.Protect and not m.Protect & 0x101:   # committed, not NOACCESS/GUARD
                yield max(m.BaseAddress, a) - self.base, min(m.BaseAddress + m.RegionSize, self.base + hi) - self.base
            a = m.BaseAddress + m.RegionSize

    def times(self, wi):
        return struct.unpack(">4f", self.read(wi + OFF_TIME, 16))     # time, real time, audio time, delta

    def num_players(self, wi):
        game = struct.unpack(">I", self.read(wi + OFF_GAME, 4))[0]
        return struct.unpack(">i", self.read(game + OFF_NUMPLAYERS, 4))[0] if game else None


def find_worldinfo(g):
    want = np.array([VTABLE_WORLDINFO], dtype=">u4")[0]
    cands = []
    for s, e in g.regions(*HEAP):
        for c in range(s, e, 1 << 24):
            data = g.read(c, min(1 << 24, e - c))
            if not data:
                continue
            w = np.frombuffer(data[:len(data) // 4 * 4], dtype=">u4")
            cands += [c + 4 * int(i) for i in np.nonzero(w == want)[0]]
    cands = [a for a in cands if g.read(a + OFF_DILATION, 4) == struct.pack(">f", 1.0)]
    before = {a: g.times(a)[1] for a in cands}
    time.sleep(0.5)
    live = [a for a in cands if g.times(a)[1] > before[a]]
    if len(live) != 1:
        raise SystemExit("expected one ticking WorldInfo among %d candidates, found %s" % (
            len(cands), [hex(a) for a in live]))
    return live[0]


def thread_names(pid):
    names = {}
    for t in psutil.Process(pid).threads():
        h = k32.OpenThread(0x0800, False, t.id)                  # THREAD_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        p = ctypes.c_wchar_p()
        if k32.GetThreadDescription(h, ctypes.byref(p)) >= 0 and p.value:
            names[t.id] = p.value
            k32.LocalFree(p)
        k32.CloseHandle(h)
    return names


def pct(values, q):
    v = sorted(values)
    return v[min(len(v) - 1, int(q * len(v)))]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", default=r"D:\rpcs3\rpcs3.exe", help="RPCS3 of the host (path picks the process)")
    ap.add_argument("--pid", type=int)
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--worldinfo", type=lambda s: int(s, 16), help="skip the search, guest address in hex")
    ap.add_argument("--label", default="")
    ap.add_argument("--players", type=int)
    ap.add_argument("--log", action="store_true", help="append a JSON line to dust_server/logs/host_tick.jsonl")
    ap.add_argument("--top", type=int, default=8, help="threads to list")
    args = ap.parse_args()

    pid = args.pid or next(p.pid for p in psutil.process_iter(["exe"])
                           if (p.info["exe"] or "").lower() == args.exe.lower())
    proc = psutil.Process(pid)
    g = Guest(pid, GUEST_BASE)
    wi = args.worldinfo or find_worldinfo(g)

    names = thread_names(pid)
    players0 = g.num_players(wi)
    cpu0 = {t.id: t.user_time + t.system_time for t in proc.threads()}
    proc_cpu0 = proc.cpu_times()
    ticks, last_rt = [], g.times(wi)[1]
    t0 = time.perf_counter()
    end = t0 + args.seconds
    while (now := time.perf_counter()) < end:
        tm, rt, _, dt = g.times(wi)
        if rt != last_rt:
            ticks.append((now, tm, rt, dt))
            last_rt = rt
    wall = time.perf_counter() - t0
    cpu1 = {t.id: t.user_time + t.system_time for t in proc.threads()}
    proc_cpu1 = proc.cpu_times()
    mem = proc.memory_info()

    if len(ticks) < 2:
        raise SystemExit("no ticks seen in %.1f s (map paused or loading?)" % wall)
    intervals = [(b[0] - a[0]) * 1000 for a, b in zip(ticks, ticks[1:])]
    deltas = [t[3] * 1000 for t in ticks]
    span = ticks[-1][0] - ticks[0][0]
    threads = sorted(((cpu1[i] - cpu0.get(i, 0)) / wall * 100, names.get(i, str(i))) for i in cpu1)[::-1]
    result = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "label": args.label, "players": args.players,
        "num_players": [players0, g.num_players(wi)], "pid": pid,
        "worldinfo": hex(wi), "seconds": round(wall, 1), "ticks": len(ticks),
        "tick_hz": round((len(ticks) - 1) / span, 2),
        "interval_ms": {"mean": round(statistics.mean(intervals), 1), "p50": round(pct(intervals, .5), 1),
                        "p95": round(pct(intervals, .95), 1), "max": round(max(intervals), 1)},
        "engine_delta_ms": {"mean": round(statistics.mean(deltas), 1), "max": round(max(deltas), 1)},
        "game_speed": round((ticks[-1][1] - ticks[0][1]) / span, 3),     # TimeSeconds per wall second
        "process_cpu_pct": round((sum(proc_cpu1[:2]) - sum(proc_cpu0[:2])) / wall * 100, 1),
        "rss_mb": mem.rss >> 20, "private_mb": getattr(mem, "private", 0) >> 20,
        "threads_cpu_pct": [[n, round(p, 1)] for p, n in threads[:args.top]],
    }
    print(json.dumps(result, indent=1))
    if args.log:
        path = Path(__file__).resolve().parent.parent / "dust_server" / "logs" / "host_tick.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
