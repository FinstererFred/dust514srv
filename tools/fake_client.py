"""Lightweight fake battle client for load tests: joins a listen host over the UE3 net protocol without RPCS3.

    python tools/fake_client.py --bind 127.0.0.20 --seconds 60

Steps: registers a member with the CREST server (POST /dev/battle/fake_member/, the host picks the credential up with
its next members poll), then Hello -> Challenge -> Login (challenge response "0") -> Welcome -> Join on the control
channel, then acks every packet the host sends and keeps the connection alive.

With --play it also spawns and walks (tools/ue3_rpc.py encodes the RPCs): reports the visible streaming levels (class
Levels), then InvokeSvcMethodOnBattleServer("battleServer", "SpawnCharacterWithFitting", <pickled fitting>),
ServerSelectDefaultSpawnPoint on its DustControllerSharedComponent and ServerBeginSpawnProcess; on
ClientStartCheckStreaming it moves to the given location, reports the levels there and sends ServerOnStreamingFinished;
on ClientPreRestartPlayer
it answers ServerAcknowledgePossession(None) + AskForPawn, on GivePawn(p) ServerAcknowledgePossession(p); then
ServerMove at --move-rate with an acceleration that turns every few seconds. ClientLoc follows the host's
VeryShortClientAdjustPosition. Message bytes were copied from a recorded real client (tools/udp_proxy.py,
tools/ue3_packets.py); integers inside messages are big-endian.
"""
import math
import random
import argparse
import json
import re
import socket
import struct
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ue3_packets import MAX_CHANNELS, MAX_CHSEQUENCE, CHTYPE_MAX, MAX_PACKET, MAX_PACKETID, parse  # noqa: E402
from ue3_rpc import ACTOR_RPCS, INDEX, MAX_INDEX, Writer, first_rpc, full_names, int_at  # noqa: E402

CHTYPE_CONTROL, CHTYPE_ACTOR = 1, 2
MSG_HELLO, MSG_CHALLENGE, MSG_LOGIN, MSG_FAILURE, MSG_JOIN, MSG_WELCOME = 0, 3, 4, 6, 9, 11
MSG_NETOBJ = 20                                     # probably CCP's NetObjConfirm: client-side net objects, negative IDs
HELLO = bytes.fromhex("00080000199100001a2b0000000000000000000000000000000000000000")
JOIN = bytes([MSG_JOIN]) + bytes(8)
LOGIN_HEAD = bytes.fromhex("0400004e2005")       # message type, then fields copied verbatim (NetSpeed 20000 among them)
URL = ("{port}/LoginScene?credential={credential}?Team={team}?LightingMode=MOOD_DAY?DefaultArmor=352592"
       "?Name={name}?SeekFreeLoading=1?Version=2.13.0.249")
MAX_ACKS_PER_PACKET = 32
RECV_SLICE = 0.01


