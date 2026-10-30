"""NP tickets (format 2.1) as the client sends them in the OAuth login (psn_ticket, crest/authentication.py).

Layout: 4 bytes version (21 01 00 00), 4 bytes size, then sections and items, each as 2 bytes type, 2 bytes length
and the data (big endian). The body section (0x3000) holds the items in a fixed order: serial, issuer ID, issued
date, expiry date, user ID, online ID (32 bytes, zero padded), region, domain, service ID, status, ... The footer
section (0x3002) holds the signer ("RPCN") and the signature.

The signature is not checked: the local RPCN server signs with its own key (open question in
docs/character_server_plan.md). Anyone who can reach this server can therefore claim any online ID.
"""

import base64
import struct

BODY_SECTION = 0x3000
ONLINE_ID, USER_ID, SERVICE_ID = 5, 4, 8  # item positions in the body section


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


def parse(ticket):
    """{online_id, user_id, service_id} from a ticket (bytes or base64 text)."""
    data = base64.b64decode(ticket) if isinstance(ticket, str) else bytes(ticket)
    if len(data) < 8 or data[0] != 0x21:
        raise TicketError("not an NP ticket of format 2.x")
    end = min(len(data), 8 + struct.unpack_from(">I", data, 4)[0])
    for kind, section in _items(data, 8, end):
        if kind != BODY_SECTION:
            continue
        items = [value for _, value in _items(section, 0, len(section))]
        if len(items) <= SERVICE_ID:
            raise TicketError("body section too short")
        online_id = items[ONLINE_ID].split(b"\0", 1)[0].decode("ascii", "replace")
        if not online_id:
            raise TicketError("empty online ID")
        return {"online_id": online_id,
                "user_id": int.from_bytes(items[USER_ID], "big"),
                "service_id": items[SERVICE_ID].split(b"\0", 1)[0].decode("ascii", "replace")}
    raise TicketError("no body section")


def build(online_id, user_id=1, service_id="UP5018-NPUB30643_00"):
    """A ticket with the same layout as RPCN's (zero signature), for tests."""
    def item(kind, value):
        return struct.pack(">HH", kind, len(value)) + value
    body = b"".join([
        item(8, b"\0" * 20), item(1, b"\0" * 4), item(7, b"\0" * 8), item(7, b"\0" * 8),
        item(2, user_id.to_bytes(8, "big")), item(4, online_id.encode().ljust(32, b"\0")),
        item(8, b"br\0\0"), item(4, b"un\0\0"), item(8, service_id.encode().ljust(24, b"\0")),
        item(1, b"\0" * 4), item(0, b""), item(0, b""),
    ])
    footer = item(8, b"RPCN") + item(8, b"\0" * 62)
    sections = item(BODY_SECTION, body) + item(0x3002, footer)
    return b"\x21\x01\0\0" + struct.pack(">I", len(sections)) + sections
