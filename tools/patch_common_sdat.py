"""Adds the modules from client_patch/ to the client's COMMON.SDAT (a plain, uncompressed zip).

The PS3 build of Python cannot compile .py sources, so every client_patch/*.py is compiled to Python
2.7 bytecode (.pyo) with the conda environment in tools/py27 first. A patch module that replaces an
existing one keeps the original in the archive as <name>_orig.pyo.

The original archive is kept as COMMON.SDAT.orig and every run rebuilds from it.

    python tools/patch_common_sdat.py            # apply client_patch/*.py
    python tools/patch_common_sdat.py --restore  # put the original archive back

DUST_GAME_DIR selects another installation, e.g. the second RPCS3 copy for the multiplayer test.
"""

import argparse
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAME_DIR = Path(os.environ.get("DUST_GAME_DIR", r"D:\rpcs3\dev_hdd0\game\NPUB30643\USRDIR\DUSTGAME"))
PATCH_DIR = ROOT / "client_patch"
PY27 = ROOT / "tools" / "py27" / "python.exe"


def compile_py27(source: Path, target: Path):
    code = "import py_compile, sys; py_compile.compile(sys.argv[1], cfile=sys.argv[2], doraise=True)"
    subprocess.run([str(PY27), "-O", "-c", code, str(source), str(target)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--restore", action="store_true", help="restore the original COMMON.SDAT")
    args = parser.parse_args()

    target = GAME_DIR / "COMMON.SDAT"
    original = GAME_DIR / "COMMON.SDAT.orig"
    if not original.exists():
        shutil.copy2(target, original)
        print(f"backup: {original}")

    if args.restore:
        shutil.copy2(original, target)
        print(f"restored {target}")
        return

    with tempfile.TemporaryDirectory() as build:
        compiled = {}
        for source in sorted(PATCH_DIR.glob("*.py")):
            pyo = Path(build) / (source.stem + ".pyo")
            compile_py27(source, pyo)
            compiled[pyo.name] = pyo.read_bytes()

        tmp = target.with_suffix(".tmp")
        with zipfile.ZipFile(original) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename in compiled:
                    renamed = info.filename[:-len(".pyo")] + "_orig.pyo"
                    info = zipfile.ZipInfo(renamed, date_time=info.date_time)
                    print(f"kept original as {renamed}")
                dst.writestr(info, data)
            for name, data in compiled.items():
                dst.writestr(zipfile.ZipInfo(name, date_time=(2015, 4, 10, 16, 48, 38)), data)
                print(f"added {name}")
    tmp.replace(target)
    print(f"patched {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
