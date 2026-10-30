"""Reads or changes a 32-bit big-endian word in the guest memory of a running RPCS3 (experiments on the host, e.g.
switching GameViewportClient.bDisableWorldRendering on and off). Prints the old and new value.

    python tools/guest_poke.py 0x470c7954                        read
    python tools/guest_poke.py 0x470c7954 --set-bits 0x10000000  OR the mask in
    python tools/guest_poke.py 0x470c7954 --clear-bits 0x10000000
    python tools/guest_poke.py 0x470c7954 --value 0x0 --exe D:\\rpcs3_b\\rpcs3.exe
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import struct

import psutil

GUEST_BASE = 0x300000000   # RPCS3 default, see host_tick.py

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.POINTER(ctypes.c_size_t)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("address", type=lambda s: int(s, 16), help="guest address of the word (hex)")
    ap.add_argument("--exe", default=r"D:\rpcs3\rpcs3.exe")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--set-bits", type=lambda s: int(s, 16))
    group.add_argument("--clear-bits", type=lambda s: int(s, 16))
    group.add_argument("--value", type=lambda s: int(s, 16))
    args = ap.parse_args()

    pid = next(p.pid for p in psutil.process_iter(["exe"]) if (p.info["exe"] or "").lower() == args.exe.lower())
    h = k32.OpenProcess(0x0008 | 0x0010 | 0x0020, False, pid)   # VM_OPERATION | VM_READ | VM_WRITE
    if not h:
        raise SystemExit("OpenProcess failed: %d" % ctypes.get_last_error())
    addr, buf, n = GUEST_BASE + args.address, ctypes.create_string_buffer(4), ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, addr, buf, 4, ctypes.byref(n)):
        raise SystemExit("read failed: %d" % ctypes.get_last_error())
    old = struct.unpack(">I", buf.raw)[0]
    new = old
    if args.set_bits is not None:
        new = old | args.set_bits
    elif args.clear_bits is not None:
        new = old & ~args.clear_bits
    elif args.value is not None:
        new = args.value
    if new != old:
        data = ctypes.create_string_buffer(struct.pack(">I", new), 4)
        if not k32.WriteProcessMemory(h, addr, data, 4, ctypes.byref(n)):
            raise SystemExit("write failed: %d" % ctypes.get_last_error())
    print("0x%08x: 0x%08x -> 0x%08x" % (args.address, old, new))


if __name__ == "__main__":
    main()
