"""CREST application for the DUST 514 client: answers requests, falling back to CCP's offline handlers.

Lookup order for each request:
  1. our own handlers below (CREST root, OAuth login, token decode, device registration, ...)
  2. CCP's original offline handlers, run with the real CATMA DB (see offline_bridge.py)
  3. otherwise 404, logged as "missing" so we know what to implement next
"""

import datetime
import json
import queue
import re
import uuid
import urllib.parse
from pathlib import Path

import offline_bridge

RESPONSES_DIR = Path(__file__).resolve().parent / "responses"

USER_ID = 1000000720  # the user id CCP's offline data is built around
ACCESS_TOKEN = "dust-local-access-token"

# Document keys from dust/documentsClient.py. CDN documents are plain text files the client
# downloads through its HTTP cache; the EULA must not be empty or the client disconnects.
DOCUMENT_KEYS = ["ageConfirmation", "eula", "nda", "serverNotAvailable", "patchNotes",
                 "importantMessage", "privacyPolicy", "readMe", "motd", "communityEvents"]
DOCUMENT_TYPE_CDN = "DOC_CdnFile"

_routes = []  # (method, compiled regex, function)


class RawResponse:
    """A handler result that is sent as-is instead of being serialized to JSON."""

    def __init__(self, body: bytes, content_type: str, headers=None, status=200):
        self.body, self.content_type, self.headers, self.status = body, content_type, headers or {}, status


class StreamResponse:
    """A handler result whose body is produced by a generator and sent with chunked encoding."""

    def __init__(self, chunks, content_type="application/json"):
        self.chunks, self.content_type = chunks, content_type


class NotificationHub:
    """CREST notification streams (crest/notifications.py in the client).

    POST .../notifications/ answers with a Location header pointing at a stream; GET on the stream is
    a long poll that starts with "CCP_HELLO" and then sends one {"sn": n, "data": ...} line per
    notification, with empty lines as keep-alive (the client times out after 25 s).
    """

    KEEP_ALIVE_SECONDS = 10

    def __init__(self):
        self.streams = {}  # stream id -> {"owner": path, "queue": Queue, "sn": next sequence number}

    def create(self, owner):
        stream_id = uuid.uuid4().hex
        self.streams[stream_id] = {"owner": owner, "queue": queue.Queue(), "sn": 0}
        return stream_id

    def send(self, owner, data):
        """Queue a notification for every stream created by `owner` (e.g. '/characters/123/notifications/')."""
        for stream in self.streams.values():
            if stream["owner"] == owner:
                stream["queue"].put(data)

    def lines(self, stream_id):
        stream = self.streams[stream_id]
        yield b'"CCP_HELLO"\n'
        while True:
            try:
                data = stream["queue"].get(timeout=self.KEEP_ALIVE_SECONDS)
            except queue.Empty:
                yield b"\n"
                continue
            yield (json.dumps({"sn": stream["sn"], "data": data}) + "\n").encode()
            stream["sn"] += 1


HUB = NotificationHub()


def route(method, pattern):
    def register(func):
        _routes.append((method, re.compile(pattern), func))
        return func
    return register


@route("GET", r"^/$")
def crest_root(req):
    return json.loads((RESPONSES_DIR / "crest_root.json").read_text(encoding="utf-8").replace("{BASE}", req["base"]))


@route("GET", r"^/roots/dust/$")
def dust_root(req):
    found, root = offline_bridge.dispatch("GET", "/roots/dust/")
    # CCP's offline main root ("/") carries a few links the 03.19 client reads from the merged root
    # data but the offline DUST root lacks, e.g. infantryMarketGroups (myCharactersClient.py).
    found, offline_main_root = offline_bridge.dispatch("GET", "/")
    for key, value in offline_main_root.items():
        root.setdefault(key, value)
    # The online flow additionally reads these from the merged root data (dust/userBase.py).
    root.update({
        "authEndpoint": {"href": f"{req['base']}/oauth/token/"},
        "decode": {"href": f"{req['base']}/decode/"},
        "devices": {"href": f"{req['base']}/devices/"},
        "keepAlive": {"href": f"{req['base']}/keepalive/"},
    })
    return root


@route("POST", r"^/oauth/token/$")
def oauth_token(req):
    # Client sends grant_type=password, scope=dust and psn_ticket=<base64 NP ticket> (crest/authentication.py).
    return {
        "access_token": ACCESS_TOKEN,
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "dust-local-refresh-token",
    }


@route("GET", r"^/decode/$")
def token_decode(req):
    return {"user": {"id": USER_ID, "href": f"{req['base']}/users/{USER_ID}/"}}


@route("POST", r"^/devices/$")
def register_device(req):
    return {}


@route("GET", r"^/keepalive/$")
def keep_alive(req):
    return {}


SOLAR_SYSTEMS = {
    # id: (name, sovereignty) -- 30003552 is the home system of CCP's offline character (Ana, Domain).
    30003552: ("Ana", "Amarr Empire"),
}


