"""Web admin for the DUST 514 revival server: battle host settings, documents, market, stores, rewards, wallet
and live status. Runs inside the CREST server process (listen_server.py) on its own port, Python stdlib only.

    python listen_server.py --admin-port 8088          # 0 switches it off
    DUST_ADMIN_TOKEN=<secret>                           # else generated once into state/admin_token.txt

Login with the token sets a session cookie (HttpOnly, SameSite=Strict); scripts can send
"Authorization: Bearer <token>" instead. Requests that change something must be JSON (no cross-site forms).

Host restart (a game mode change needs one, the running host crashes switching in place):
  DUST_HOST_CONTROL_DIR  folder of the Docker watchdog (docker/host/watchdog.py): creates <dir>/restart and
                         reads <dir>/status.json
  DUST_HOST_RESTART_CMD  otherwise a shell command (on Windows default: tools/restart_host.ps1)
"""

import gzip
import hmac
import http.server
import json
import mimetypes
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import content
import crest_app
import offline_bridge
import server_status
import store

BASE_DIR = Path(__file__).resolve().parent
UI_DIR = BASE_DIR / "admin_ui"
STATE_DIR = BASE_DIR / "state"
TOKEN_FILE = STATE_DIR / "admin_token.txt"
DEV_COMMANDS = BASE_DIR / "dev_commands.json"
FAKE_BATTLE = BASE_DIR / "fake_battle.json"
DOCUMENTS_DIR = crest_app.RESPONSES_DIR / "documents"

SESSION_COOKIE = "dust_admin_session"
SESSION_SECONDS = 12 * 3600
MAX_BODY = 4 * 1024 * 1024
_sessions = {}  # session id -> expiry
_file_lock = threading.Lock()

DOCUMENTS = {  # key -> label; keys from crest_app.DOCUMENT_KEYS
    "motd": "Message of the day",
    "importantMessage": "Important message",
    "patchNotes": "Patch notes",
    "communityEvents": "Community events",
    "readMe": "Read me (launcher news tab)",
    "serverNotAvailable": "Server not available",
    "eula": "EULA (must not be empty)",
    "privacyPolicy": "Privacy policy",
    "nda": "NDA",
    "ageConfirmation": "Age confirmation",
}

# Game mode levels tried on the listen-server host (docs/battle_feasibility.md, experiment 9; set_host_mode.py).
TESTED_MODES = {
    "MN_Craters01_BG01_AmbA": "works with 2 players",
    "MN_Craters01_BG01_SkB": "works with 2 players",
    "MN_Craters01_BG01_DomB": "works with 2 players",
    "MN_Highland01_BG01_Dom20A": "loads, spawn in a red zone",
    "MN_Craters01_BG01_OmsA": "untested",
}
TESTED_LIGHTING = "MOOD_DAY"
# Start options a running host can only change by restarting (switching the mode in place crashes it).
RESTART_OPTIONS = ("gametype", "gameModeLevel", "bfid", "battleID")


# --- token and sessions -----------------------------------------------------------------------------

def admin_token():
    token = os.environ.get("DUST_ADMIN_TOKEN")
    if token:
        return token
    if not TOKEN_FILE.exists():
        STATE_DIR.mkdir(exist_ok=True)
        TOKEN_FILE.write_text(secrets.token_urlsafe(18) + "\n", encoding="utf-8")
        print(f"admin token generated in {TOKEN_FILE}: {TOKEN_FILE.read_text().strip()}", flush=True)
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def new_session():
    now = time.time()
    for sid, expiry in list(_sessions.items()):
        if expiry < now:
            del _sessions[sid]
    sid = secrets.token_urlsafe(24)
    _sessions[sid] = now + SESSION_SECONDS
    return sid


