"""NP tickets (format 2.1) as the client sends them in the OAuth login (psn_ticket, crest/authentication.py).

Layout: 4 bytes version (21 01 00 00), 4 bytes size, then sections and items, each as 2 bytes type, 2 bytes length
and the data (big endian). The body section (0x3000) holds the items in a fixed order: serial, issuer ID, issued
date, expiry date, user ID, online ID (32 bytes, zero padded), region, domain, service ID, status, ... The footer
section (0x3002) holds the signer ("RPCN") and the signature.

RPCN signs the whole body section (with its 4-byte header) with ECDSA on secp224k1 and SHA-224, DER encoded
(rpcn src/server/client/ticket.rs, SignTickets=true). verify() checks that signature against the official RPCN key
and the keys in DUST_TICKET_KEYS (PEM files, e.g. the stack's own RPCN), plus expiry and service ID. Pure Python, so
the server keeps running on the standard library alone.
"""

import base64
import hashlib
import os
import struct
import time

BODY_SECTION, FOOTER_SECTION = 0x3000, 0x3002
ONLINE_ID, USER_ID, SERVICE_ID = 5, 4, 8  # item positions in the body section
ISSUED, EXPIRES = 2, 3
SERVICE_PREFIX = "UP5018-NPUB30643"
EXPIRY_GRACE = 3600  # seconds a ticket is still accepted after its expiry date (RPCN: 15 minutes after issue)

# np.rpcs3.net, ticket_public.pem in the RPCN repository; checked against a ticket of the official server (2026-11-01)
OFFICIAL_RPCN_KEY = """-----BEGIN PUBLIC KEY-----
ME4wEAYHKoZIzj0CAQYFK4EEACADOgAEsHvA8K3bl2V+nziQOejSucl9wqMdMELn
0Eebk9gcQrCr32xCGRox4x+TNC+PAzvVKcLFf9taCn0=
-----END PUBLIC KEY-----"""

# secp224k1 (SEC 2): y^2 = x^3 + 5 over P, base point G of order N
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFE56D
N = 0x010000000000000000000000000001DCE8D2EC6184CAF0A971769FB1F7
G = (0xA1455B334DF099DF30FC28A169A467E9E47075A90F7E650EB6B7A45C,
     0x7E089FED7FBA344282CAFBD6F7E319F7C0B0BD59E2CA4BDB556D61A5)
CURVE_OID = bytes.fromhex("06052b81040020")  # 1.3.132.0.32


class TicketError(ValueError):
    pass


def _items(data, pos, end):
    while pos + 4 <= end:
        kind, length = struct.unpack_from(">HH", data, pos)
        pos += 4
        if pos + length > end:
            raise TicketError("item runs past its section")
        yield kind, data[pos:pos + length]
        pos += length


def _decode(ticket):
    data = base64.b64decode(ticket) if isinstance(ticket, str) else bytes(ticket)
    if len(data) < 8 or data[0] != 0x21:
        raise TicketError("not an NP ticket of format 2.x")
    return data


def _sections(data):
    """{section type: (raw section with header, its items)}"""
    end = min(len(data), 8 + struct.unpack_from(">I", data, 4)[0])
    sections, pos = {}, 8
    for kind, value in _items(data, 8, end):
        sections[kind] = (data[pos:pos + 4 + len(value)], [v for _, v in _items(value, 0, len(value))])
        pos += 4 + len(value)
    return sections


def parse(ticket):
    """{online_id, user_id, service_id} from a ticket (bytes or base64 text)."""
    sections = _sections(_decode(ticket))
    if BODY_SECTION not in sections:
        raise TicketError("no body section")
    items = sections[BODY_SECTION][1]
    if len(items) <= SERVICE_ID:
        raise TicketError("body section too short")
    online_id = items[ONLINE_ID].split(b"\0", 1)[0].decode("ascii", "replace")
    if not online_id:
        raise TicketError("empty online ID")
    return {"online_id": online_id,
            "user_id": int.from_bytes(items[USER_ID], "big"),
            "service_id": items[SERVICE_ID].split(b"\0", 1)[0].decode("ascii", "replace")}


def verify(ticket, keys=None, now=None):
    """parse(), but only for a ticket signed by one of `keys` (default trusted_keys()), not expired, for DUST 514."""
    data = _decode(ticket)
    info = parse(data)
    sections = _sections(data)
    body, items = sections[BODY_SECTION]
    footer = sections.get(FOOTER_SECTION, (b"", []))[1]
    if len(footer) < 2 or footer[0] != b"RPCN":
        raise TicketError("not signed by RPCN")
    if not any(_ecdsa_verify(key, hashlib.sha224(body).digest(), footer[1])
               for key in (trusted_keys() if keys is None else keys)):
        raise TicketError("bad signature")
    expires = int.from_bytes(items[EXPIRES], "big") / 1000
    if expires + EXPIRY_GRACE < (time.time() if now is None else now):
        raise TicketError("expired")
    if not info["service_id"].startswith(SERVICE_PREFIX):
        raise TicketError(f"ticket for another game ({info['service_id']})")
    return info


