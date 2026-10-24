"""Sets the size of one file in DUST 514's PS3TOC.TXT to the file's actual size (byte-exact, CRLF kept).

    python tools/set_toc_size.py Movies/Intro.bik

DUST_GAME_DIR selects another installation, e.g. the second RPCS3 copy for the multiplayer test.
"""

import os
import re
import sys
from pathlib import Path

GAME_DIR = Path(os.environ.get("DUST_GAME_DIR", r"D:\rpcs3\dev_hdd0\game\NPUB30643\USRDIR\DUSTGAME"))


def main():
    rel = sys.argv[1].replace("/", "\\")
    toc = GAME_DIR / "PS3TOC.TXT"
    data = toc.read_bytes()
    entry = ("..\\DustGame\\" + rel).encode()
    pattern = re.compile(rb"^(\d+)( 0 0 " + re.escape(entry) + rb" )", re.M | re.I)
    matches = list(pattern.finditer(data))
    if len(matches) != 1:
        sys.exit(f"expected exactly one TOC entry for {entry!r}, found {len(matches)}")
    size = (GAME_DIR / rel.replace("\\", "/")).stat().st_size
    m = matches[0]
    toc.write_bytes(data[:m.start(1)] + str(size).encode() + data[m.end(1):])
    print(f"{rel}: {m.group(1).decode()} -> {size}")


if __name__ == "__main__":
    main()