# --- host settings: the map start in dev_commands.json and the battle finder entry in fake_battle.json ----

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_start(command):
    """'Start <map>?a=b?flag' -> (map, [(key, value or None), ...])"""
    if not command or not command.startswith("Start "):
        return None, []
    url = command[len("Start "):]
    parts = url.split("?")
    options = [(p.split("=", 1)[0], p.split("=", 1)[1] if "=" in p else None) for p in parts[1:] if p]
    return parts[0], options


def build_start(map_name, options):
    return "Start " + map_name + "".join(f"?{k}" if v is None else f"?{k}={v}" for k, v in options)


def set_option(options, key, value):
    for i, (k, _) in enumerate(options):
        if k.lower() == key.lower():
            options[i] = (k, value)
            return
    options.append((key, value))


def get_option(options, key, default=None):
    return next((v for k, v in options if k.lower() == key.lower()), default)


def start_command_entry(dev):
    return next((c for c in dev["commands"] if c.get("action") == "ue3" and str(c.get("arg", "")).startswith("Start ")),
                None)


def host_member_entry(dev):
    return next((c for c in dev["commands"] if c.get("action") == "battle_member" and (c.get("arg") or {}).get("host")),
                None)


def host_settings():
    dev, battle = read_json(DEV_COMMANDS), read_json(FAKE_BATTLE)
    map_name, options = parse_start((start_command_entry(dev) or {}).get("arg"))
    member = (host_member_entry(dev) or {}).get("arg") or {}
    target = battle.get("target_listen") or {}
    return {
        "map": map_name, "game_type": get_option(options, "gametype"), "game_mode_level": get_option(options, "gameModeLevel"),
        "bfid": int(get_option(options, "bfid", 0) or 0), "terraform": get_option(options, "Terraform"),
        "lighting": get_option(options, "LightingMode"), "battle_id": int(get_option(options, "battleID", 0) or 0),
        "host_name": get_option(options, "Name"), "host_team": int(get_option(options, "Team", member.get("team", 0)) or 0),
        "battle_name": battle.get("name"), "mode_id": battle.get("mode_id"), "mode_name": battle.get("mode_name"),
        "client_team": battle.get("listen_team", "defender"), "finder_enabled": bool(battle.get("enabled")),
        "variant": battle.get("variant"), "listen_address": target.get("address"), "listen_port": target.get("port"),
        "theatre_name": battle.get("theatre_name", "Lokale Gefechte"),
        "theatre_description": battle.get("theatre_description", "Testgefecht des lokalen Servers"),
        "revision": dev.get("revision"), "start_command": build_start(map_name, options) if map_name else None,
    }


def save_host_settings(s, bump_revision):
    """Write the settings into dev_commands.json and fake_battle.json; returns the new start command."""
    for key in ("map", "game_type", "game_mode_level", "terraform", "lighting", "host_name"):
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", str(s.get(key) or "")):
            raise ValueError(f"invalid value for {key}: {s.get(key)!r}")
    if s.get("client_team") not in ("attacker", "defender"):
        raise ValueError("client_team must be attacker or defender")
    with _file_lock:
        dev, battle = read_json(DEV_COMMANDS), read_json(FAKE_BATTLE)
        entry = start_command_entry(dev)
        if not entry:
            raise ValueError("dev_commands.json has no start command")
        _, options = parse_start(entry["arg"])
        for key, value in (("gametype", s["game_type"]), ("gameModeLevel", s["game_mode_level"]), ("bfid", int(s["bfid"])),
                           ("Terraform", s["terraform"]), ("LightingMode", s["lighting"]),
                           ("battleID", int(s["battle_id"])), ("Team", int(s["host_team"])), ("Name", s["host_name"])):
            set_option(options, key, str(value))
        entry["arg"] = build_start(s["map"], options)
        member = host_member_entry(dev)
        if member:
            member["arg"]["team"] = int(s["host_team"])
        if bump_revision:
            dev["revision"] = int(dev.get("revision") or 0) + 1
        battle.update({
            "battle_id": int(s["battle_id"]), "name": str(s["battle_name"])[:60], "mode_id": int(s["mode_id"]),
            "mode_name": str(s["mode_name"])[:40], "listen_team": s["client_team"], "enabled": bool(s["finder_enabled"]),
            "theatre_name": str(s["theatre_name"])[:60], "theatre_description": str(s["theatre_description"])[:200],
            "target_listen": {"address": str(s["listen_address"]), "port": int(s["listen_port"])},
        })
        write_json(DEV_COMMANDS, dev)
        write_json(FAKE_BATTLE, battle)
        return entry["arg"], dev["revision"]