_key_cache = {}


def trusted_keys():
    """The official RPCN key and the keys in DUST_TICKET_KEYS (PEM files, separated by commas). A missing file is
    skipped: the stack's RPCN writes its key on its first start, possibly after this server started."""
    keys = [public_key(OFFICIAL_RPCN_KEY)]
    for path in filter(None, (p.strip() for p in os.environ.get("DUST_TICKET_KEYS", "").split(","))):
        try:
            mtime = os.path.getmtime(path)
            if _key_cache.get(path, (None,))[0] != mtime:
                with open(path) as f:
                    _key_cache[path] = (mtime, public_key(f.read()))
            keys.append(_key_cache[path][1])
        except (OSError, TicketError) as e:
            print(f"np_ticket: key {path} not usable ({e})", flush=True)
    return keys


def public_key(pem):
    """(x, y) of a secp224k1 public key in PEM (SubjectPublicKeyInfo, uncompressed point)."""
    der = base64.b64decode("".join(line for line in pem.strip().splitlines() if not line.startswith("-----")))
    if CURVE_OID not in der or len(der) < 57 or der[-57] != 4:
        raise TicketError("not an uncompressed secp224k1 public key")
    point = (int.from_bytes(der[-56:-28], "big"), int.from_bytes(der[-28:], "big"))
    if (point[1] ** 2 - point[0] ** 3 - 5) % P:
        raise TicketError("point is not on secp224k1")
    return point


def _add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0]:
        if (a[1] + b[1]) % P == 0:
            return None
        slope = 3 * a[0] * a[0] * pow(2 * a[1], -1, P)
    else:
        slope = (b[1] - a[1]) * pow(b[0] - a[0], -1, P)
    x = (slope * slope - a[0] - b[0]) % P
    return x, (slope * (a[0] - x) - a[1]) % P


def _mul(k, point):
    result = None
    while k:
        if k & 1:
            result = _add(result, point)
        point = _add(point, point)
        k >>= 1
    return result


def _der_ints(sig):
    """(r, s) from a DER ECDSA signature."""
    try:
        if sig[0] != 0x30 or sig[1] != len(sig) - 2:
            raise TicketError("bad signature encoding")
        values, pos = [], 2
        for _ in range(2):
            if sig[pos] != 0x02:
                raise TicketError("bad signature encoding")
            length = sig[pos + 1]
            values.append(int.from_bytes(sig[pos + 2:pos + 2 + length], "big"))
            pos += 2 + length
        return values
    except IndexError:
        raise TicketError("bad signature encoding") from None


def _ecdsa_verify(key, digest, sig):
    try:
        r, s = _der_ints(sig)
    except TicketError:
        return False
    if not (0 < r < N and 0 < s < N):
        return False
    w = pow(s, -1, N)
    point = _add(_mul(int.from_bytes(digest, "big") * w % N, G), _mul(r * w % N, key))
    return point is not None and point[0] % N == r


def _ecdsa_sign(secret, digest, nonce):
    """For tests only: DER signature with a caller-chosen nonce."""
    r = _mul(nonce, G)[0] % N
    s = pow(nonce, -1, N) * (int.from_bytes(digest, "big") + r * secret) % N

    def der_int(value):
        raw = value.to_bytes((value.bit_length() + 8) // 8, "big")
        return b"\x02" + bytes([len(raw)]) + raw
    body = der_int(r) + der_int(s)
    return b"\x30" + bytes([len(body)]) + body


def build(online_id, user_id=1, service_id="UP5018-NPUB30643_00", secret=None, issued=None):
    """A ticket with the same layout as RPCN's, for tests. Without `secret` the signature is zero (like an RPCN with
    SignTickets=false); with it the ticket is signed by that private key. `issued` in seconds, default now."""
    def item(kind, value):
        return struct.pack(">HH", kind, len(value)) + value
    issued_ms = int((time.time() if issued is None else issued) * 1000)
    body = b"".join([
        item(8, b"\0" * 20), item(1, b"\0\0\x01\0"),
        item(7, issued_ms.to_bytes(8, "big")), item(7, (issued_ms + 15 * 60 * 1000).to_bytes(8, "big")),
        item(2, user_id.to_bytes(8, "big")), item(4, online_id.encode().ljust(32, b"\0")),
        item(8, b"br\0\0"), item(4, b"un\0\0"), item(8, service_id.encode().ljust(24, b"\0")),
        item(1, b"\0" * 4), item(0, b""), item(0, b""),
    ])
    body = item(BODY_SECTION, body)
    if secret is None:
        footer = item(8, b"\0" * 4) + item(8, b"\0" * 56)
    else:
        digest = hashlib.sha224(body).digest()
        footer = item(8, b"RPCN") + item(8, _ecdsa_sign(secret, digest, int.from_bytes(digest, "big") % (N - 1) + 1))
    sections = body + item(FOOTER_SECTION, footer)
    return b"\x21\x01\0\0" + struct.pack(">I", len(sections)) + sections
