"""Samples where one host thread of RPCS3 spends its time: suspends it about 1000 times a second, reads RIP and sorts the
samples into JIT code (recompiled guest code, no module), rpcs3.exe and system DLLs (by export name). For a sample
outside rpcs3.exe the first return address into rpcs3.exe found on the stack is counted as its caller, so that waits and
socket calls can be told apart. The RPCS3 PPU profiler counts all syscall time as "idle"; this shows what it is.

    python tools/thread_sampler.py                          # host main_thread, 20 s
    python tools/thread_sampler.py --thread RenderingThread --seconds 30 --top 40

rpcs3.exe has no symbols: its samples are grouped in 4 KB pages (offset from the image base). The thread's CPU time
over the run is printed too; samples in a wait function (ntdll NtWait*, ZwWait*, NtDelayExecution, ...) cost no CPU.
"""
import argparse
import collections
import ctypes
import ctypes.wintypes as wt
import struct
import time

import psutil

from host_tick import thread_names

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
k32.OpenThread.restype = wt.HANDLE
k32.OpenProcess.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.SuspendThread.argtypes = k32.ResumeThread.argtypes = [wt.HANDLE]
k32.GetThreadContext.argtypes = [wt.HANDLE, ctypes.c_void_p]
psapi.EnumProcessModulesEx.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_uint64), wt.DWORD, ctypes.POINTER(wt.DWORD),
                                       wt.DWORD]
psapi.GetModuleBaseNameW.argtypes = [wt.HANDLE, ctypes.c_uint64, wt.LPWSTR, wt.DWORD]


class ModInfo(ctypes.Structure):
    _fields_ = [("base", ctypes.c_uint64), ("size", wt.DWORD), ("entry", ctypes.c_uint64)]


psapi.GetModuleInformation.argtypes = [wt.HANDLE, ctypes.c_uint64, ctypes.POINTER(ModInfo), wt.DWORD]

CONTEXT_SIZE, CONTEXT_FLAGS_OFF, RSP_OFF, RIP_OFF = 1232, 0x30, 0x98, 0xF8
CONTEXT_CONTROL = 0x100001
WAITS = ("NtWait", "ZwWait", "NtDelayExecution", "ZwDelayExecution", "NtRemoveIoCompletion", "NtSignalAndWait",
         "WaitOnAddress", "RtlWaitOnAddress", "NtAlertThreadByThreadId", "ZwAlertThreadByThreadId",
         "NtWaitForAlertByThreadId", "ZwWaitForAlertByThreadId")