class BitWriter:
    def __init__(self):
        self.bits = []

    def bit(self, v):
        self.bits.append(1 if v else 0)

    def serialize_int(self, value, maximum):
        written, mask = 0, 1
        while written + mask < maximum and mask:   # like FBitWriter::SerializeInt: bound by the bits written so far
            if value & mask:
                self.bit(1)
                written += mask
            else:
                self.bit(0)
            mask <<= 1

    def data(self, payload, nbits):
        for i in range(nbits):
            self.bit((payload[i >> 3] >> (i & 7)) & 1)

    def finish(self):
        bits = self.bits + [1]                      # terminator
        out = bytearray((len(bits) + 7) // 8)
        for i, b in enumerate(bits):
            out[i >> 3] |= b << (i & 7)
        return bytes(out)


def ue3_string(text):
    raw = text.encode("ascii") + b"\0"
    return struct.pack(">i", len(raw)) + raw


class Connection:
    def __init__(self, bind, server):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind, 0))
        self.sock.settimeout(0.005)
        self.server = server
        self.verbose = False
        self.controller_bunches = []                # host -> client bunches on the PlayerController channel
        self.opened_bunches = []                    # (channel, data) of the first bunch of every other actor channel
        self.closed_channels = []                   # actor channels the host closed (our pawn's one when we died)
        self.packet_id = 0
        self.sequence = {}                          # channel -> last reliable sequence we sent
        self.pending_acks = []
        self.last_send = 0.0
        self.stats = {"recv": 0, "sent": 0, "bytes_in": 0, "opened": 0, "closed": 0, "bunches": 0, "errors": 0,
                      "replayed": 0}

    def send(self, control=(), actor=()):
        """control: payloads for the control channel (reliable); actor: (channel, reliable, data, bits) bunches on
        channels the host opened (the PlayerController is channel 1)."""
        w = BitWriter()
        w.serialize_int(self.packet_id % MAX_PACKETID, MAX_PACKETID)
        acks, self.pending_acks = self.pending_acks[:MAX_ACKS_PER_PACKET], self.pending_acks[MAX_ACKS_PER_PACKET:]
        for ack in acks:
            w.bit(1)
            w.serialize_int(ack, MAX_PACKETID)
        bunches = [(0, True, payload, len(payload) * 8) for payload in control] + list(actor)
        for channel, reliable, data, nbits in bunches:
            w.bit(0)
            if reliable:
                self.sequence[channel] = self.sequence.get(channel, 0) + 1
            opening = channel == 0 and self.sequence[0] == 1    # our first bunch opens the control channel
            w.bit(opening)                          # bControl: open/close flags follow
            if opening:
                w.bit(1)                            # bOpen
                w.bit(0)                            # bClose
            w.bit(reliable)
            w.serialize_int(channel, MAX_CHANNELS)
            if reliable:
                w.serialize_int(self.sequence[channel] % MAX_CHSEQUENCE, MAX_CHSEQUENCE)
                w.serialize_int(CHTYPE_CONTROL if channel == 0 else CHTYPE_ACTOR, CHTYPE_MAX)
            w.serialize_int(nbits, MAX_PACKET * 8)
            w.data(data, nbits)
        self.sock.sendto(w.finish(), self.server)
        self.packet_id += 1
        self.stats["sent"] += 1
        self.last_send = time.time()

    def receive(self):
        """Returns control messages (bytes) received; acks every packet. Drains at most RECV_SLICE seconds so that a busy
        host cannot starve our own sends (the socket timeout alone only ends the loop after a quiet gap)."""
        messages, until = [], time.time() + RECV_SLICE
        while time.time() < until:
            try:
                data, _ = self.sock.recvfrom(65535)
            except (socket.timeout, ConnectionResetError):
                return messages
            self.stats["recv"] += 1
            self.stats["bytes_in"] += len(data)
            try:
                packet_id, _, bunches = parse(data)
            except ValueError:
                self.stats["errors"] += 1
                continue
            self.pending_acks.append(packet_id)
            for b in bunches:
                self.stats["bunches"] += 1
                self.stats["opened"] += b["open"]
                if b["open"] and self.verbose:
                    print("  opened channel %d type %s: %s" % (b["channel"], b["type"], b["data"][:12].hex()), flush=True)
                self.stats["closed"] += b["close"] and b["channel"] != 0
                if b["close"] and b["channel"] != 0:
                    self.closed_channels.append(b["channel"])
                if b["close"] and self.verbose:
                    print("  closed channel %d" % b["channel"], flush=True)
                if b["channel"] == 0:
                    if b["data"]:
                        messages.append(b["data"])
                    if b["close"]:                  # the host closes the connection (often an empty bunch)
                        messages.append(b"closed")
                elif b["channel"] == 1 and b["bits"]:
                    self.controller_bunches.append((b["data"], b["bits"]))
                if b["open"] and b["channel"] != 1:
                    self.opened_bunches.append((b["channel"], b["data"]))
        return messages


