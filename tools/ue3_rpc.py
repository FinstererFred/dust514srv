"""Encodes and decodes UE3 RPC bunches on the DustPlayerController channel (fake client groundwork).

Replication indices come from the cooked script packages (research/tools_local/netfields.py, declaration order;
DustPlayerController has 212 net fields). An RPC bunch is SerializeInt(index, 212) followed by the parameters in
declaration order: bools as one bit, every other parameter as a "sent" bit (0 = zero value, omitted) plus its value.
Values: int/float as 4 bytes big-endian (PS3 memory order), byte as 8 bits, vector compressed like
FVector::SerializeCompressed, string as int32 length (with terminator) plus bytes.

    python tools/ue3_rpc.py        decodes the ServerMove bunches of dust_server/logs/replay_spawn_move.jsonl
"""
import re
import struct

from ue3_packets import BitReader

MAX_INDEX = 212
INDEX = {"ServerMove": 54, "ServerUpdatePing": 62, "ServerAcknowledgePossession": 42, "AskForPawn": 40,
         "ServerUpdateLevelVisibility": 91, "ServerBeginSpawnProcess": 174, "ServerRefreshCachedViewportInfo": 191,
         "InvokeSvcMethodOnBattleServer": 197, "ServerSetLeftTriggerHeld": 125, "ServerOnStreamingFinished": 173,
         # client functions (host -> client)
         "GivePawn": 41, "ClientPreRestartPlayer": 183, "VeryShortClientAdjustPosition": 56,
         "ClientUpdateLevelStreamingStatus": 90, "ClientStartCheckStreaming": 172, "ClientSetTimeLeftBeforeRespawn": 177,
         "InvokeSvcMethodOnClient": 196}
# DustControllerSharedComponent (own actor channel, archetype DustGame.Default__DustControllerSharedComponent): 38 net
# fields; ServerSelectDefaultSpawnPoint has no parameters. Without it mCurrentSpawnPoint stays None and the host's
# CheckSpawnPointIsValid cancels the spawn (ClientNotifySpawnPointCancelled).
SHARED_COMPONENT_MAX_INDEX = 38
SHARED_COMPONENT_INDEX = {"ServerSelectDefaultSpawnPoint": 26, "ServerSetCurrentSpawnPoint": 27}
# Server RPCs on other actor channels: archetype -> (net field count, {function: (index, parameter types)}).
# A recorded client equipped its rifle after GivePawn with ServerSetCurrentWeapon(<weapon channel>) on the inventory
# manager and ServerSetCurrentFireMode(0) on the weapon; firing is stock UE3 Weapon.ServerStartFire/ServerStopFire
# (CCP added TimeStamp), not seen in a recording yet.
ACTOR_RPCS = {
    "DustGame.Default__DustControllerSharedComponent": (38, {"ServerSelectDefaultSpawnPoint": (26, [])}),
    "DustGame.Default__DustPawnInventoryManager": (27, {"ServerSetCurrentWeapon": (23, ["object"])}),
    "DustGame.Default__DustHandheldWeapon": (54, {"ServerStartFire": (26, ["byte", "float"]),
                                                  "ServerStopFire": (27, ["byte"]),
                                                  "ServerSetCurrentFireMode": (52, ["int"])}),
}
# Parameter types in declaration order. "object" is an actor reference; on the wire a big-endian int32 that matched the
# actor's channel index (GivePawn/ServerAcknowledgePossession, 2026-10-30), echoed back unchanged.
SCHEMA = {"ServerMove": ["float", "vector", "vector", "byte", "byte", "int"], "ServerUpdatePing": ["int"],
          "ServerAcknowledgePossession": ["object"], "AskForPawn": [], "ServerBeginSpawnProcess": [], "ServerOnStreamingFinished": [],
          "InvokeSvcMethodOnBattleServer": ["str", "str", "str"], "ServerUpdateLevelVisibility": ["name", "bool"]}
# Names and object paths go through a per-direction cache: the first use writes the full form (cache id from 0x401 up,
# int32 length, text with terminator, int32 FName number), later uses only the negated cache id (no number).


class Reader(BitReader):
    """BitReader over a bunch payload of a known bit length (no terminator bit)."""
    def __init__(self, data, nbits):
        self.data, self.pos, self.end = data, 0, nbits

    def byte(self):
        return sum(self.bit() << i for i in range(8))

    def raw(self, n):
        return bytes(self.byte() for _ in range(n))

    def float_(self):
        return struct.unpack(">f", self.raw(4))[0]

    def int_(self):
        return struct.unpack(">i", self.raw(4))[0]

    def vector(self):
        bits = self.serialize_int(20)
        bias, maximum = 1 << (bits + 1), 1 << (bits + 2)
        return tuple(self.serialize_int(maximum) - bias for _ in range(3))