def restart_needed(running, configured):
    """True if the running host must restart to get `configured` (another mode, map, level or battle)."""
    if not running or not configured:
        return False
    (map_a, opt_a), (map_b, opt_b) = parse_start(running), parse_start(configured)
    return map_a != map_b or any(get_option(opt_a, key) != get_option(opt_b, key) for key in RESTART_OPTIONS)


def bump_revision():
    with _file_lock:
        dev = read_json(DEV_COMMANDS)
        dev["revision"] = int(dev.get("revision") or 0) + 1
        write_json(DEV_COMMANDS, dev)
        return dev["revision"]


def restart_method():
    control = os.environ.get("DUST_HOST_CONTROL_DIR")
    if control:
        return "control", control
    command = os.environ.get("DUST_HOST_RESTART_CMD")
    if not command and os.name == "nt" and (BASE_DIR.parent / "tools" / "restart_host.ps1").exists():
        command = "powershell -NoProfile -ExecutionPolicy Bypass -File tools\\restart_host.ps1"
    return ("command", command) if command else (None, None)


def restart_host():
    method, target = restart_method()
    if method is None:
        raise ValueError("No restart method configured (DUST_HOST_CONTROL_DIR or DUST_HOST_RESTART_CMD)")
    if method == "control":
        Path(target).mkdir(parents=True, exist_ok=True)
        (Path(target) / "restart").write_text(time.strftime("%Y-%m-%d %H:%M:%S admin\n"))
    else:
        subprocess.Popen(target, shell=True, cwd=BASE_DIR.parent, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    clear_members()
    return method


def clear_members():
    # A new host process registers members from scratch; old entries belong to clients of the old map.
    with crest_app.LISTEN_LOCK:
        crest_app.LISTEN_MEMBERS.clear()
        crest_app.PENDING_CONNECTS.clear()


def watchdog_status():
    control = os.environ.get("DUST_HOST_CONTROL_DIR")
    if not control:
        return None
    try:
        return json.loads((Path(control) / "status.json").read_text())
    except (OSError, ValueError):
        return None


# --- status -------------------------------------------------------------------------------------------

def catma_status():
    try:
        request = urllib.request.Request(offline_bridge.SERVICE_URL, json.dumps(
            {"method": "Get", "path": "/dust/ps3client/configuration/"}).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=3) as response:
            json.loads(response.read())
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": repr(e)}


def status():
    host = dict(server_status.HOST)
    try:
        configured = host_settings()
    except Exception as e:
        configured = {"error": repr(e)}
    now = time.time()
    online = server_status.host_online()
    method, _ = restart_method()
    with crest_app.LISTEN_LOCK:
        members = list(crest_app.LISTEN_MEMBERS)
        pending = len(crest_app.PENDING_CONNECTS)
    return {
        "time": now, "server_started": server_status.STARTED,
        "catma": catma_status(),
        "host": {
            "online": online, "last_poll_age": now - host["last_poll"] if host["last_poll"] else None,
            "last_members_poll_age": now - host["last_members_poll"] if host["last_members_poll"] else None,
            "started": host["started"], "revision": host["revision"], "running_start": host["start_command"],
            "file_revision": configured.get("revision"), "configured_start": configured.get("start_command"),
            "restart_needed": online and restart_needed(host["start_command"], configured.get("start_command")),
            "pending_revision": online and host["revision"] != configured.get("revision"),
            "restart_method": method, "watchdog": watchdog_status(),
        },
        "members": members, "pending_connects": pending, "notification_streams": len(crest_app.HUB.streams),
        "missing": server_status.MISSING.most_common(50),
        "recent": list(server_status.RECENT)[-150:],
    }


# --- content validation -------------------------------------------------------------------------------

def _int(value, minimum=0):
    value = int(value)
    if value < minimum:
        raise ValueError(f"value {value} < {minimum}")
    return value


def _overrides(raw):
    result = {}
    for type_id, entry in (raw or {}).items():
        clean = {}
        if "enabled" in entry and entry["enabled"] is not None:
            clean["enabled"] = bool(entry["enabled"])
        if entry.get("price") not in (None, ""):
            clean["price"] = _int(entry["price"], 1)
        if clean:
            result[str(int(type_id))] = clean
    return result


def clean_content(name, data):
    if name == "market":
        return {"enabled": bool(data.get("enabled", True)),
                "excluded_groups": [int(g) for g in data.get("excluded_groups", [])],
                "hidden_groups": [int(g) for g in data.get("hidden_groups", [])],
                "items": _overrides(data.get("items"))}
    if name == "aur_store":
        return {"enabled": bool(data.get("enabled", True)), "items": _overrides(data.get("items"))}
    if name == "loyalty":
        stores = {}
        for corp in content.LOYALTY_STORES:
            store = (data.get("stores") or {}).get(str(corp)) or {}
            stores[str(corp)] = {"balance": _int(store.get("balance", 0)),
                                 "offers": {str(int(t)): {"lp": _int(o.get("lp", 0)), "isk": _int(o.get("isk", 0))}
                                            for t, o in (store.get("offers") or {}).items()}}
        return {"stores": stores}
    if name == "rewards":
        days = [{"sp": _int(d.get("sp", 0)), "aur": _int(d.get("aur", 0))} for d in data.get("daily_login", [])]
        if not 1 <= len(days) <= 31:
            raise ValueError("1 to 31 login days")
        return {"daily_login": days}
    if name == "wallet":
        return {"isk": _int(data.get("isk", 0)), "aur": _int(data.get("aur", 0))}
    if name == "storefront":
        layout = data.get("layout")
        if layout is not None and not isinstance(layout, dict):
            raise ValueError("layout must be an object or null")
        return {"layout": layout}
    raise KeyError(name)


# --- HTTP ---------------------------------------------------------------------------------------------

class AdminError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "DustAdmin/1"

    def log_message(self, fmt, *args):
        pass

    # helpers
    def send_json(self, data, status=200, headers=None):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_body(body, "application/json; charset=utf-8", status, headers)

    def send_body(self, body, content_type, status=200, headers=None):
        if len(body) > 4096 and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, 6)
            headers = {**(headers or {}), "Content-Encoding": "gzip"}
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise AdminError(415, "JSON expected")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise AdminError(413, "too large")
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise AdminError(400, "invalid JSON")

    def session(self):
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE and _sessions.get(value, 0) > time.time():
                return value
        return None

    def authorized(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].encode(), admin_token().encode()):
            return True
        return self.session() is not None

    # dispatch
    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        path = self.path.split("?")[0]
        try:
            if not path.startswith("/api/"):
                return self.static(path) if method == "GET" else self.send_json({"error": "not found"}, 404)
            if path == "/api/login" and method == "POST":
                return self.login()
            if path == "/api/logout" and method == "POST":
                _sessions.pop(self.session(), None)
                return self.send_json({"ok": True}, headers={
                    "Set-Cookie": f"{SESSION_COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
            if not self.authorized():
                raise AdminError(401, "not logged in")
            if method == "POST":
                body = self.read_json()
            for m, pattern, func in API:
                match = re.fullmatch(pattern, path)
                if m == method and match:
                    args = match.groups()
                    return self.send_json(func(body, *args) if method == "POST" else func(*args))
            raise AdminError(404, "not found")
        except AdminError as e:
            self.send_json({"error": str(e)}, e.status)
        except (ValueError, KeyError, TypeError) as e:
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 400)
        except Exception as e:
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    def static(self, path):
        name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        file = (UI_DIR / name).resolve()
        if not re.fullmatch(r"[a-z0-9_\-]+\.(html|js|css|svg)", name) or file.parent != UI_DIR.resolve() or not file.exists():
            return self.send_json({"error": "not found"}, 404)
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.send_body(file.read_bytes(), content_type + "; charset=utf-8", headers={
            "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'"})

    def login(self):
        body = self.read_json()
        if not hmac.compare_digest(str(body.get("token", "")).encode(), admin_token().encode()):
            time.sleep(1)
            raise AdminError(401, "wrong token")
        sid = new_session()
        self.send_json({"ok": True}, headers={
            "Set-Cookie": f"{SESSION_COOKIE}={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}"})


def api_host_get():
    return {"settings": host_settings(), "tested_modes": TESTED_MODES, "tested_lighting": TESTED_LIGHTING}


def api_host_save(body):
    """{"settings": {...}, "apply": bool}: apply = restart the map now if the host can do it in place."""
    online = server_status.host_online()
    # Saved without a new revision: a mode change must not reach a running host in place (it crashes);
    # a restarted host runs the saved start on its own.
    command, revision = save_host_settings(body["settings"], bump_revision=False)
    needs_restart = online and restart_needed(server_status.HOST["start_command"], command)
    applied = False
    if body.get("apply") and online and not needs_restart:
        revision, applied = bump_revision(), True
    return {"start_command": command, "revision": revision, "host_online": online, "applied_in_place": applied,
            "restart_needed": needs_restart}


def api_host_reload_map(body):
    if server_status.host_online() and restart_needed(server_status.HOST["start_command"], host_settings()["start_command"]):
        raise AdminError(409, "The host runs a different mode; restart it first")
    return {"revision": bump_revision()}


def api_host_restart(body):
    return {"method": restart_host()}


def api_members_clear(body):
    clear_members()
    return {"ok": True}


def api_documents_get():
    return {"documents": [{"key": key, "label": DOCUMENTS.get(key, key),
                           "text": (DOCUMENTS_DIR / f"{key}.txt").read_text(encoding="utf-8")
                           if (DOCUMENTS_DIR / f"{key}.txt").exists() else ""}
                          for key in sorted(crest_app.DOCUMENT_KEYS, key=lambda k: list(DOCUMENTS).index(k)
                                            if k in DOCUMENTS else len(DOCUMENTS))]}


def api_document_save(body, key):
    if key not in crest_app.DOCUMENT_KEYS:
        raise AdminError(404, "unknown document")
    text = str(body.get("text", ""))
    if key == "eula" and not text.strip():
        raise AdminError(400, "The EULA must not be empty, otherwise the client disconnects")
    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCUMENTS_DIR / f"{key}.txt").write_text(text, encoding="utf-8", newline="\n")
    return {"ok": True}


