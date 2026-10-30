"""Regression check: without DUST_CHAR_STORE the CREST server must answer exactly as before the character server.

Runs the same requests (login, user and character documents, sub resources, wallet, skill book and upgrade) through
CrestApp in-process, once with the dust_server of a baseline commit and once with the working tree, and compares
status, body and log source. Needs the CATMA service (catma_service/offline_service.py); it only reads, apart from
CCP's no-op skill POST/PUT and our no-op mercenary PUT.

    python tools/legacy_parity.py                     # baseline e930d67 (before stage 1a), service on :8090
    python tools/legacy_parity.py --baseline <rev> --service http://127.0.0.1:8091

The baseline is the last commit whose legacy behaviour is wanted. Change it only on purpose, when a later commit
changes what the offline characters see (and say so in the commit message).

Exit code 0: identical; 1: differences (listed); 2: setup problem (no service, no git).
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = "e930d67"  # last commit before stage 1a
TOKEN = "dust-local-access-token"
CHAR, USER = 2100001611, 1000000720
GET_PATHS = [
    "/decode/", f"/users/{USER}/", f"/users/{USER}/mercenaries/", f"/characters/{CHAR}/", f"/characters/{CHAR}/private/",
    f"/characters/{CHAR}/mercenary/", f"/characters/{CHAR}/mercenary/private/", f"/characters/{CHAR + 1}/",
    f"/characters/{CHAR}/mail/", f"/characters/{CHAR}/chat/channels/", f"/characters/{CHAR}/quests/",
    f"/characters/{CHAR}/mercenary/fittings/", f"/characters/{CHAR}/mercenary/fittings/100/",
    f"/characters/{CHAR}/mercenary/skills/", f"/characters/{CHAR}/mercenary/skills/boosters/",
    f"/inventory/{CHAR}/owner/{CHAR}/all/", f"/corporations/1000205/members/{CHAR}/",
    f"/accounts/{CHAR}/", f"/accounts/{CHAR}/10000/", "/accounts/1000001/",
    f"/characters/{CHAR}/dailybonusinfo/", f"/dust/characters/{CHAR}/vivox/",
]
WRITES = [
    ("PUT", f"/characters/{CHAR}/mercenary/", {"aurSpent": 0}),
    ("POST", f"/characters/{CHAR}/mercenary/skills/", {"skillTypeID": 364555}),
    ("PUT", f"/characters/{CHAR}/mercenary/skills/364555/", {"skillTypeID": 364555, "currentLevel": 4, "aimLevel": 5}),
]


def ticket(online_id):
    """An RPCN-style ticket (same layout as np_ticket.build, inlined: the baseline has no np_ticket)."""
    def item(kind, value):
        return kind.to_bytes(2, "big") + len(value).to_bytes(2, "big") + value
    body = b"".join([item(8, b"\0" * 20), item(1, b"\0" * 4), item(7, b"\0" * 8), item(7, b"\0" * 8),
                     item(2, (1).to_bytes(8, "big")), item(4, online_id.encode().ljust(32, b"\0")),
                     item(8, b"br\0\0"), item(4, b"un\0\0"), item(8, b"UP5018-NPUB30643_00".ljust(24, b"\0")),
                     item(1, b"\0" * 4), item(0, b""), item(0, b"")])
    sections = item(0x3000, body) + item(0x3002, item(8, b"RPCN") + item(8, b"\0" * 62))
    return b"\x21\x01\0\0" + len(sections).to_bytes(4, "big") + sections


def run_requests(server_dir):
    """Child process: answers of the CrestApp in `server_dir`, one JSON line each."""
    sys.path.insert(0, server_dir)
    import crest_app
    app = crest_app.CrestApp()

    def call(method, path, body=None, form=False, token=TOKEN):
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        raw = b""
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
            raw = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
        status, _, payload, source, _ = app.handle(method, path, headers, raw, "https://127.0.0.1:8080", peer="127.0.0.9")
        print(json.dumps({"req": f"{method} {path}", "status": status, "source": source,
                          "body": payload.decode("utf-8", "replace") if isinstance(payload, bytes) else repr(payload)}))

    login = {"grant_type": "password", "scope": "dust", "psn_ticket": base64.b64encode(ticket("DustTester2")).decode()}
    call("POST", "/oauth/token/", login, form=True, token=None)
    for path in GET_PATHS:
        call("GET", path)
    for method, path, body in WRITES:
        call(method, path, body)


def answers(server_dir, service, state_dir):
    env = {k: v for k, v in os.environ.items() if k not in ("DUST_CHAR_STORE", "DUST_HOST_ACCOUNTS")}
    env.update({"DUST_OFFLINE_SERVICE": service, "DUST_STATE_DIR": state_dir,
                "DUST_CONTENT_DIR": str(ROOT / "dust_server" / "content"), "PYTHONIOENCODING": "utf-8"})
    out = subprocess.run([sys.executable, __file__, "--run", server_dir], env=env, capture_output=True, text=True,
                         encoding="utf-8", timeout=300)
    if out.returncode:
        raise RuntimeError(f"requests failed in {server_dir}:\n{out.stderr[-2000:]}")
    return [json.loads(line) for line in out.stdout.splitlines() if line.startswith("{")]


def compare(baseline=BASELINE, service=None):
    """List of differences between baseline and working tree (empty = identical). Raises on setup problems."""
    service = service or os.environ.get("DUST_OFFLINE_SERVICE", "http://127.0.0.1:8090")
    urllib.request.urlopen(f"{service}/catalog", timeout=120).close()  # reachable (and catalog built) or raise
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "baseline.tar"
        subprocess.run(["git", "-C", str(ROOT), "archive", "-o", str(archive), baseline, "dust_server"], check=True)
        with tarfile.open(archive) as tar:
            tar.extractall(Path(tmp) / "baseline", filter="data")
        old = answers(str(Path(tmp) / "baseline" / "dust_server"), service, str(Path(tmp) / "state_old"))
        new = answers(str(ROOT / "dust_server"), service, str(Path(tmp) / "state_new"))
    if len(old) != len(new):
        return [f"{len(old)} answers before, {len(new)} now"]
    return [f"{o['req']}: {o['status']} {o['source']} -> {n['status']} {n['source']}"
            + ("" if o["body"] == n["body"] else " (body differs)")
            for o, n in zip(old, new) if o != n]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument("--service")
    parser.add_argument("--run", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.run:
        run_requests(args.run)
        return 0
    try:
        diffs = compare(args.baseline, args.service)
    except Exception as e:
        print(f"setup problem: {e}", file=sys.stderr)
        return 2
    for diff in diffs:
        print("DIFF", diff)
    print(f"{'identical' if not diffs else f'{len(diffs)} differences'} "
          f"({len(GET_PATHS) + len(WRITES) + 1} requests, baseline {args.baseline})")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