class Process:
    def __init__(self, pid):
        self.h = k32.OpenProcess(0x0410, False, pid)            # QUERY_INFORMATION | VM_READ
        self.buf = ctypes.create_string_buffer(4096)
        self.n = ctypes.c_size_t()
        self.modules = self._modules()
        self.exports = {}

    def read(self, addr, size):
        buf = self.buf if size <= 4096 else ctypes.create_string_buffer(size)
        ok = k32.ReadProcessMemory(self.h, addr, buf, size, ctypes.byref(self.n))
        return buf.raw[:self.n.value] if ok else b""

    def _modules(self):
        arr, need = (ctypes.c_uint64 * 1024)(), wt.DWORD()
        psapi.EnumProcessModulesEx(self.h, arr, ctypes.sizeof(arr), ctypes.byref(need), 3)
        mods = []
        for base in arr[:need.value // 8]:
            info, name = ModInfo(), ctypes.create_unicode_buffer(260)
            psapi.GetModuleInformation(self.h, base, ctypes.byref(info), ctypes.sizeof(info))
            psapi.GetModuleBaseNameW(self.h, base, name, 260)
            mods.append((info.base, info.base + info.size, name.value.lower()))
        return sorted(mods)

    def module(self, addr):
        for lo, hi, name in self.modules:
            if lo <= addr < hi:
                return lo, name
        return None, None

    def export_table(self, base):
        # Sorted (rva, name) of a mapped DLL's export directory, read from the target process.
        if base in self.exports:
            return self.exports[base]
        table = []
        try:
            pe = struct.unpack_from("<I", self.read(base + 0x3C, 4))[0]
            rva, size = struct.unpack_from("<II", self.read(base + pe + 0x88, 8))
            if rva:
                d = self.read(base + rva, 40)
                nfuncs, nnames, afuncs, anames, aords = struct.unpack_from("<IIIII", d, 20)
                funcs = struct.unpack("<%dI" % nfuncs, self.read(base + afuncs, 4 * nfuncs))
                names = struct.unpack("<%dI" % nnames, self.read(base + anames, 4 * nnames))
                ords = struct.unpack("<%dH" % nnames, self.read(base + aords, 2 * nnames))
                for n_rva, o in zip(names, ords):
                    s = self.read(base + n_rva, 64)
                    table.append((funcs[o], s[:s.find(b"\0")].decode("latin1")))
        except (struct.error, IndexError):
            pass
        table.sort()
        self.exports[base] = table
        return table

    def symbol(self, addr):
        base, name = self.module(addr)
        if base is None:
            return "[jit]"
        if name == "rpcs3.exe":
            return "rpcs3.exe+%#x" % ((addr - base) & ~0xFFF)
        best = None
        for rva, sym in self.export_table(base):
            if rva > addr - base:
                break
            best = sym
        return "%s!%s" % (name, best or "?")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", default=r"D:\rpcs3\rpcs3.exe")
    ap.add_argument("--thread", default="main_thread", help="part of the RPCS3 thread name")
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--rate", type=float, default=1000, help="samples per second")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    pid = next(p.pid for p in psutil.process_iter(["exe"]) if (p.info["exe"] or "").lower() == args.exe.lower())
    tid = next(t for t, n in thread_names(pid).items() if args.thread in n and n.startswith("PPU"))
    proc = Process(pid)
    rpcs3 = next((lo, hi) for lo, hi, n in proc.modules if n == "rpcs3.exe")
    th = k32.OpenThread(0x0002 | 0x0008 | 0x0040, False, tid)  # SUSPEND_RESUME | GET_CONTEXT | QUERY_INFORMATION
    raw = ctypes.create_string_buffer(CONTEXT_SIZE + 16)
    ctx = (ctypes.addressof(raw) + 15) & ~15
    struct.pack_into("<I", raw, ctx - ctypes.addressof(raw) + CONTEXT_FLAGS_OFF, CONTEXT_CONTROL)

    def cpu():
        return next(t for t in psutil.Process(pid).threads() if t.id == tid)

    samples = []
    t0, c0 = time.time(), cpu()
    while time.time() - t0 < args.seconds:
        if k32.SuspendThread(th) == 0xFFFFFFFF:
            break
        ok = k32.GetThreadContext(th, ctx)
        k32.ResumeThread(th)
        if ok:
            off = ctx - ctypes.addressof(raw)
            rip = struct.unpack_from("<Q", raw, off + RIP_OFF)[0]
            rsp = struct.unpack_from("<Q", raw, off + RSP_OFF)[0]
            samples.append((rip, rsp))
        time.sleep(1.0 / args.rate)
    t1, c1 = time.time(), cpu()
    busy = (c1.user_time - c0.user_time + c1.system_time - c0.system_time) / (t1 - t0)
    print("thread %d (%s): %d samples in %.1f s, CPU %.1f %% (user %.1f, kernel %.1f)" % (
        tid, args.thread, len(samples), t1 - t0, 100 * busy, 100 * (c1.user_time - c0.user_time) / (t1 - t0),
        100 * (c1.system_time - c0.system_time) / (t1 - t0)))

    where, groups, callers = collections.Counter(), collections.Counter(), collections.Counter()
    for rip, rsp in samples:
        sym = proc.symbol(rip)
        where[sym] += 1
        groups[sym.split("+")[0].split("!")[0]] += 1
        if not sym.startswith("rpcs3.exe") and sym != "[jit]":
            stack = proc.read(rsp, 2048)
            ret = next((v for v in struct.unpack("<%dQ" % (len(stack) // 8), stack) if rpcs3[0] <= v < rpcs3[1]), None)
            callers[(sym, proc.symbol(ret) if ret else "?")] += 1
    n = len(samples) or 1
    waits = sum(c for s, c in where.items() if any(w in s for w in WAITS))
    print("\nby module (waiting in a wait function: %.1f %%):" % (100.0 * waits / n))
    for g, c in groups.most_common():
        print("  %6.1f %%  %s" % (100.0 * c / n, g))
    print("\ntop locations:")
    for s, c in where.most_common(args.top):
        print("  %6.1f %%  %s" % (100.0 * c / n, s))
    print("\nsystem DLL samples by rpcs3.exe caller:")
    for (s, caller), c in callers.most_common(args.top):
        print("  %6.1f %%  %-45s <- %s" % (100.0 * c / n, s, caller))


if __name__ == "__main__":
    main()