def api_catalog():
    return content.catalog().raw


def api_catalog_reload(body):
    content._catalog.clear()
    cat = content.catalog()
    return {"items": len(cat.items), "groups": len(cat.groups)}


def api_content_get(name):
    if name not in content.DEFAULTS:
        raise AdminError(404, "unknown area")
    data = content.load(name)
    if name == "storefront" and not data["layout"]:
        data["ccp_default"] = crest_app.offline_result("/dust/storefront/10000001/")
    return data


def api_content_save(body, name):
    if name not in content.DEFAULTS:
        raise AdminError(404, "unknown area")
    data = clean_content(name, body)
    content.save(name, data)
    return data


def api_market_effective():
    return {"isk": content.isk_market(), "aur": content.aur_store()}


def api_characters():
    # Accounts and characters from store.py; without DUST_CHAR_STORE the database is not even opened.
    if not crest_app.CHAR_STORE:
        return {"enabled": False, "users": []}
    try:
        rules = content.skill_rules()
    except Exception:
        rules = None  # CATMA service without GET /skills (started before stage 2): no free SP
    db = store.get()
    users = []
    for user in db.users():
        chars = []
        for char in db.characters_of(user["id"]):
            known, total = db.skills_of(char["id"]), store.total_sp(char)
            chars.append({"id": char["id"], "name": char["name"], "specialty": char["specialty_id"],
                          "sp": total, "free_sp": rules.free_sp(total, known) if rules else None,
                          "sp_per_day": char["sp_per_day"], "passive": bool(char["passive_sp"]), "isk": char["isk"],
                          "skills": [{"id": t, "level": level} for t, level in known.items()]})
        users.append({"id": user["id"], "online_id": user["online_id"], "characters": chars})
    return {"enabled": True, "users": users}


