"""CREST application for the DUST 514 client: answers requests, falling back to CCP's offline handlers.

Lookup order for each request:
  1. our own handlers below (CREST root, OAuth login, token decode, device registration, ...)
  2. CCP's original offline handlers, run with the real CATMA DB (see offline_bridge.py)
  3. otherwise 404, logged as "missing" so we know what to implement next
"""

import datetime
import json
import os
import queue
import re
import threading
import time
import uuid
import urllib.parse
from pathlib import Path

import content
import np_ticket
import offline_bridge
import server_status
import skills
import store

RESPONSES_DIR = Path(__file__).resolve().parent / "responses"

USER_ID = 1000000720  # the user id CCP's offline data is built around
OFFLINE_CHARACTER_ID = 2100001611  # CCP's "Offline Character 1", template for our own character documents
ACCESS_TOKEN = "dust-local-access-token"
REFRESH_TOKEN = "dust-local-refresh-token"

# Accounts and characters per RPCN account from store.py (docs/character_server_plan.md, stage 1a). Off by default:
# then every account shares CCP's offline user and characters as before. The listen-server host keeps CCP's offline
# character either way: logins of the accounts in DUST_HOST_ACCOUNTS get the shared token, and every request with
# that token (or none) is answered the old way.
CHAR_STORE = os.environ.get("DUST_CHAR_STORE") == "1"
HOST_ACCOUNTS = {a.strip() for a in os.environ.get("DUST_HOST_ACCOUNTS", "DustHost").split(",") if a.strip()}
STARTER = {  # stage 1a: every account gets an Amarr Enforcer until characters can be created (stage 3)
    "bloodline_id": 5, "race_id": 4, "specialty_id": 353915, "corporation_id": 1000205,
    "portrait_id": 2,  # myCharactersClient.GetPortraitIDByRace: Caldari 0, Gallente 1, Amarr 2, Minmatar 3
    "gender": 1, "npe_state": 1,  # as CCP's offline character 1
}

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
        self.streams = {}  # stream id -> {"owner": path, "peer": client_key(), "queue": Queue, "sn": next sequence number}

    def create(self, owner, peer=None):
        stream_id = uuid.uuid4().hex
        self.streams[stream_id] = {"owner": owner, "peer": peer, "queue": queue.Queue(), "sn": 0}
        return stream_id

    def send(self, owner, data, peer=None):
        """Queue a notification for every stream created by `owner` (e.g. '/characters/123/notifications/').

        With `peer` (client_key), only for streams opened by that client: all local players and the listen-server
        host share CCP's offline character, so the owner alone does not tell their clients apart.
        """
        for stream in self.streams.values():
            if stream["owner"] == owner and (peer is None or stream["peer"] == peer):
                stream["queue"].put(data)

    def base_of(self, owner):
        """The server address (req["base"]) the newest stream of `owner` was opened with, or None."""
        bases = [s["peer"][1] for s in self.streams.values() if s["owner"] == owner and s["peer"]]
        return bases[-1] if bases else None

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


def token_answer(token=ACCESS_TOKEN, refresh=REFRESH_TOKEN):
    return {"access_token": token, "token_type": "Bearer", "expires_in": store.TOKEN_LIFETIME, "refresh_token": refresh}


UNAUTHORIZED = RawResponse(b'{"message": "unknown token"}', "application/json", status=401)


@route("POST", r"^/oauth/token/$")
def oauth_token(req):
    # Client sends grant_type=password, scope=dust and psn_ticket=<base64 NP ticket> (crest/authentication.py);
    # after expires_in it sends grant_type=refresh_token with the refresh token and no ticket.
    body = req["body"] if isinstance(req["body"], dict) else {}
    if not CHAR_STORE:
        return token_answer()
    if body.get("grant_type") == "refresh_token":
        if body.get("refresh_token") == REFRESH_TOKEN:
            return token_answer()
        user = store.get().user_for_refresh_token(body.get("refresh_token", ""))
        return token_answer(*store.get().issue_token(user["id"])) if user else UNAUTHORIZED
    try:
        online_id = np_ticket.parse(body.get("psn_ticket", ""))["online_id"]
    except (np_ticket.TicketError, ValueError) as e:
        print(f"oauth: unreadable ticket ({e}), shared offline user", flush=True)
        return token_answer()
    if online_id in HOST_ACCOUNTS:
        return token_answer()
    user = store.get().user_for_online_id(online_id)
    if not store.get().characters_of(user["id"]):
        create_starter_character(user)
    return token_answer(*store.get().issue_token(user["id"]))


def create_starter_character(user):
    specialty = next(s for s in content.specialties() if s["id"] == STARTER["specialty_id"])
    name = user["online_id"]
    while store.get().name_taken(name):
        name += "_"
    return store.get().create_character(
        user["id"], name, STARTER["gender"], STARTER["bloodline_id"], STARTER["race_id"], specialty,
        STARTER["portrait_id"], STARTER["corporation_id"], npe_state=STARTER["npe_state"])


def bearer_token(req):
    auth = next((v for k, v in req["headers"].items() if k.lower() == "authorization"), "")
    return auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else None


def current_user(req):
    """The store's user for the request's token; None for the shared offline user (store off, host, no token).

    Raises Unauthorized for a token the store does not know (e.g. issued before its state was deleted).
    """
    token = bearer_token(req)
    if not CHAR_STORE or not token or token == ACCESS_TOKEN:
        return None
    user = store.get().user_for_token(token)
    if not user:
        raise Unauthorized()
    return user


class Unauthorized(Exception):
    pass


