"""Live state of the running server for the web admin: recent requests, endpoints the client asked for that
nothing answers ("missing"), and what the listen-server host is doing (from its dev-command polls)."""

import collections
import re
import threading
import time

STARTED = time.time()
RECENT = collections.deque(maxlen=300)  # request log events, newest last
MISSING = collections.Counter()  # "METHOD /path" with numbers collapsed -> count
_lock = threading.Lock()

# A host polls /dev/commands/ every 3 s once it is in the merc quarters (client_patch/dustdevhook.py); a gap
# longer than this means it was restarted, and a fresh host runs whatever revision it gets first.
HOST_GAP_SECONDS = 30
HOST = {
    "last_poll": None,  # time of the last /dev/commands/ poll of the host (port 8080)
    "last_members_poll": None,
    "started": None,  # first poll after a gap
    "revision": None,  # revision the host has run (it runs every new revision once)
    "start_command": None,  # the map start command of that revision
}


def record(event):
    if event.get("kind") != "http":
        return
    with _lock:
        RECENT.append({key: event.get(key) for key in ("time", "port", "peer", "request", "status", "source")})
        if (event.get("source") or "").startswith("missing"):
            method, target = (event.get("request") or "? ?").split(" ")[:2]
            MISSING[method + " " + re.sub(r"/\d+", "/N", target.split("?")[0])] += 1


def host_polled(revision, start_command):
    now = time.time()
    with _lock:
        if HOST["last_poll"] is None or now - HOST["last_poll"] > HOST_GAP_SECONDS:
            HOST["started"] = now
            HOST["revision"] = None
        if revision and revision != HOST["revision"]:
            HOST["revision"], HOST["start_command"] = revision, start_command
        HOST["last_poll"] = now


def host_members_polled():
    HOST["last_members_poll"] = time.time()


def host_online():
    return HOST["last_poll"] is not None and time.time() - HOST["last_poll"] <= HOST_GAP_SECONDS