# Fittings "<suit type>:<module>+-1,..." per slot in suit order (offline fittings in the client's offlineResourceFittings):
FITTINGS = {"heavy": "352592:369179+-1,-1+-1,368557+-1,-1+-1,-1+-1,-1+-1",    # recorded default: Amarr Heavy Frame, a
                                                                               # weapon that charges while held
            "assault": "354941:368949+-1,-1+-1,-1+-1,-1+-1,-1+-1,353120+-1,-1+-1,-1+-1"}  # Assault Dropsuit + rifle
ACCEL = 25000.0                                     # |InAccel| of a recorded walking client
QUIET = {21, 22, 56, 57, 59, 60, 61}                # PRI/Pawn properties and move corrections, not printed
ADJUST_WITH_STATE = {57, 60, 61}                    # Short-, -, LongClientAdjustPosition
SHARED_COMPONENT = "DustGame.Default__DustControllerSharedComponent"
INVENTORY = "DustGame.Default__DustPawnInventoryManager"
WEAPON = "DustGame.Default__DustHandheldWeapon"
# ServerRefreshCachedViewportInfo(DustViewportInfo) as a recorded client sent it ~1 s after GivePawn, copied verbatim
# (struct layout not decoded yet). Test: without it the host charges the weapon but no shot follows.
VIEWPORT_INFO = (bytes.fromhex("bf852c010088400100886800006c0629d3ebfbb39af119f2ea26380000c028"), 246)
SOCKET_NAME = re.compile(r"^(small|medium|large|op|backdrop)\d+$", re.I)
STRUCTURE_NAME = re.compile(r"^[A-Z]{2}_GA_\w+$")
NAMES_PER_BUNCH = 8                                 # about 230 bits per name: stays well under MaxPacket


class Levels:
    """Streaming levels the client reports with ServerUpdateLevelVisibility. A level name the host does not know gets
    the client dropped, so they are derived from this connection's traffic as a real client does it:
    - map levels: ClientUpdateLevelStreamingStatus with bNewShouldBeVisible, plus the map's _MT and _VI levels, which a
      recorded client reported without such a call;
    - the MOOD_ lighting actor's level: its name, FName number = its actor channel;
    - every district structure: the open bunch of its socket actor names the socket (Small38, OP03, BackDrop01, ...)
      and then the structure (CS_GA_PowCore01S ...), in full or as a cache reference. Reported as <structure>_LOD0
      (backdrops without _LOD0) with FName number = the socket's actor channel; once the host asks the client to
      stream around the spawn point (ClientStartCheckStreaming), also <structure> and <structure>+AU."""
    def __init__(self):
        self.cache = {}                             # host's name cache: id -> text
        self.map_levels = []
        self.structures = {}                        # socket channel -> structure name (or MOOD_ level)
        self.near_spawn = False
        self.reported = set()
        self.next_id = 0x401                        # our own name cache
        self.channels = {}                          # archetype -> our latest actor channel of it (ACTOR_RPCS)

    def scan_controller(self, data):
        value = int.from_bytes(data, "little")
        for _, cache_id, text, _, end in full_names(data):
            self.cache[cache_id] = text
            visible = (value >> (end + 1)) & 1      # after PackageName: bNewShouldBeLoaded, bNewShouldBeVisible
            if text.startswith("MN_") and (visible or text.endswith(("_MT", "_VI"))) and text not in self.map_levels:
                self.map_levels.append(text)

    def scan_open(self, channel, data):
        names = full_names(data)
        for _, cache_id, text, _, _ in names:
            self.cache[cache_id] = text
        ref = int_at(data, 0)                       # the open bunch starts with the archetype, full or as a reference
        archetype = names[0][2] if names and names[0][0] == 0 else self.cache.get(-ref if ref else 0)
        if archetype in ACTOR_RPCS and not (archetype == SHARED_COMPONENT and archetype in self.channels):
            self.channels[archetype] = channel      # ours comes first; inventory and weapons reach only their owner
        for _, _, text, _, end in names:
            if text.startswith("MOOD_"):
                self.structures[channel] = text
            elif SOCKET_NAME.match(text):
                follow = [n[2] for n in names if end <= n[0] <= end + 40]
                if follow and STRUCTURE_NAME.match(follow[0]):
                    self.structures[channel] = follow[0]
                else:
                    for k in range(41):
                        ref = int_at(data, end + k)
                        if ref is not None and ref < 0 and STRUCTURE_NAME.match(self.cache.get(-ref, "")):
                            self.structures[channel] = self.cache[-ref]
                            break
                return

    def wanted(self):
        out = [(text, 0) for text in self.map_levels]
        for channel, name in sorted(self.structures.items()):
            if name.startswith(("MOOD_", "CB_")):
                out.append((name, channel))
            else:
                out.append((name + "_LOD0", channel))
                if self.near_spawn:
                    out += [(name, channel), (name + "+AU", channel)]
        return out

    def take_unreported(self):
        """Up to NAMES_PER_BUNCH (cache id, text, number) names not reported yet."""
        out = []
        for level in self.wanted():
            if level not in self.reported and len(out) < NAMES_PER_BUNCH:
                self.reported.add(level)
                out.append((self.next_id,) + level)
                self.next_id += 1
        return out