def own_character(req, char_id, private=False):
    """The store's character `char_id`, or None if the old (CCP offline) answer applies.

    IDs below store.FIRST_CHARACTER_ID are CCP's offline characters (the host's). Our IDs that do not exist, or
    another account's character on a private document, are a 404 (logged as missing:character), no fallback.
    """
    if not CHAR_STORE or char_id < store.FIRST_CHARACTER_ID:
        return None
    char = store.get().character(char_id)
    if not char or (private and (current_user(req) or {}).get("id") != char["user_id"]):
        raise CharacterMissing(char_id)
    return char


class CharacterMissing(Exception):
    pass


def own_character_in_path(req):
    """The store's character whose ID is in the path (/characters/N/..., /inventory/N/owner/N/..., ...), or None.

    Only the owner gets these documents: the fallback cannot tell public from private ones, and the private ones
    (mail, fittings, inventory, wallet) are the majority. Others get a 404 (missing:character) in the log.
    """
    if not CHAR_STORE:
        return None
    ids = {int(n) for n in re.findall(r"(?<!\d)(\d{10})(?!\d)", req["path"])}
    ids = [n for n in ids if store.FIRST_CHARACTER_ID <= n < store.FIRST_CHARACTER_ID + 100_000_000]
    return own_character(req, ids[0], private=True) if ids else None


@route("GET", r"^/decode/$")
def token_decode(req):
    user_id = (current_user(req) or {"id": USER_ID})["id"]
    return {"user": {"id": user_id, "href": f"{req['base']}/users/{user_id}/"}}


@route("POST", r"^/devices/$")
def register_device(req):
    return {}


@route("GET", r"^/keepalive/$")
def keep_alive(req):
    return {}


# --- Accounts and characters from store.py (CHAR_STORE) -------------------------------------------------------
# Our own documents start from CCP's answer for its offline user/character 1 with the IDs swapped (rebind), so every
# link the client knows stays; the fields that describe the character are then set from the store.

OFFLINE = object()  # handler result: answer as if there were no own handler (CCP's offline answer, logged as such)


def rebind(result, user_id, char_id):
    """`result` with CCP's offline user and character IDs replaced by ours."""
    text = json.dumps(result)
    text = re.sub(rf"\b{OFFLINE_CHARACTER_ID}\b", str(char_id), text)
    return json.loads(re.sub(rf"\b{USER_ID}\b", str(user_id), text))


def character_template(path, char):
    return rebind(offline_result(path.replace(f"/{char['id']}/", f"/{OFFLINE_CHARACTER_ID}/")),
                  char["user_id"], char["id"])


def link(req, path, **extra):
    return {"href": f"{req['base']}{path}", **extra}


def portrait_link(req, char):
    return link(req, f"/portraits/mercenary/{bool(char['gender'])}/{char['portrait_id']}/", id=char["portrait_id"])


def sp_per_day(char):
    # Without passive gain 0, so the client's local counter (skillClient) does not count up either.
    return char["sp_per_day"] if char["passive_sp"] else 0