@route("GET", r"^/solarsystems/(\d+)/$")
def solar_system(req):
    # The client only reads sovereignty.name (uiSvcHUD.py) from this System-v1 document.
    system_id = int(re.match(r"^/solarsystems/(\d+)/$", req["path"]).group(1))
    name, sovereignty = SOLAR_SYSTEMS.get(system_id, (f"System {system_id}", "Unknown"))
    return {"id": system_id, "name": name, "href": f"{req['base']}/solarsystems/{system_id}/",
            "sovereignty": {"name": sovereignty}}


def offline_result(path):
    """CCP's offline answer for `path`; raises if there is none, so callers only add fixes on top."""
    found, result = offline_bridge.dispatch("GET", path)
    if not found:
        raise LookupError(f"no offline handler for {path}")
    if isinstance(result, Exception):
        raise result
    return result


def id_from_href(href):
    m = re.search(r"/(\d+)/?$", href or "")
    return int(m.group(1)) if m else None


@route("GET", r"^/characters/(\d+)/mercenary/$")
def mercenary(req):
    merc = offline_result(req["path"])
    # 03.19 reads mercenaryPublicData['dustAgents'] (dustAgentClient.py); CCP's offline data predates it.
    merc.setdefault("dustAgents", {"href": f"{req['base']}{req['path']}agents/"})
    return merc


@route("GET", r"^/characters/(\d+)/mercenary/agents/$")
def mercenary_agents(req):
    return {"items": [], "totalCount": 0, "pageCount": 1}


@route("GET", r"^/locations/(\d+)/$")
def location(req):
    loc = offline_result(req["path"])
    # uiSvcMap reads solarSystem/constellation/region ids; the offline constellation only has an href.
    for key in ("station", "solarSystem", "constellation", "region"):
        part = loc.get(key)
        if isinstance(part, dict) and "id" not in part:
            part["id"] = id_from_href(part.get("href"))
    return loc


@route("GET", r"^/characters/(\d+)/mercenary/skills/boosters/$")
def boosters(req):
    data = offline_result(req["path"])
    # The offline data only knows booster kind 0; 03.19 also asks for kind 1 (boosterClient.GetBoosterLimits).
    # The valid kinds come from the client's CATMA data (boosterStaticClient), so cover a generous range.
    kinds = data.setdefault("kindInfo", {}).setdefault("items", [])
    known = {k.get("kind") for k in kinds}
    kinds.extend({"kind": kind, "stackLimit": 3, "multipliers": 1} for kind in range(10) if kind not in known)
    return data


# (SP, AUR) reward per consecutive login day; questsClient/welcomeScreen index this list.
DAILY_LOGIN_REWARDS = [(10000, 0), (15000, 0), (20000, 0), (25000, 0), (30000, 0), (35000, 0), (40000, 50)]


@route("GET", r"^/characters/(\d+)/mercenary/private/$")
def mercenary_private(req):
    data = offline_result(req["path"])
    # 03.19 reads mercenaryData['dailyQuest2Info']['href'] (questsClient.py); missing in the offline data.
    data.setdefault("dailyQuest2Info", {"href": f"{req['base']}{req['path']}dailyquest2/"})
    return data


@route("GET", r"^/characters/(\d+)/mercenary/private/dailyquest2/$")
def daily_quest2_info(req):
    return {"items": [{"day": day + 1, "spReward": sp, "aurumReward": aur}
                      for day, (sp, aur) in enumerate(DAILY_LOGIN_REWARDS)]}


@route("GET", r"^/corporations/\d+/members/\d+/roles/$")
def corporation_member_roles(req):
    # CorporationMemberRoleCollection-v1; an NPC corp member has no roles.
    return {"items": [], "totalCount": 0, "pageCount": 1}


@route("GET", r"^/dust/characters/(\d+)/vivox/$")
@route("POST", r"^/dust/characters/(\d+)/vivox/$")
def vivox(req):
    # Voice chat credentials (vivoxClient.py); there is no Vivox server, so these are placeholders.
    return {"vivoxUsername": "dust", "vivoxPassword": "dust", "vivoxServer": ""}


@route("GET", r"^/characters/\d+/dailybonusinfo/$")
def daily_bonus_info(req):
    # CCP's offline handler builds pseudo quests from the client's catma DB, which the server lacks.
    # welcomeScreen.py also reads the account-wide counter and whether today's rewards were claimed.
    return {"items": [], "consecutiveLogons": 1, "userConsecutiveLogons": 1, "lastCompletedID": None,
            "characterRewardReceived": False, "userRewardReceived": False}


@route("PUT", r"^/characters/\d+/mercenary/$")
def update_mercenary(req):
    # MercenaryUpdate-v1, e.g. {"aurSpent": 0}; CCP's offline handler has no PUT. Accepted, not stored yet.
    return {}


