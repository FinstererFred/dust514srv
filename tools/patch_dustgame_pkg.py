"""Patches UnrealScript bytecode in the game's DUSTGAME.XXX (cooked, uncompressed UE3 package).

DustDataLog.IsEnabled returns WorldInfo.NetMode == NM_DedicatedServer (1); the listen host runs as NM_ListenServer (2),
so it logs nothing and the dev hook cannot follow who holds the objectives (MCC barrage, client_patch/dustdevhook.py).
The patch compares with 2 instead. The original package is kept as DUSTGAME.XXX.orig and every run patches from it.

    python tools/patch_dustgame_pkg.py            # apply
    python tools/patch_dustgame_pkg.py --restore  # put the original package back

DUST_GAME_DIR selects another installation (default: the host in D:\\rpcs3).
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from upk import Pkg  # noqa: E402

GAME_DIR = Path(os.environ.get("DUST_GAME_DIR", r"D:\rpcs3\dev_hdd0\game\NPUB30643\USRDIR\DUSTGAME"))
PACKAGE = GAME_DIR / "COOKEDPS3" / "DUSTGAME.XXX"

# function, old bytes, new bytes (unique within the function's bytecode)
PATCHES = [
    # return byte(WorldInfo.NetMode) == byte(1)  ->  == byte(2)
    ("DustDataLog.IsEnabled", bytes.fromhex("383a240116"), bytes.fromhex("383a240216")),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--restore", action="store_true", help="restore the original package")
    args = parser.parse_args()

    original = PACKAGE.with_name(PACKAGE.name + ".orig")
    if args.restore:
        shutil.copy2(original, PACKAGE)
        print(f"restored {PACKAGE}")
        return
    if not original.exists():
        shutil.copy2(PACKAGE, original)
        print(f"kept original as {original.name}")

    pkg = Pkg(str(original))
    data = bytearray(pkg.f)
    exports = {pkg.path(i + 1): e for i, e in enumerate(pkg.exports)}
    for path, old, new in PATCHES:
        e = exports[path]
        start, end = e["off"], e["off"] + e["size"]
        at = data.find(old, start, end)
        if at < 0 or data.find(old, at + 1, end) >= 0:
            raise SystemExit(f"{path}: pattern {old.hex()} not found exactly once")
        data[at:at + len(new)] = new
        print(f"{path}: {old.hex()} -> {new.hex()} at file offset {at:#x}")
    PACKAGE.write_bytes(data)
    print(f"patched {PACKAGE}")


if __name__ == "__main__":
    main()