def member_for(char):
    days = int((time.time() - char["created_at"]) // 86400)
    return f"Member for {days} day{'s' if days != 1 else ''}"


def mercenary_entry(req, char):
    """MercenaryCollection-v1 entry as read by characterCreation2 and myCharactersClient."""
    return {
        "character": link(req, f"/characters/{char['id']}/", id=char["id"], name=char["name"]),
        "self": f"{req['base']}/users/{char['user_id']}/mercenaries/{char['id']}/",
        "skillPoints": store.total_sp(char), "skillPointsPerDay": sp_per_day(char),
        "gender": bool(char["gender"]),
        "bloodline": link(req, f"/bloodlines/{char['bloodline_id']}/", id=char["bloodline_id"]),
        "portrait": portrait_link(req, char),
        "corporation": {**corporation_link(req, char["corporation_id"]), "memberFor": member_for(char)},
        "wealth": {"isk": float(char["isk"])},
        "specialty": link(req, f"/specialties/{char['specialty_id']}/", id=char["specialty_id"]),
        "npeState": char["npe_state"],
        "passiveSkillGain": {"status": char["passive_sp"], "self": link(
            req, f"/users/{char['user_id']}/mercenaries/passiveskillgain/{char['id']}/")},
        "favoriteFitting": None,
    }


def path_ids(req, pattern):
    return [int(x) for x in re.match(pattern, req["path"]).groups()]


@route("GET", r"^/users/(\d+)/$")
def user_document(req):
    user = current_user(req)
    if not user:
        return OFFLINE
    if path_ids(req, r"^/users/(\d+)/$")[0] != user["id"]:
        raise CharacterMissing(None)
    return {"mercenaries": link(req, f"/users/{user['id']}/mercenaries/"),
            "notifications": link(req, f"/users/{user['id']}/notifications/")}


@route("GET", r"^/users/(\d+)/mercenaries/$")
def user_mercenaries(req):
    user = current_user(req)
    if not user:
        return OFFLINE
    if path_ids(req, r"^/users/(\d+)/mercenaries/$")[0] != user["id"]:
        raise CharacterMissing(None)
    return collection([mercenary_entry(req, char) for char in store.get().characters_of(user["id"])])


@route("PUT", r"^/users/(\d+)/mercenaries/passiveskillgain/(\d+)/$")
def passive_skill_gain(req):
    # characterCreation2.ActivateSkillGainCallback: {"status": 1}; one character per account gains SP passively.
    char = own_character(req, path_ids(req, r"^/users/(\d+)/mercenaries/passiveskillgain/(\d+)/$")[1], private=True)
    if not char:
        return OFFLINE
    status = (req["body"] if isinstance(req["body"], dict) else {}).get("status", 1)
    store.get().set_passive(char["id"], 1 if status else 0)
    for other in store.get().characters_of(char["user_id"]):  # the account's other characters may have switched off
        notify_skill_points(other["id"])
    return {}


@route("GET", r"^/characters/(\d+)/$")
def character_document(req):
    char = own_character(req, path_ids(req, r"^/characters/(\d+)/$")[0])
    if not char:
        return OFFLINE
    doc = character_template(req["path"], char)
    corp = offline_result(f"/corporations/{char['corporation_id']}/")
    doc.update({
        "name": char["name"], "gender": char["gender"], "description": "", "skillPointsPerDay": float(sp_per_day(char)),
        "bloodLine": link(req, f"/bloodlines/{char['bloodline_id']}/", id=char["bloodline_id"]),
        "race": link(req, f"/races/{char['race_id']}/", id=char["race_id"]),
        "corporation": {**doc.get("corporation", {}), **corporation_link(req, char["corporation_id"]),
                        "logo": corp.get("logo") or doc.get("corporation", {}).get("logo")},
    })
    return doc


@route("GET", r"^/characters/(\d+)/private/$")
def character_private(req):
    char = own_character(req, path_ids(req, r"^/characters/(\d+)/private/$")[0], private=True)
    if not char:
        return OFFLINE
    doc = character_template(req["path"], char)
    corp_id = char["corporation_id"]
    doc.update({"corporation": corporation_link(req, corp_id),
                "corporationMember": link(req, f"/corporations/{corp_id}/members/{char['id']}/")})
    return doc


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


# Regions on the battle finder's star map. CCP's offline universe has none, but the client selects Sinq Laison
# (uiSvcMap.GetInitialData hardcodes 10000032) and travels from that selection; Domain is our battle's region.
# "hasChildren": False keeps the map at universe level, so no region/constellation data is needed.
MAP_REGIONS = [(10000032, "Sinq Laison", 0.35, 0.55), (10000043, "Domain", 0.65, 0.45)]


@route("GET", r"^/map/regions/$")
def map_universe(req):
    # MapUniverse-v1 (dust/mapClient.py, ui/starmapCommon.py GetNodeMap). Any KeyError in the star map is an
    # uncaught exception, which the client treats as a disconnect.
    universe = offline_result(req["path"])
    href = f"{req['base']}/map/regions/"
    universe.update({
        "href": href, "type": "universe",
        "boundary": {"xMin": 0, "xMax": 1, "yMin": 0, "yMax": 1},
        "regions": universe.get("regions") or [
            {"id": region_id, "name": name, "href": f"{href}{region_id}/",
             "position": {"u": u, "v": v, "flipped": False}, "weight": 0.0, "connections": [], "hasChildren": False}
            for region_id, name, u, v in MAP_REGIONS],
        "owners": {kind: {"href": f"{req['base']}/map/owners/{kind}/"} for kind in ("sovereignty", "districts")},
    })
    return universe


@route("GET", r"^/map/owners/(sovereignty|districts)/$")
def map_owners(req):
    # Sovereignty/district owners per map level (mapClient.GetOwners, uiSvcMap.GetOwners): nobody owns anything
    return {"map": {"href": f"{req['base']}/map/regions/"}, "regions": [], "constellations": [], "systems": []}


@route("GET", r"^/map/search/$")
def map_search(req):
    # MapSearchCollection-v1 (mapClient.SearchMap). No hits: the battle finder then leaves the star map as is.
    return {"items": [], "totalCount": 0, "pageCount": 1}


def id_from_href(href):
    m = re.search(r"/(\d+)/?$", href or "")
    return int(m.group(1)) if m else None


@route("GET", r"^/characters/(\d+)/mercenary/$")
def mercenary(req):
    char = own_character(req, path_ids(req, r"^/characters/(\d+)/mercenary/$")[0])
    if char:
        merc = character_template(req["path"], char)
        merc["portrait"] = portrait_link(req, char)
        # battleServer._MemberJoinedBattle loads a member's skills from here (stage 4, a real battle server)
        merc["battleSkills"] = merc["skills"]
    else:
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


def skill_href(req, char_id, type_id):
    return f"{req['base']}/characters/{char_id}/mercenary/skills/{type_id}/"


# Changes the client did not make itself (web admin, passive gain switched) reach a running client through its
# character's notification stream; skillClient listens for both (OnCharacterSkill...FromBackend). Without a stream,
# e.g. not logged in, they are dropped: the next login loads everything anyway.

def notify_character(char_id, name, body):
    HUB.send(f"/characters/{char_id}/notifications/", {"contentType": f"application/vnd.ccp.eve.{name}-v1", "body": body})


def notify_skill_points(char_id):
    char = store.get().character(char_id)
    if char:
        # skillClient.OnCharacterSkillPointChangeFromBackend; the weekly battle SP cap (stage 5) is not used yet.
        notify_character(char_id, "OnCharacterSkillPointChange", {
            "totalSkillPoints": store.total_sp(char), "skillPointsPerDay": sp_per_day(char),
            "skillPointsThisCycle": 0, "cycleCap": 0})


def notify_skill_changes(char_id, before, after):
    """skillClient.OnCharacterSkillChangeFromBackend for every skill that differs ({typeID: level}; level None =
    removed). The client keeps a skill's href for upgrades, so it needs the address its stream was opened with."""
    base = HUB.base_of(f"/characters/{char_id}/notifications/")
    if not base:
        return
    for type_id in sorted(set(before) | set(after)):
        if before.get(type_id) != after.get(type_id):
            notify_character(char_id, "OnCharacterSkillChange", {
                "typeID": type_id, "level": after.get(type_id),
                "href": f"{base}/characters/{char_id}/mercenary/skills/{type_id}/"})


@route("GET", r"^/characters/(\d+)/mercenary/skills/$")
def character_skills(req):
    # DustCharacterSkillCollection (skillClient._LoadKnownSkills); all on one page, no "next".
    char = own_character(req, path_ids(req, r"^/characters/(\d+)/mercenary/skills/$")[0], private=True)
    if not char:
        return OFFLINE
    return collection([{"skillTypeID": type_id, "skillLevel": level, "skillName": "",
                        "href": skill_href(req, char["id"], type_id)}
                       for type_id, level in store.get().skills_of(char["id"]).items()])


def skill_rejected(char, action, code):
    # The client checks first and runs these calls without error handling: an HTTP error would be an uncaught
    # exception (= disconnect). So answer 200 and log; the client reloads the skills right after and sees the truth.
    print(f"skills: {action} for character {char['id']} rejected: {skills.ERROR_TEXT.get(code, code)}", flush=True)
    return {}


@route("POST", r"^/characters/(\d+)/mercenary/skills/$")
def read_skill_book(req):
    # skillClient.UseSkillbook: {"skillTypeID"}; the skill becomes known at level 0. Skill books are not taken
    # from the inventory yet (CCP's offline inventory has 999 of everything, stage 5).
    char = own_character(req, path_ids(req, r"^/characters/(\d+)/mercenary/skills/$")[0], private=True)
    if not char:
        return OFFLINE
    type_id = int((req["body"] if isinstance(req["body"], dict) else {}).get("skillTypeID") or 0)
    rules, db = content.skill_rules(), store.get()
    with db.transaction():
        code = rules.check_book(db.skills_of(char["id"]), type_id)
        if code:
            return skill_rejected(char, f"book {type_id}", code)
        db.set_skill(char["id"], type_id, 0)
    return {}


@route("PUT", r"^/characters/(\d+)/mercenary/skills/(\d+)/$")
def upgrade_skill(req):
    # skillClient.UpgradeSkill: {"skillTypeID", "currentLevel", "aimLevel"}; costs SP (free SP = total - spent).
    char_id, type_id = path_ids(req, r"^/characters/(\d+)/mercenary/skills/(\d+)/$")
    char = own_character(req, char_id, private=True)
    if not char:
        return OFFLINE
    body = req["body"] if isinstance(req["body"], dict) else {}
    current, aim = int(body.get("currentLevel", -1)), int(body.get("aimLevel", -1))
    rules, db = content.skill_rules(), store.get()
    with db.transaction():
        char = db.character(char_id)
        code = rules.check_upgrade(db.skills_of(char_id), store.total_sp(char), type_id, current, aim)
        if code:
            return skill_rejected(char, f"upgrade {type_id} {current}->{aim}", code)
        db.set_skill(char_id, type_id, aim)
    return {}


@route("GET", r"^/characters/(\d+)/mercenary/private/$")
def mercenary_private(req):
    char = own_character(req, path_ids(req, r"^/characters/(\d+)/mercenary/private/$")[0], private=True)
    if char:
        data = character_template(req["path"], char)
        data.update({"ISKDiffSinceLastLogOff": 0, "SPDiffSinceLastLogOff": 0})
    else:
        data = offline_result(req["path"])
    # 03.19 reads mercenaryData['dailyQuest2Info']['href'] (questsClient.py); missing in the offline data.
    data.setdefault("dailyQuest2Info", {"href": f"{req['base']}{req['path']}dailyquest2/"})
    return data


@route("GET", r"^/characters/(\d+)/mercenary/private/dailyquest2/$")
def daily_quest2_info(req):
    # (SP, AUR) reward per consecutive login day (content/rewards.json); questsClient/welcomeScreen index this list.
    return {"items": [{"day": day + 1, "spReward": reward["sp"], "aurumReward": reward["aur"]}
                      for day, reward in enumerate(content.load("rewards")["daily_login"])]}


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


@route("PUT", r"^/characters/(\d+)/mercenary/$")
def update_mercenary(req):
    # MercenaryUpdate-v1, e.g. {"aurSpent": 0}; CCP's offline handler has no PUT. Stored for our own characters.
    char = own_character(req, path_ids(req, r"^/characters/(\d+)/mercenary/$")[0], private=True)
    body = req["body"] if isinstance(req["body"], dict) else {}
    fields = {column: int(body[key]) for key, column in
              (("portraitID", "portrait_id"), ("aurSpent", "aur_spent"), ("npeState", "npe_state"))
              if isinstance(body.get(key), (int, float, bool))}
    if char and fields:
        store.get().update_character(char["id"], **fields)
    return {}


@route("POST", r"^/(users|characters)/\d+/notifications/$")
def create_notification_stream(req):
    stream_id = HUB.create(req["path"], client_key(req))
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
    # The battle finder's star map loads the corporation's districts (corporationClient.GetDistrictsURI);
    # without the link the KeyError counts as an uncaught exception = disconnect. No planetary conquest here.
    corp.setdefault("districts", {"href": f"{req['base']}/corporations/{corp_id}/districts/"})
    return corp


@route("GET", r"^/corporations/(\d+)/districts/$")
def corporation_districts(req):
    # DistrictCollection-v1 (districtClient.GetCorporationDistricts reads "items")
    return {"items": [], "totalCount": 0, "pageCount": 1}


@route("GET", r"^/documents/$")
def documents(req):
    # CCP's offline list lacks "documentType", which the online client needs (documentsClient.py).
    # The file's modification time in the name makes the client's HTTP cache fetch edited texts.
    def version(key):
        path = RESPONSES_DIR / "documents" / f"{key}.txt"
        return int(path.stat().st_mtime) if path.exists() else 0
    return {"documents": [
        {"documentKey": key, "documentType": DOCUMENT_TYPE_CDN,
         "href": f"{req['base']}/cdn/documents/{key}.{version(key)}.txt"}
        for key in DOCUMENT_KEYS
    ]}


@route("GET", r"^/cdn/documents/(\w+?)(\.\d+)?\.txt$")
def document_content(req):
    key = re.match(r"^/cdn/documents/(\w+?)(\.\d+)?\.txt$", req["path"]).group(1)
    path = RESPONSES_DIR / "documents" / f"{key}.txt"
    body = path.read_bytes() if path.exists() else b""
    return RawResponse(body, "text/plain; charset=utf-8", {"Cache-Control": "max-age=300"})


# --- Market, stores and wallet: content/*.json, edited in the web admin (content.py, admin.py) ---------

MARKET_STATION = (60006418, "Ana")  # where CCP's offline character lives (see /locations/60006418/)
VGS_ACCOUNTS = {1000001: "AUR", 1000012: "LOP"}  # CCP's offline VGS accounts (offlineResourceVGS)
ISK_ACCOUNT_KEY = 10000  # the character's wallet in CCP's offline account collection


def collection(items, **extra):
    return {"items": items, "totalCount": len(items), "pageCount": 1, **extra}


def type_link(req, item):
    return {"id": item["id"], "href": f"{req['base']}/types/{item['id']}/", "name": item["name"]}


def market_group_href(req, group_id):
    return f"{req['base']}/market/groups/{group_id}/"


def items_in_group(req, prices):
    """(catalog item, price) for the items of `prices` in the market group from ?group= and the groups below it."""
    cat = content.catalog()
    group_id = id_from_href(req["query"].get("group"))
    groups = cat.subtree(group_id) if group_id in cat.groups else None
    return [(cat.items[type_id], price) for type_id, price in sorted(prices.items())
            if groups is None or cat.items[type_id]["categoryID"] in groups]


@route("GET", r"^/market/groups/$")
def market_groups(req):
    # MarketGroupCollection-v1: the whole tree at once (dustMarketClient._LoadGroup links children by parentGroup).
    cat = content.catalog()
    hidden = set()
    for group_id in content.load("market")["hidden_groups"]:
        hidden |= cat.subtree(group_id)
    groups = []
    for group_id in sorted(cat.market_groups() - hidden):
        group, href = cat.groups[group_id], market_group_href(req, group_id)
        entry = {"href": href, "name": group["name"], "description": group["description"] or "",
                 "types": {"href": f"{req['base']}/market/types/?group={href}"}}
        if group_id != cat.root and group["parent"]:
            entry["parentGroup"] = {"href": market_group_href(req, group["parent"])}
        groups.append(entry)
    return collection(groups)


@route("GET", r"^/market/types/$")
def market_types(req):
    # MarketTypeCollection-v1; the client takes the type href from here for the sell order lookup.
    return collection([{"type": type_link(req, item),
                        "marketGroup": {"href": market_group_href(req, item["categoryID"])}}
                       for item, _ in items_in_group(req, content.isk_market())])


@route("GET", r"^/market/(\d+)/prices/$")
def market_prices(req):
    # MarketPriceCollection-v1: what the ISK market lists per group (dustMarketClient._LoadRoughBestPrices).
    return collection([{"type": type_link(req, item), "price": price}
                       for item, price in items_in_group(req, content.isk_market())])


@route("GET", r"^/market/(\d+)/orders/sell/$")
def market_sell_orders(req):
    # MarketOrderCollection-v1 for ?type=: one endless order at the listed price (GetPriceByTypeID, buy orders).
    type_id = id_from_href(req["query"].get("type"))
    price = content.isk_market().get(type_id)
    if not price:
        return collection([])
    station_id, station_name = MARKET_STATION
    return collection([{
        "type": type_link(req, content.catalog().items[type_id]), "price": price, "volume": 1000000, "buy": False,
        "location": {"id": station_id, "href": f"{req['base']}/stations/{station_id}/", "name": station_name},
        "range": "station", "duration": 365,
    }])


def aur_offer(req, item, price):
    # VgsOffer as read by dust/crestdata/vgsData2.py; one product with quantity 1 makes it a plain offer.
    return {"id": item["id"], "href": f"{req['base']}/offers/{item['id']}/", "name": item["name"],
            "description": item["description"] or "", "imageUrl": "", "price": price,
            "basePrice": item["baseAurPrice"] or price, "endDate": None, "tags": [],
            "products": [{"id": item["id"], "href": f"{req['base']}/products/{item['id']}/", "typeId": item["id"],
                          "groupId": item["categoryID"], "quantity": 1}]}


@route("GET", r"^/stores/2/offers/$")
def aur_store_offers(req):
    cat = content.catalog()
    return collection([aur_offer(req, cat.items[type_id], price)
                       for type_id, price in sorted(content.aur_store().items())], currentPage=1)


@route("GET", r"^/dust/storefront/(\d+)/$")
def storefront(req):
    # Storefront-v2, the market's start page; without an own layout CCP's offline one.
    return content.load("storefront")["layout"] or offline_result(req["path"])


@route("GET", r"^/dust/asset/loyaltyStores/$")
def loyalty_stores(req):
    # DustLoyaltyStoreCollection-v1 (loyaltyStoreClient._LoadStores); the balance is the corporation's LP.
    stores = content.load("loyalty")["stores"]
    cat = content.catalog()
    items = []
    for corp, group_id in content.LOYALTY_STORES.items():
        # CCP's offline data answers every corporation id with the same NPC corporation; the market group
        # of each store carries the faction's name.
        corporation = {"id": corp, "name": cat.groups[group_id]["name"], "href": f"{req['base']}/corporations/{corp}/"}
        href = f"{req['base']}/dust/asset/loyaltyStores/{corp}/"
        items.append({"href": href, "id": corp, "corporation": corporation,
                      "balance": (stores.get(str(corp)) or {}).get("balance", 0), "offers": {"href": f"{href}offers/"}})
    return collection(items)


@route("GET", r"^/dust/asset/loyaltyStores/(\d+)/offers/$")
def loyalty_store_offers(req):
    corp = int(re.match(r"^/dust/asset/loyaltyStores/(\d+)/offers/$", req["path"]).group(1))
    cat = content.catalog()
    href = f"{req['base']}/dust/asset/loyaltyStores/{corp}/offers/"
    return collection([{"href": f"{href}{type_id}/", "type": type_link(req, cat.items[type_id]),
                        "lpCost": lp, "iskCost": isk, "quantity": 1}
                       for type_id, lp, isk in content.loyalty_offers().get(corp, []) if type_id in cat.items])


def isk_account(req, owner_id, key, wallet):
    # ISK of our own characters is per character (store.py); CCP's offline characters share wallet.json.
    char = own_character(req, owner_id, private=True)
    href = f"{req['base']}/accounts/{owner_id}/{key}/"
    return {"href": href, "id": key, "balance": char["isk"] if char else wallet["isk"],
            "transactions": f"{href}transactions/"}


@route("GET", r"^/accounts/(\d+)/$")
def account(req):
    account_id = int(re.match(r"^/accounts/(\d+)/$", req["path"]).group(1))
    wallet = content.load("wallet")
    currency = VGS_ACCOUNTS.get(account_id)
    if currency:
        # VgsAccount-v1 (aurumClient via vgsData2.GetAccount); CCP's offline routes answer it with the ISK collection.
        if currency == "AUR":
            balance = wallet["aur"]
        else:
            balance = sum(lp.get("balance", 0) for lp in content.load("loyalty")["stores"].values())
        return {"id": account_id, "currency": currency, "balance": balance, "freeBalance": balance, "totalSpent": 0,
                "href": f"{req['base']}{req['path']}", "transactions": {"href": f"{req['base']}{req['path']}transactions/"}}
    # A character's accounts (myCharactersClient._GetAccountIfNeeded), the wallet first.
    return collection([isk_account(req, account_id, ISK_ACCOUNT_KEY, wallet)])


@route("GET", r"^/accounts/(\d+)/(\d+)/$")
def character_account(req):
    owner_id, key = map(int, re.match(r"^/accounts/(\d+)/(\d+)/$", req["path"]).groups())
    return isk_account(req, owner_id, key, content.load("wallet"))


# --- Experiment 1: a fake battle (docs/battle_feasibility.md) -------------------------------------
# The battle finder lists it, joining (battleClient3.JoinBattle) posts a member, and we answer like
# CCP's backend would: OnBattleMemberJoined, then OnBattleMemberConnect with a server address, which
# the client turns into "CleanLoad <address>:<port>?credential=..." (dustClient/dustUnreal).

FAKE_BATTLE_CONFIG = Path(__file__).resolve().parent / "fake_battle.json"
HOME_LOCATION = {  # Ana in Domain, where CCP's offline character lives (see /locations/60006418/)
    "region": (10000043, "Domain"),
    "constellation": (20000517, "Constellation 20000517"),
    "system": (30003552, "Ana"),
}


def fake_battle_config():
    config = json.loads(FAKE_BATTLE_CONFIG.read_text(encoding="utf-8")) if FAKE_BATTLE_CONFIG.exists() else {}
    return config if config.get("enabled") else None


def corporation_link(req, corp_id):
    try:
        name = offline_result(f"/corporations/{corp_id}/").get("name")
    except Exception:
        name = None
    return {"id": corp_id, "name": name or f"Corporation {corp_id}", "href": f"{req['base']}/corporations/{corp_id}/"}


def fake_battle(req, config):
    """Battle-v1 as read by uiSvcBattle (_FormatTheatreBattles, _GetNavigationNodes) and dustClient."""
    battle_href = f"{req['base']}/battles/{config['battle_id']}/"
    links = {key: {"id": id_, "name": name, "href": f"{req['base']}/{key}s/{id_}/"}
             for key, (id_, name) in HOME_LOCATION.items()}
    links["system"]["href"] = f"{req['base']}/solarsystems/{HOME_LOCATION['system'][0]}/"
    links["system"]["security"] = 0.5  # battleFinder2.SetJoiningState shows it on the join screen
    return {
        "id": config["battle_id"], "href": battle_href, "name": config["name"],
        "status": 3,  # uiSvcBattle.JoinBattle ignores battles below 3
        "teamSelect": False,
        "startDate": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        # dustClient.GetBattleModeID (a CATMA DustGameType); overviewPanel shows the name on the deploy map.
        "mode": {"id": config["mode_id"], "name": config.get("mode_name", "Ambush")},
        # battleFinder2.RedrawPlanetThreaded looks the planet up by href (map search, empty here)
        "planet": {"id": config["planet_id"], "name": "Ana", "href": f"{req['base']}/planets/{config['planet_id']}/"},
        **links,
        "attacker": corporation_link(req, config["attacker_corp_id"]),
        "defender": corporation_link(req, config["defender_corp_id"]),
        "members": {"href": f"{battle_href}members/"},
        "serverRegion": "local",
        "maxPlayers": 32, "totalPlayers": 1,
    }


@route("GET", r"^/battles/theatres/$")
def battle_theatres(req):
    config = fake_battle_config()
    if not config:
        return offline_result(req["path"])
    # No "queue" key: uiSvcBattle.OnSelect then joins a listed battle instead of a matchmaking queue.
    return {"items": [{"key": "public", "name": config.get("theatre_name", "Lokale Gefechte"),
                       "description": config.get("theatre_description", "Testgefecht des lokalen Servers"),
                       "icon": {"href": f"{req['base']}/images/theatres/public.png"},
                       "regions": [{"id": "local"}]}]}


@route("GET", r"^/battles/$")
def battles(req):
    config = fake_battle_config()
    if not config:
        return offline_result(req["path"])
    return {"items": [fake_battle(req, config)]}


@route("GET", r"^/battles/(\d+)/$")
def battle(req):
    config = fake_battle_config()
    if not config or id_from_href(req["path"]) != config["battle_id"]:
        return RawResponse(b'{"message": "unknown battle"}', "application/json", status=404)
    return fake_battle(req, config)


@route("GET", r"^/battles/(\d+)/members/$")
def battle_members(req):
    return {"items": [], "totalCount": 0, "pageCount": 1}


@route("POST", r"^/battles/(\d+)/members/$")
def join_battle(req):
    # BattleMemberCreate-v1: {"character": {"href"}, "team"?, "region"?}; answer is a BattleMember-v1.
    config = fake_battle_config()
    battle_id = int(re.match(r"^/battles/(\d+)/members/$", req["path"]).group(1))
    if not config or battle_id != config["battle_id"]:
        return RawResponse(b'{"message": "unknown battle"}', "application/json", status=404)
    character_href = ((req["body"] or {}).get("character") or {}).get("href", "")
    character_id = id_from_href(character_href)
    team = (req["body"] or {}).get("team") or config["team"]
    battle_href = f"{req['base']}/battles/{battle_id}/"
    member = {
        "href": f"{battle_href}members/{character_id}/",
        "character": {"id": character_id, "href": character_href},
        "battle": {"id": battle_id, "href": battle_href},
        "team": team,
    }
    credential = uuid.uuid4().hex[:24]  # battleServer._MemberJoinedBattle uses 24 hex chars
    listen_member = None
    if config["variant"] == "listen":
        # A client hosts the map (?listen?battleID=...); it picks this member up from /dev/battle/members/
        # and registers the credential with its battle server; only then is the client told to connect.
        team = config.get("listen_team", team)
        if team == "auto":
            # Alternate, starting with the defenders (the host is on the attackers). Rejoins count as new
            # members, so this only roughly balances the teams.
            with LISTEN_LOCK:
                team = ("defender", "attacker")[len(LISTEN_MEMBERS) % 2]
        member["team"] = team
        listen_member = register_listen_member(req, config, team)
        credential = listen_member["credential"]
    target = config[{"localmap": "target_localmap", "listen": "target_listen"}.get(config["variant"], "target_probe")]
    connect = {**member, "credential": credential, "server": {"address": target["address"], "port": target["port"]}}
    # The client reads contentType's last dotted part minus "-v1" as the notification name
    # (characterConnectionClient._NotificationCallback) and passes "body" to battleClient3.
    owner = f"/characters/{character_id}/notifications/"
    joined = {"contentType": "application/vnd.ccp.eve.OnBattleMemberJoined-v1", "body": member}
    # Only to the joining client: the host has the same character, and a host that gets the connect
    # joins its own battle as a client, leaves the listen map and drops every player.
    peer = client_key(req)
    threading.Timer(config["joined_delay_seconds"], HUB.send, args=(owner, joined, peer)).start()
    connect_data = {"contentType": "application/vnd.ccp.eve.OnBattleMemberConnect-v1", "body": connect}
    if listen_member:
        with LISTEN_LOCK:
            PENDING_CONNECTS[credential] = (owner, connect_data, peer)
    else:
        threading.Timer(config["connect_delay_seconds"], HUB.send, args=(owner, connect_data, peer)).start()
    return member


LISTEN_MEMBERS = []  # players registered with the listen-server host, one entry per join
PENDING_CONNECTS = {}  # credential -> (notification owner, OnBattleMemberConnect, peer) until the host has it
LISTEN_LOCK = threading.Lock()
LISTEN_CONNECT_DELAY = 2.0  # the host registers right after its poll returns


OFFLINE_CHARACTERS_END = 2100001611 + 100      # userBattle.STARTING_OFFLINE_CHARID + NUM_OFFLINE_PLAYERS


def register_listen_member(req, config, team):
    # Every player needs its own battle character ID and URI: DustTeamGame.Login (credential branch,
    # ?battleID=) takes them from the host's battleServer, whose cache is keyed by URI. All local players
    # share CCP's offline characters, so neither the CREST character nor the user tells them apart.
    # The host itself uses first_member_id - 1. Only CCP's offline characters 2100001611 to 2100001710 get an
    # inventory, skills and a fitting (userBattle.OfflineConnect, NUM_OFFLINE_PLAYERS = 100); for a later ID the
    # host's fitting check fails (inventory None) and the pawn spawns without a weapon. So the IDs wrap around.
    with LISTEN_LOCK:
        first = config.get("first_member_id", 2100001612)
        character_id = first + len(LISTEN_MEMBERS) % (OFFLINE_CHARACTERS_END - first)
        member = {
            "credential": uuid.uuid4().hex[:24],
            "characterID": character_id,
            "characterURI": f"{req['base']}/battlecharacters/{character_id}/",
            "name": f"Mercenary {len(LISTEN_MEMBERS) + 2}",
            "team": {"attacker": 0, "defender": 1}[team],
        }
        LISTEN_MEMBERS.append(member)
        return member


# Addresses the listen-server host polls from. Every client with our COMMON.SDAT patch polls the dev
# endpoints, so without this a player's client would get the host's commands and start its own
# listen-server match (that the backend knows nothing about, so it cannot be left either). The host runs
# on the server itself (127.0.0.1 in the Docker container); players come from outside or through the
# Docker gateway.
HOST_PEERS = {p.strip() for p in os.environ.get("DUST_HOST_PEERS", "127.0.0.1,::1,::ffff:127.0.0.1").split(",") if p.strip()}


# Extra RPCS3 instances on the host's own machine (multiplayer and scaling tests) also come from 127.0.0.1, so
# each gets its own port: 8081 for client 2, 8082 for client 3, ... (dev commands from dev_commands_8081.json).
TEST_CLIENT_PORTS = range(8081, 8090)


def test_client(req):
    port = req["base"].rsplit(":", 1)[-1]
    return port.isdigit() and int(port) in TEST_CLIENT_PORTS


def client_key(req):
    # Address plus the server address the client talks to: test clients on this machine share 127.0.0.1.
    return req.get("peer"), req["base"]


def from_host(req):
    return (req.get("peer") is None or req["peer"] in HOST_PEERS) and not test_client(req)


@route("GET", r"^/dev/battle/members/$")
def listen_battle_members(req):
    # Polled by the listen-server host (client_patch/dustdevhook.py), which registers new credentials.
    # The host's Python does not run while it loads a map, so a poll also means the map is up: send the
    # joining clients their OnBattleMemberConnect now (a client connecting mid-load crashes the host).
    if not from_host(req):
        return {"items": []}
    server_status.host_members_polled()
    with LISTEN_LOCK:
        for member in LISTEN_MEMBERS:
            pending = PENDING_CONNECTS.pop(member["credential"], None)
            if pending:
                threading.Timer(LISTEN_CONNECT_DELAY, HUB.send, args=pending).start()
        return {"items": list(LISTEN_MEMBERS)}


@route("POST", r"^/dev/battle/fake_member/$")
def fake_battle_member(req):
    # For tools/fake_client.py: registers a member with the listen-server host like a real join does, without a
    # game client. The host picks it up with its next /dev/battle/members/ poll.
    config = fake_battle_config()
    if not config or config["variant"] != "listen":
        return RawResponse(b'{"message": "no listen battle"}', "application/json", status=404)
    team = (req["body"] or {}).get("team") or config.get("listen_team", config["team"])
    if team == "auto":
        with LISTEN_LOCK:
            team = ("defender", "attacker")[len(LISTEN_MEMBERS) % 2]
    return {**register_listen_member(req, config, team), "server": config["target_listen"]}


@route("GET", r"^/dev/host/heartbeat/$")
def host_heartbeat(req):
    # For the Docker watchdog (docker/host/watchdog.py): seconds since the host's game last polled us.
    # RPCS3 can keep running after the game's Python died (e.g. when this server was restarted).
    polls = [t for t in (server_status.HOST["last_poll"], server_status.HOST["last_members_poll"]) if t]
    return {"age": round(time.time() - max(polls), 1) if polls else None}


@route("DELETE", r"^/battles/(\d+)/members/(\d+)/$")
def leave_battle(req):
    # BattleMemberDelete-v1 (battleClient3.LeaveBattle); the client drops the membership itself.
    return {}


DEV_COMMANDS_DIR = Path(__file__).resolve().parent


@route("GET", r"^/dev/commands/$")
def dev_commands(req):
    # Polled by client_patch/dustdevhook.py; the client runs the commands once per new revision.
    # Test clients on this machine talk to ports 8081+ (TEST_CLIENT_PORTS) and get dev_commands_8081.json.
    second_client = test_client(req)
    if not second_client and not from_host(req):
        return {"revision": 0, "commands": []}  # a player's client, not the host (see HOST_PEERS)
    path = DEV_COMMANDS_DIR / ("dev_commands_8081.json" if second_client else "dev_commands.json")
    if not path.exists():
        return {"revision": 0, "commands": []}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not second_client:
        start = next((c["arg"] for c in data.get("commands", [])
                      if c.get("action") == "ue3" and str(c.get("arg", "")).startswith("Start ")), None)
        server_status.host_polled(data.get("revision"), start)
    return data


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
    def handle(self, method, target, headers, body, base, peer=None):
        """Return (status, content_type, payload bytes, source, extra headers) for one request."""
        url = urllib.parse.urlsplit(target)
        path = url.path
        req = {
            "method": method, "path": path, "query": dict(urllib.parse.parse_qsl(url.query)),
            "headers": headers, "body": parse_body(headers, body), "base": base, "peer": peer,
        }
        try:
            result, source = self.dispatch(req)
        except Unauthorized:
            return 401, "application/json; charset=utf-8", b'{"message": "unknown token"}', "unauthorized", {}
        except CharacterMissing as e:
            return (404, "application/json; charset=utf-8", b'{"message": "unknown character"}',
                    f"missing:character:{e.args[0]}", {})

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

    def dispatch(self, req):
        """(result, source): our handler, else CCP's offline handler (source None if there is neither)."""
        for m, regex, func in _routes:
            if m == req["method"] and regex.match(req["path"]):
                result = func(req)
                if result is not OFFLINE:
                    return result, f"own:{func.__name__}"
                break
        char = own_character_in_path(req)
        if char:
            # Stage 1b: CCP's handlers answer every character ID with their offline character's data, so ask for
            # that one and swap the IDs (mail, chat, quests, fittings, skills, inventory, corporation member ...).
            path = re.sub(rf"\b{char['id']}\b", str(OFFLINE_CHARACTER_ID), req["path"])
            found, result = offline_bridge.dispatch(req["method"], path, parameters=req["query"], resource=req["body"])
            if found and not isinstance(result, Exception):
                result = rebind(result, char["user_id"], char["id"])
            return result, ("ccp_offline:rebind" if found else None)
        found, result = offline_bridge.dispatch(req["method"], req["path"], parameters=req["query"],
                                                resource=req["body"])
        return result, ("ccp_offline" if found else None)