def api_character_save(body, char_id):
    if not crest_app.CHAR_STORE:
        raise AdminError(409, "DUST_CHAR_STORE is off")
    db, char_id = store.get(), int(char_id)
    char = db.character(char_id)
    if not char:
        raise AdminError(404, "unknown character")
    before = db.skills_of(char_id)
    if "sp" in body:
        db.set_total_sp(char_id, max(0, _int(body["sp"])))
    if "isk" in body:
        db.update_character(char_id, isk=max(0, _int(body["isk"])))
    if body.get("reset_skills"):
        specialty = next(s for s in content.specialties() if s["id"] == char["specialty_id"])
        db.replace_skills(char_id, {s["skillTypeID"]: s["skillLevel"] for s in specialty["startingSkills"]})
    if isinstance(body.get("skill"), dict):
        # One skill at a level 0-5 (0 = book read, nothing trained) or removed (level null). No prerequisite or SP
        # check: the admin may set any state, e.g. to test a fitting.
        type_id, level = _int(body["skill"].get("typeID")), body["skill"].get("level")
        rules = content.skill_rules()
        if type_id not in rules.skills:
            raise AdminError(400, "not a skill")
        skills = dict(before)
        if level is None:
            skills.pop(type_id, None)
        else:
            skills[type_id] = min(_int(level), rules.max_level)
        db.replace_skills(char_id, skills)
    # Tell a running client (the game otherwise only sees this at the next login)
    if "sp" in body:
        crest_app.notify_skill_points(char_id)
    crest_app.notify_skill_changes(char_id, before, db.skills_of(char_id))
    return {"ok": True}


