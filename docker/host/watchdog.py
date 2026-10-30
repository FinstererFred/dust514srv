#!/usr/bin/env python3
"""Runs the DUST 514 battle host (RPCS3, headless) and keeps it running.

Restarts RPCS3 when it exits, when its log stops growing (hang), when the game inside stops polling the
CREST server (its Python can die while RPCS3 keeps running, e.g. when the server restarts), or when someone asks for it by
creating the file $CONTROL_DIR/restart (the web admin does this after a game-mode change, which the
running host cannot do in place). $CONTROL_DIR/stop stops the host until the file is removed.
The current state is written to $CONTROL_DIR/status.json.

Before each start the watchdog waits until the RPCN server from rpcn.yml answers and creates the host's
account there if it is missing (the game hangs at the PSN sign-in without it).

Environment (defaults in brackets):
  HOST_GAME_ARGS     arguments for the game  [-autologinserver=127.0.0.1:8080 -autologincharindex=0 -novsync]
  RPCS3_EXTRA_ARGS   extra RPCS3 options, e.g. "--stdout"  []
  CONTROL_DIR        restart/stop/status files  [/data/control]
  STARTUP_GRACE      seconds before hang detection starts (first boot compiles PPU/SPU caches)  [1200]
  HANG_TIMEOUT       seconds without log output that count as a hang  [180]
  HEARTBEAT_URL      CREST endpoint with the age of the game's last poll, "" = off
                     [http://127.0.0.1:8080/dev/host/heartbeat/]
  HEARTBEAT_TIMEOUT  seconds without a game poll (after the first one) before a restart  [120]
  RPCN_CHECK         "0" = start RPCS3 without waiting for RPCN  [1]
"""

import json
import os
import shlex
import signal
import socket
import ssl
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", "/data/config")) / "rpcs3"
CACHE_HOME = Path(os.environ.get("XDG_CACHE_HOME", "/data/cache")) / "rpcs3"
EBOOT = CONFIG_HOME / "dev_hdd0/game/NPUB30643/USRDIR/EBOOT.BIN"
RPCS3_LOG = CACHE_HOME / "RPCS3.log"
RPCN_CONFIG = CONFIG_HOME / "rpcn.yml"

GAME_ARGS = os.environ.get("HOST_GAME_ARGS", "-autologinserver=127.0.0.1:8080 -autologincharindex=0 -novsync")
EXTRA_ARGS = os.environ.get("RPCS3_EXTRA_ARGS", "")
CONTROL_DIR = Path(os.environ.get("CONTROL_DIR", "/data/control"))
STARTUP_GRACE = int(os.environ.get("STARTUP_GRACE", "1200"))
HANG_TIMEOUT = int(os.environ.get("HANG_TIMEOUT", "180"))
HEARTBEAT_URL = os.environ.get("HEARTBEAT_URL", "http://127.0.0.1:8080/dev/host/heartbeat/")
HEARTBEAT_TIMEOUT = int(os.environ.get("HEARTBEAT_TIMEOUT", "120"))
RPCN_CHECK = os.environ.get("RPCN_CHECK", "1") != "0"
HEARTBEAT_EVERY = 10
RPCN_RETRY = 5
STOP_TIMEOUT = 20
POLL = 2

_terminating = False


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def write_status(**fields):
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONTROL_DIR / "status.json.tmp"
    tmp.write_text(json.dumps({"updated": time.time(), **fields}, indent=1))
    tmp.replace(CONTROL_DIR / "status.json")


def take_request(name):
    """True (and the request file is consumed) if $CONTROL_DIR/<name> exists."""
    path = CONTROL_DIR / name
    if path.exists():
        path.unlink(missing_ok=True)
        return True
    return False


def log_size():
    try:
        return RPCS3_LOG.stat().st_size
    except FileNotFoundError:
        return 0


def heartbeat_age():
    """Seconds since the game last polled the CREST server, or None (no poll yet, server unreachable)."""
    try:
        with urllib.request.urlopen(HEARTBEAT_URL, timeout=3) as response:
            return json.load(response).get("age")
    except (OSError, ValueError):
        return None


def rpcn_settings():
    """Host, port, NPID and password from RPCS3's rpcn.yml (flat "Key: value" lines, password in plain text)."""
    values = {}
    for line in RPCN_CONFIG.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition(":")
        if sep and not line[:1].isspace():
            values[key.strip()] = value.strip().strip('"')
    host, _, port = values.get("Host", "").rpartition(":")
    return host, int(port or 31313), values.get("NPID", ""), values.get("Password", "")