class Player:
    """Spawns and walks over the PlayerController channel (1)."""
    def __init__(self, conn, joined, args):
        self.conn, self.joined, self.args = conn, joined, args
        self.pawn = None
        self.location = (0.0, 0.0, 1000.0)          # what a recorded client sent before spawning
        self.next_spawn = joined + args.spawn_delay
        self.begin_spawn = None
        self.next_move = joined
        self.heading = random.uniform(0, 2 * math.pi)
        self.next_turn = 0.0
        self.levels = Levels()
        self.streamed = False                       # ServerOnStreamingFinished sent for this spawn
        self.next_levels = joined + 1.0             # let the first channel opens arrive
        self.armed = False                          # weapon selected for the current pawn
        self.next_fire, self.stop_fire = None, None

    def send(self, *rpcs, reliable=True):
        w = Writer()
        for rpc in rpcs:
            w.rpc(*rpc)
        data, nbits = w.payload()
        self.conn.send(actor=[(1, reliable, data, nbits)])

    def send_actor(self, archetype, name, *values):
        """Reliable RPC on our channel of that actor; False while the host has not opened one."""
        channel = self.levels.channels.get(archetype)
        if channel is None:
            return False
        self.conn.send(actor=[(channel, True) + Writer().actor_rpc(archetype, name, *values).payload()])
        return True

    def handle(self, data, nbits):
        """One host bunch on the PlayerController channel; follows several RPCs while their parameters are known."""
        self.levels.scan_controller(data)
        index, r = first_rpc(data, nbits)
        while True:
            if self.conn.verbose and index not in QUIET:
                print("  %.2f host rpc %d (%d bits)" % (time.time() - self.joined, index, nbits), flush=True)
            if index == INDEX["ClientPreRestartPlayer"]:
                self.send(("ServerAcknowledgePossession", None), ("AskForPawn",))
            elif index == INDEX["GivePawn"]:
                if not r.bit():
                    break
                ref = struct.unpack(">i", r.raw(4))[0]
                self.send(("ServerAcknowledgePossession", ref))
                if self.pawn is None:
                    print("pawn %d after %.1f s" % (ref, time.time() - self.joined), flush=True)
                self.pawn = ref
                self.armed = False
            elif index == INDEX["VeryShortClientAdjustPosition"]:
                values = [r.float_() if r.bit() else 0.0 for _ in range(4)]   # TimeStamp, NewLocX, NewLocY, NewLocZ
                self.location = tuple(values[1:])
                self.conn.stats["adjusts"] = self.conn.stats.get("adjusts", 0) + 1
                if r.bit():                         # NewBase
                    r.int_()
            elif index in ADJUST_WITH_STATE:        # TimeStamp, NewState, newPhysics, NewLocX/Y/Z, ...
                if r.bit():
                    r.float_()
                if r.bit():
                    self.read_name(r)
                if r.bit():
                    r.byte()
                self.location = tuple(r.float_() if r.bit() else 0.0 for _ in range(3))
                self.conn.stats["adjusts"] = self.conn.stats.get("adjusts", 0) + 1
                break                               # velocity, base and floor not needed
            elif index == INDEX["ClientSetTimeLeftBeforeRespawn"]:
                if r.bit():
                    r.float_()
            elif index == INDEX["ClientStartCheckStreaming"]:
                if r.bit():
                    self.location = r.vector()      # a real client moves its camera there at once (ServerMove)
                self.levels.near_spawn, self.streamed = True, False
            else:
                break
            if r.end - r.pos < 8:
                break
            index = r.serialize_int(MAX_INDEX)

    def read_name(self, r):
        cache_id = r.int_()
        if cache_id < 0:
            return self.levels.cache.get(-cache_id)
        text = r.raw(r.int_())[:-1].decode("latin1")
        r.int_()                                    # FName number
        self.levels.cache[cache_id] = text
        return text

    def tick(self, now):
        while self.conn.controller_bunches:
            self.handle(*self.conn.controller_bunches.pop(0))
        while self.conn.opened_bunches:
            self.levels.scan_open(*self.conn.opened_bunches.pop(0))
        while self.conn.closed_channels:
            if self.conn.closed_channels.pop(0) == self.pawn:  # dead: the host drops the pawn, spawn again
                self.conn.stats["deaths"] = self.conn.stats.get("deaths", 0) + 1
                self.pawn, self.armed, self.streamed = None, False, False
                self.next_fire = self.stop_fire = None
                for archetype in (INVENTORY, WEAPON):          # the new pawn brings new ones
                    self.levels.channels.pop(archetype, None)
                self.next_spawn = now + 3.0
        if now >= self.next_levels:
            names = self.levels.take_unreported()
            if names:
                self.send(*[("ServerUpdateLevelVisibility", name, True) for name in names])
                self.conn.stats["levels"] = len(self.levels.reported)
            elif self.levels.near_spawn and not self.streamed:
                self.send(("ServerOnStreamingFinished",))   # a recorded client sent it behind a ServerMove
                self.streamed = True
            self.next_levels = now + 0.1
        if self.pawn is None and now >= self.next_spawn:
            pickled = "(lp1\n(S'%s'\np2\ntp3\na(dp4\na." % FITTINGS[self.args.fitting]
            self.send(("InvokeSvcMethodOnBattleServer", "battleServer", "SpawnCharacterWithFitting", pickled))
            self.begin_spawn = now + 0.5            # after the battle server confirmed the fitting (asynchronous)
            self.next_spawn = now + self.args.spawn_retry
        if self.begin_spawn and now >= self.begin_spawn:
            self.send_actor(SHARED_COMPONENT, "ServerSelectDefaultSpawnPoint")   # same tick in a recording
            self.send(("ServerBeginSpawnProcess",))
            self.begin_spawn = None
        if self.pawn is not None and not self.armed and WEAPON in self.levels.channels:
            weapon = self.levels.channels[WEAPON]
            self.conn.send(actor=[(1, True) + VIEWPORT_INFO])
            self.send_actor(INVENTORY, "ServerSetCurrentWeapon", weapon)
            self.send_actor(WEAPON, "ServerSetCurrentFireMode", 0)
            self.armed = True
            if self.args.fire_interval:
                self.next_fire = now + random.uniform(1.0, self.args.fire_interval)
        if self.next_fire and now >= self.next_fire:
            self.send(("ServerSetRightTriggerHeld", True))   # recorded together with ServerStartFire
            self.send_actor(WEAPON, "ServerStartFire", 0, now - self.joined + 1.0)
            self.conn.stats["bursts"] = self.conn.stats.get("bursts", 0) + 1
            self.stop_fire, self.next_fire = now + self.args.fire_burst, now + self.args.fire_interval
        if self.stop_fire and now >= self.stop_fire:
            self.send_actor(WEAPON, "ServerStopFire", 0)
            self.send(("ServerSetRightTriggerHeld", False))
            self.send(("ServerReloadWeapon", 0))    # after every burst, so the clip never runs dry
            self.stop_fire = None
        if now >= self.next_move:
            accel = (0, 0, 0)
            if self.pawn is not None:
                if now >= self.next_turn:
                    self.heading += random.uniform(-2.0, 2.0)
                    self.next_turn = now + random.uniform(1.5, 4.0)
                accel = (ACCEL * math.cos(self.heading), ACCEL * math.sin(self.heading), 0)
            yaw = int(self.heading / (2 * math.pi) * 65536) & 0xffff
            view = struct.unpack(">i", struct.pack(">I", yaw << 16))[0]       # (Yaw << 16) | Pitch, signed int
            self.send(("ServerMove", now - self.joined + 1.0, accel, self.location, 0, 0, view), reliable=False)
            self.conn.stats["moves"] = self.conn.stats.get("moves", 0) + 1
            self.next_move = now + 1.0 / self.args.move_rate