class Writer:
    def __init__(self):
        self.bits = []

    def bit(self, v):
        self.bits.append(1 if v else 0)

    def serialize_int(self, value, maximum):
        new, mask = 0, 1
        while new + mask < maximum and mask:
            if value & mask:
                self.bit(1)
                new += mask
            else:
                self.bit(0)
            mask <<= 1

    def byte(self, v):
        for i in range(8):
            self.bit((v >> i) & 1)

    def raw(self, data):
        for b in data:
            self.byte(b)

    def float_(self, v):
        self.raw(struct.pack(">f", v))

    def int_(self, v):
        self.raw(struct.pack(">i", v))

    def vector(self, v):
        x, y, z = (int(round(c)) for c in v)
        ceil_log2 = (max(abs(x), abs(y), abs(z))).bit_length()     # appCeilLogTwo(1 + max)
        bits = max(1, min(20, ceil_log2)) - 1
        self.serialize_int(bits, 20)
        bias, maximum = 1 << (bits + 1), 1 << (bits + 2)
        for c in (x, y, z):
            self.serialize_int(c + bias, maximum)

    def str_(self, s):
        raw = s.encode("latin1") + b"\0"
        self.raw(struct.pack(">i", len(raw)) + raw)

    def name(self, value):
        """value: (cache id, text, number), always written in full form."""
        cache_id, text, number = value
        self.int_(cache_id)
        self.str_(text)
        self.int_(number)

    def rpc(self, name, *values):
        """Appends one PlayerController RPC; several RPCs can share a bunch."""
        return self.call(INDEX[name], MAX_INDEX, SCHEMA[name], values)

    def actor_rpc(self, archetype, name, *values):
        """Appends one RPC of another actor (ACTOR_RPCS)."""
        maximum, functions = ACTOR_RPCS[archetype]
        index, schema = functions[name]
        return self.call(index, maximum, schema, values)

    def call(self, index, maximum, schema, values):
        self.serialize_int(index, maximum)
        for kind, value in zip(schema, values):
            if kind == "bool":
                self.bit(value)
                continue
            zero = value in (None, 0, 0.0, "", (0, 0, 0))
            self.bit(not zero)
            if zero:
                continue
            {"float": self.float_, "int": self.int_, "byte": self.byte, "vector": self.vector, "str": self.str_,
             "object": self.int_, "name": self.name}[kind](value)
        return self

    def payload(self):
        out = bytearray((len(self.bits) + 7) // 8)
        for i, b in enumerate(self.bits):
            out[i >> 3] |= b << (i & 7)
        return bytes(out), len(self.bits)


def decode_server_move(data, nbits):
    r = Reader(data, nbits)
    index = r.serialize_int(MAX_INDEX)
    out = {"index": index}
    out["TimeStamp"] = r.float_() if r.bit() else 0.0
    out["InAccel"] = r.vector() if r.bit() else (0, 0, 0)
    out["ClientLoc"] = r.vector() if r.bit() else (0, 0, 0)
    out["MoveFlags"] = r.byte() if r.bit() else 0
    out["ClientRoll"] = r.byte() if r.bit() else 0
    out["View"] = r.int_() if r.bit() else 0
    out["left_bits"] = r.end - r.pos
    return out


def encode_server_move(timestamp, accel, loc, move_flags=0, roll=0, view=0):
    return Writer().rpc("ServerMove", timestamp, accel, loc, move_flags, roll, view).payload()


FULL_NAME = re.compile(rb"\x00\x00[\x04-\x0f][\x00-\xff]\x00\x00\x00([\x02-\x7f])([A-Za-z0-9_+.]{1,126})\x00")


def full_names(data):
    """Names written in full form anywhere in a bunch payload, found at every bit alignment, as (bit offset of the
    cache id, cache id, text, number, bit offset after the number)."""
    value, out = int.from_bytes(data, "little"), []
    for shift in range(8):
        d = (value >> shift).to_bytes(len(data), "little")
        for m in FULL_NAME.finditer(d):
            if m.group(1)[0] == len(m.group(2)) + 1 and m.end() + 4 <= len(d):
                out.append((m.start() * 8 + shift, int.from_bytes(d[m.start():m.start() + 4], "big"),
                            m.group(2).decode("latin1"), int.from_bytes(d[m.end():m.end() + 4], "big"),
                            (m.end() + 4) * 8 + shift))
    return sorted(out)


def int_at(data, bit):
    """Big-endian int32 at an arbitrary bit offset of a payload (None past the end)."""
    if bit + 32 > len(data) * 8:
        return None
    raw = ((int.from_bytes(data, "little") >> bit) & 0xffffffff).to_bytes(4, "little")
    return struct.unpack(">i", raw)[0]


def first_rpc(data, nbits):
    """Index of the first field in a host -> client bunch on the PlayerController channel, plus the reader."""
    r = Reader(data, nbits)
    return r.serialize_int(MAX_INDEX), r


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fake_client import load_replay
    items = load_replay(str(Path(__file__).resolve().parent.parent / "dust_server/logs/replay_spawn_move.jsonl"), {1})
    shown = 0
    for t, ch, rel, data, nbits in items:
        if data[:1] == b"\x36" and not rel and (shown < 6 or 36 < t < 38) and shown < 14:
            print("%7.2f %s" % (t, decode_server_move(data, nbits)))
            shown += 1
