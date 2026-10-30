"""Runs UE3 console commands once on the running listen-server host without restarting its map: writes a new
revision of dev_commands.json that holds only these commands, waits until the host has polled it, then puts the
normal command list back under the same revision (so the host does not run it again).

    python dev_once.py "set DustGameViewportClient bDisableWorldRendering true"
    python dev_once.py "stat fps" "stat unit"
"""
import argparse
import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "logs" / "client.log"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="+", help="UE3 console command(s)")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()

    path = HERE / "dev_commands.json"
    original = path.read_text(encoding="utf-8-sig")
    data = json.loads(original)
    revision = data["revision"] + 1
    once = {**data, "revision": revision, "commands": [{"action": "ue3", "arg": c} for c in args.command]}
    size = LOG.stat().st_size if LOG.exists() else 0
    path.write_text(json.dumps(once, indent=2) + "\n", encoding="utf-8")
    try:
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            time.sleep(1)
            if LOG.exists():
                with LOG.open("rb") as f:
                    f.seek(size)
                    if f"dev commands revision {revision}".encode() in f.read():
                        print(f"revision {revision} ran: {args.command}")
                        break
        else:
            print(f"revision {revision} not picked up within {args.timeout:.0f} s")
    finally:
        data["revision"] = revision
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