def register(crest, team):
    body = json.dumps({"team": team} if team else {}).encode()
    req = urllib.request.Request(crest + "/dev/battle/fake_member/", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crest", default="http://127.0.0.1:8080")
    ap.add_argument("--bind", default="127.0.0.20", help="local address; one per fake client keeps them apart")
    ap.add_argument("--server", help="host:port of the listen host (default: from the CREST answer)")
    ap.add_argument("--team", choices=["attacker", "defender"])
    ap.add_argument("--wait", type=float, default=8, help="seconds for the host to poll the new member")
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--retries", type=int, default=10, help="new handshakes while the host rejects the credential")
    ap.add_argument("--keepalive", type=float, default=0.05, help="max seconds between our packets")
    ap.add_argument("--replay", help="udp_proxy.py recording: replay its client's actor-channel bunches after Join")
    ap.add_argument("--replay-channels", default="0,1",
                    help="comma-separated channels to replay (0: msg 20 control messages, 1: PlayerController)")
    ap.add_argument("--replay-limit", type=int, help="replay only the first N bunches (bisecting)")
    ap.add_argument("--replay-skip", help="comma-separated hex prefixes of bunches not to replay, e.g. db,14")
    ap.add_argument("--replay-only", help="comma-separated hex prefixes: replay only these bunches, e.g. db")
    ap.add_argument("--verbose", action="store_true", help="print channels the host opens")
    ap.add_argument("--play", action="store_true", help="spawn and walk")
    ap.add_argument("--spawn-delay", type=float, default=5, help="seconds after Join before the first spawn request")
    ap.add_argument("--spawn-retry", type=float, default=15, help="seconds between spawn requests until a pawn")
    ap.add_argument("--move-rate", type=float, default=30, help="ServerMove calls per second")
    ap.add_argument("--fire-interval", type=float, default=0, help="seconds between bursts once armed (0: no firing)")
    ap.add_argument("--fire-burst", type=float, default=1.5, help="seconds the trigger stays down per burst")
    ap.add_argument("--fitting", choices=sorted(FITTINGS), default="heavy")
    args = ap.parse_args()

    replay = load_replay(args.replay, {int(c) for c in args.replay_channels.split(",")}) if args.replay else []
    if args.replay_skip:
        skip = tuple(bytes.fromhex(p) for p in args.replay_skip.split(","))
        replay = [item for item in replay if not item[3].startswith(skip)]
    if args.replay_only:
        only = tuple(bytes.fromhex(p) for p in args.replay_only.split(","))
        replay = [item for item in replay if item[3].startswith(only)]
    if args.replay_limit is not None:
        replay = replay[:args.replay_limit]
    if replay:
        print("replay: %d bunches over %.0f s" % (len(replay), replay[-1][0]), flush=True)
    member = register(args.crest, args.team)
    host, port = (args.server.rsplit(":", 1) if args.server
                  else (member["server"]["address"], member["server"]["port"]))
    print("member %s, character %s, team %s -> %s:%s" % (member["credential"], member["characterID"], member["team"],
                                                         host, port), flush=True)
    time.sleep(args.wait)
    for attempt in range(args.retries + 1):
        state = run(args, member, host, port, replay)
        if state != "invalid_credential":
            break
        print("host does not know the credential yet, retrying in 3 s", flush=True)
        time.sleep(3)


def load_replay(path, channels):
    """Client bunches on the given actor channels from a udp_proxy.py recording, as (seconds after the recorded
    client's Join, channel, reliable, data, bits). Takes the last client session in the file."""
    records = [json.loads(line) for line in open(path, encoding="utf-8")]
    client = records[-1]["client"]
    joined, items = None, []
    for rec in records:
        if rec["client"] != client or rec["dir"] != "c2s":
            continue
        for b in parse(bytes.fromhex(rec["hex"]))[2]:
            if b["channel"] == 0 and b["data"][:1] == bytes([MSG_JOIN]):
                joined = rec["t"]
            elif b["channel"] == 0 and b["data"][:1] != bytes([MSG_NETOBJ]):
                continue                            # of the control messages only msg 20 is replayed
            elif joined is not None and b["channel"] in channels:
                items.append((rec["t"] - joined, b["channel"], bool(b["reliable"]), b["data"], b["bits"]))
    return items


def run(args, member, host, port, replay):
    conn = Connection(args.bind, (host, int(port)))
    conn.verbose = args.verbose
    conn.send([HELLO])
    state, start, last_report = "hello", time.time(), time.time()
    next_item = 0
    while time.time() - start < args.seconds:
        for msg in conn.receive():
            kind = msg[0] if msg != b"closed" else None
            if kind == MSG_CHALLENGE and state == "hello":
                url = URL.format(port=":%s" % port, credential=member["credential"], team=member["team"],
                                 name="FakeClient")
                conn.send([LOGIN_HEAD + ue3_string("0") + ue3_string(url)])
                state = "login"
                print("challenge -> login", flush=True)
            elif kind == MSG_WELCOME and state == "login":
                conn.send([JOIN])
                state, joined = "joined", time.time()
                player = Player(conn, joined, args) if args.play else None
                print("welcome -> join", flush=True)
            elif kind == MSG_FAILURE or msg == b"closed":
                print("host closed or refused:", msg[:120], flush=True)
                state = "invalid_credential" if b"InvalidCredential" in msg else "failed"
            elif kind not in (20,):
                print("control message %s (%d bytes)" % (kind, len(msg)), flush=True)
        if state in ("failed", "invalid_credential"):
            break
        if state == "joined":
            while next_item < len(replay) and replay[next_item][0] <= time.time() - joined:
                if conn.pending_acks and replay[next_item][4] > 2048:
                    conn.send()                     # acks first: a big bunch plus acks would exceed MaxPacket
                conn.send(actor=[replay[next_item][1:]])     # one bunch per packet stays under MaxPacket
                conn.stats["replayed"] += 1
                next_item += 1
            if player:
                player.tick(time.time())
            else:
                conn.controller_bunches.clear()
        if conn.pending_acks or time.time() - conn.last_send > args.keepalive:
            conn.send()
        if time.time() - last_report > 5:
            print(time.strftime("%H:%M:%S"), state, conn.stats, flush=True)
            last_report = time.time()
    print("end", state, conn.stats, flush=True)
    conn.sock.close()
    return state


if __name__ == "__main__":
    main()