def rpcn_packet(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("RPCN closed the connection")
        data += chunk
    return data


def rpcn_ensure_account():
    """Creates the host's RPCN account (protocol as in research/rpcn/create_account.py).

    Returns None when the account exists now, otherwise why not. RPCN closes the connection after a
    Create, so this costs one connection per start.
    """
    try:
        host, port, npid, password = rpcn_settings()
    except (OSError, ValueError) as e:
        return f"{RPCN_CONFIG} unreadable: {e}"
    if not host or not npid or not password:
        return f"{RPCN_CONFIG} lacks Host, NPID or Password"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # RPCN's certificate is self-signed
    # Create: npid, password, online name, avatar URL, email (NUL-terminated); header type u8, command u16,
    # size u32, packet id u64, little endian
    body = b"".join(s.encode() + bytes(1) for s in (npid, password, npid, "https://rpcs3.net/cdn/netplay/DefaultAvatar.png",
                                                  f"{npid.lower()}@dust514.invalid"))
    try:
        with socket.create_connection((host, port), timeout=5) as raw, ctx.wrap_socket(raw) as sock:
            for _ in range(2):  # server info, then the answer to Create
                if _:
                    sock.sendall(struct.pack("<BHIQ", 0, 2, 15 + len(body), 1) + body)
                size = struct.unpack("<BHIQ", rpcn_packet(sock, 15))[2]
                payload = rpcn_packet(sock, size - 15)
    except OSError as e:
        return f"RPCN at {host}:{port} unreachable: {e}"
    error = payload[0] if payload else None
    if error == 0:
        log(f"created RPCN account {npid}")
    # 11 = CreationExistingUsername, 13 = CreationExistingEmail
    return None if error in (0, 11, 13) else f"RPCN refused account {npid} (error {error})"


def wait_for_rpcn(restarts):
    reported = None
    while not _terminating and not (CONTROL_DIR / "stop").exists():
        problem = rpcn_ensure_account()
        if problem is None:
            return
        if problem != reported:
            log(f"waiting for RPCN: {problem}")
            reported = problem
        write_status(state="waiting", reason=problem, restarts=restarts)
        time.sleep(RPCN_RETRY)


def start_rpcs3():
    cmd = ["rpcs3", "--headless", *shlex.split(EXTRA_ARGS), str(EBOOT)]
    if GAME_ARGS.strip():
        # "--" ends RPCS3's own options, so the game arguments reach the game unparsed
        cmd += ["--", *shlex.split(GAME_ARGS)]
    log("starting: " + " ".join(cmd))
    return subprocess.Popen(cmd)


def stop_rpcs3(proc):
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        log("RPCS3 ignored SIGTERM, killing it")
        proc.kill()
        proc.wait()


def on_signal(signum, _frame):
    global _terminating
    _terminating = True
    log(f"signal {signum}, shutting down")


def run_once(restarts):
    """Runs RPCS3 until it exits, hangs or a restart/stop is requested. Returns the reason."""
    proc = start_rpcs3()
    started = time.time()
    last_size, last_growth = log_size(), started
    last_heartbeat_check, game_alive = 0.0, None  # game_alive = last time the game was seen polling
    write_status(state="running", pid=proc.pid, started=started, restarts=restarts)

    while True:
        time.sleep(POLL)
        now = time.time()

        if _terminating:
            stop_rpcs3(proc)
            return "terminated"
        if proc.poll() is not None:
            return f"exited with code {proc.returncode}"
        if take_request("restart"):
            stop_rpcs3(proc)
            return "restart requested"
        if (CONTROL_DIR / "stop").exists():
            stop_rpcs3(proc)
            return "stop requested"

        size = log_size()
        if size != last_size:
            last_size, last_growth = size, now
        elif now - started > STARTUP_GRACE and now - last_growth > HANG_TIMEOUT:
            log(f"no log output for {int(now - last_growth)} s, treating RPCS3 as hung")
            stop_rpcs3(proc)
            return "hang"

        if HEARTBEAT_URL and now - last_heartbeat_check >= HEARTBEAT_EVERY:
            last_heartbeat_check = now
            age = heartbeat_age()
            if age is not None and age < 2 * HEARTBEAT_EVERY:
                game_alive = now
            if game_alive is not None and now - game_alive > HEARTBEAT_TIMEOUT:
                log(f"the game has not polled the server for {int(now - game_alive)} s")
                stop_rpcs3(proc)
                return "game heartbeat lost"
            if game_alive is None and now - started > STARTUP_GRACE:
                log(f"the game has not polled the server within {STARTUP_GRACE} s")
                stop_rpcs3(proc)
                return "game never came up"


def main():
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    if not EBOOT.exists():
        sys.exit(f"{EBOOT} not found: the data volume is not set up (see docker/README.md)")

    restarts = 0
    quick_failures = 0
    while not _terminating:
        if (CONTROL_DIR / "stop").exists():
            write_status(state="stopped", restarts=restarts)
            time.sleep(POLL)
            continue

        if RPCN_CHECK:
            wait_for_rpcn(restarts)
            if _terminating or (CONTROL_DIR / "stop").exists():
                continue
        started = time.time()
        reason = run_once(restarts)
        log(f"RPCS3 ended: {reason}")
        if _terminating:
            break
        restarts += 1

        # Back off when RPCS3 keeps dying right after the start (broken data, missing firmware, ...)
        quick_failures = quick_failures + 1 if time.time() - started < 60 and reason.startswith("exited") else 0
        delay = min(300, 5 * 2 ** quick_failures) if quick_failures else 3
        write_status(state="restarting", reason=reason, restarts=restarts, next_start=time.time() + delay)
        deadline = time.time() + delay
        while not _terminating and time.time() < deadline:
            time.sleep(1)

    write_status(state="stopped", restarts=restarts)


if __name__ == "__main__":
    main()