def api_skills():
    rules = content.skill_rules()
    return {"maxLevel": rules.max_level, "skills": [
        {"id": s["id"], "name": s["name"], "required": s["required"],
         "cost": [rules.cumulative_cost(s["id"], level) for level in range(rules.max_level + 1)]}
        for s in sorted(rules.skills.values(), key=lambda s: s["name"])]}


API = [
    ("GET", r"/api/status", status),
    ("GET", r"/api/host", api_host_get),
    ("POST", r"/api/host", api_host_save),
    ("POST", r"/api/host/reload-map", api_host_reload_map),
    ("POST", r"/api/host/restart", api_host_restart),
    ("POST", r"/api/members/clear", api_members_clear),
    ("GET", r"/api/documents", api_documents_get),
    ("POST", r"/api/documents/(\w+)", api_document_save),
    ("GET", r"/api/catalog", api_catalog),
    ("POST", r"/api/catalog/reload", api_catalog_reload),
    ("GET", r"/api/market/effective", api_market_effective),
    ("GET", r"/api/characters", api_characters),
    ("POST", r"/api/characters/(\d+)", api_character_save),
    ("GET", r"/api/skills", api_skills),
    ("GET", r"/api/content/(\w+)", api_content_get),
    ("POST", r"/api/content/(\w+)", api_content_save),
]


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


def start(host, port):
    admin_token()
    server = Server((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"web admin on http://{host}:{port}/", flush=True)
    return server