@route("POST", r"^/(users|characters)/\d+/notifications/$")
def create_notification_stream(req):
    stream_id = HUB.create(req["path"])
    return RawResponse(b"", "application/json", {"Location": f"{req['base']}/notifications/streams/{stream_id}/"}, status=201)


@route("GET", r"^/notifications/streams/(\w+)/$")
def notification_stream(req):
    stream_id = re.match(r"^/notifications/streams/(\w+)/$", req["path"]).group(1)
    if stream_id not in HUB.streams:
        return RawResponse(b'{"message": "unknown stream"}', "application/json", status=404)
    return StreamResponse(HUB.lines(stream_id))


@route("GET", r"^/time/$")
def server_time(req):
    # Parsed with '%Y-%m-%dT%H:%M:%S' (crest/util.py ParseDate).
    return {"time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")}


@route("GET", r"^/dust/asset/bundle/offline$")
def asset_bundle(req):
    # CCP's offline handler lists the asset archives on the client's own disk. The client already
    # has every archive installed, so there is nothing to stream.
    return []


@route("GET", r"^/corporations/(\d+)/$")
def corporation(req):
    found, corp = offline_bridge.dispatch("GET", req["path"])
    if not found or isinstance(corp, Exception):
        return corp
    # CCP's offline data has plain URL strings per logo size; the client reads logo[size]['href']
    # (corporationClient.GetLogoImage). Images are only used when already cached, else a default icon.
    corp_id = re.match(r"^/corporations/(\d+)/$", req["path"]).group(1)
    logo = corp.get("logo") or {}
    for size in ("32x32", "64x64", "128x128", "256x256"):
        logo[size] = {"href": f"{req['base']}/images/corporations/{corp_id}_{size.split('x')[0]}.png"}
    corp["logo"] = logo
    return corp


@route("GET", r"^/documents/$")
def documents(req):
    # CCP's offline list lacks "documentType", which the online client needs (documentsClient.py).
    return {"documents": [
        {"documentKey": key, "documentType": DOCUMENT_TYPE_CDN, "href": f"{req['base']}/cdn/documents/{key}.txt"}
        for key in DOCUMENT_KEYS
    ]}


@route("GET", r"^/cdn/documents/(\w+)\.txt$")
def document_content(req):
    key = re.match(r"^/cdn/documents/(\w+)\.txt$", req["path"]).group(1)
    path = RESPONSES_DIR / "documents" / f"{key}.txt"
    body = path.read_bytes() if path.exists() else b""
    return RawResponse(body, "text/plain; charset=utf-8", {"Cache-Control": "max-age=300"})


def parse_body(headers, body):
    if not body:
        return None
    content_type = headers.get("Content-Type", "")
    text = body.decode("utf-8", "replace")
    if "x-www-form-urlencoded" in content_type:
        return dict(urllib.parse.parse_qsl(text))
    try:
        return json.loads(text)
    except ValueError:
        return text


def content_type_for(headers):
    accept = headers.get("Accept", "").split(",")[0].strip()
    if not accept or accept == "*/*":
        return "application/json; charset=utf-8"
    if not accept.startswith("application/"):
        accept = "application/" + accept
    if not accept.endswith("+json") and "json" not in accept:
        accept += "+json"
    return accept + "; charset=utf-8"


class CrestApp:
    def handle(self, method, target, headers, body, base):
        """Return (status, content_type, payload bytes, source, extra headers) for one request."""
        url = urllib.parse.urlsplit(target)
        path = url.path
        req = {
            "method": method, "path": path, "query": dict(urllib.parse.parse_qsl(url.query)),
            "headers": headers, "body": parse_body(headers, body), "base": base,
        }
        result, source = None, None
        for m, regex, func in _routes:
            if m == method and regex.match(path):
                result, source = func(req), f"own:{func.__name__}"
                break
        else:
            found, result = offline_bridge.dispatch(method, path, parameters=req["query"], resource=req["body"])
            source = "ccp_offline" if found else None

        if source is None:
            return 404, "application/json; charset=utf-8", b'{"message": "not implemented"}', "missing", {}
        if isinstance(result, Exception):
            payload = json.dumps({"message": f"{type(result).__name__}: {result}"}).encode()
            return 500, "application/json; charset=utf-8", payload, f"{source}:error:{type(result).__name__}: {result}", {}
        if isinstance(result, RawResponse):
            return result.status, result.content_type, result.body, source, result.headers
        if isinstance(result, StreamResponse):
            return 200, result.content_type, result, source, {}
        text = json.dumps(result if result is not None else {}, default=str)
        text = text.replace(offline_bridge.OFFLINE_HOST, base)
        # offline.framework.MkURL (VGS store data) builds links without a port.
        text = text.replace('"http://127.0.0.1/', f'"{base}/')
        return 200, content_type_for(headers), text.encode("utf-8"), source, {}
