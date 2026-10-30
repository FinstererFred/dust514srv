"""Character creation and deletion rules (docs/character_server_plan.md, stage 3). No HTTP and no SQL here.

Facts from the 03.19 client (dust/ui/characterCreation2.py, dust/userClient.py, dust/character.py):
- POST <user>/mercenaries/ MercenaryItemCreate-v2 {name, gender, bloodline: href}. The name is "<given> <family>";
  the client sends no race, specialty or portrait, so all of them follow from the bloodline.
- A 403 with {"title", "message"} becomes a popup and sends the player back to the name page
  (dust.popups.HttpForbiddenErrorConfig); a 200 returns to the character selection.
- POST <mercenary self> {prepareDelete: true|false} starts or cancels the countdown; the list shows
  deletePrepareDate (UTC, '%Y-%m-%dT%H:%M:%S') and offers "delete" once that time has passed; DELETE <self> deletes.
"""

import datetime
import re

MAX_CHARACTERS = 3  # characterCreation2._MAX_CHARACTERS: three slots in the selection
NAME_MIN, NAME_MAX = 3, 37  # EVE's character name limits
NAME_CHARS = re.compile(r"^[A-Za-z0-9' -]+$")  # dust.character.GetNameInvalidCharacters (non-Chinese region)

# dustConst race and bloodline IDs. Only bloodlines the client has icons for (characterIcons.bloodlineImage);
# Ni-Kunni (6) and Jin-Mei (12) have none and are left out.
CALDARI, MINMATAR, AMARR, GALLENTE = 1, 2, 4, 8
BLOODLINES = {  # id: (name, race, short description)
    1: ("Deteis", CALDARI, "Caldari bloodline."),
    2: ("Civire", CALDARI, "Caldari bloodline."),
    11: ("Achura", CALDARI, "Caldari bloodline."),
    3: ("Sebiestor", MINMATAR, "Minmatar bloodline."),
    4: ("Brutor", MINMATAR, "Minmatar bloodline."),
    14: ("Vherokior", MINMATAR, "Minmatar bloodline."),
    5: ("Amarr", AMARR, "Amarr bloodline."),
    13: ("Khanid", AMARR, "Amarr bloodline."),
    7: ("Gallente", GALLENTE, "Gallente bloodline."),
    8: ("Intaki", GALLENTE, "Gallente bloodline."),
}
RACE_NAMES = {CALDARI: "Caldari", MINMATAR: "Minmatar", AMARR: "Amarr", GALLENTE: "Gallente"}
PORTRAIT_BY_RACE = {CALDARI: 0, GALLENTE: 1, AMARR: 2, MINMATAR: 3}  # characterCreation2.GetPortraitIDByRace
# The starting NPC corporations, 12 per race, in the order of CATMA's starting_corporations_global (356418,
# amarrCorporations.0-11 ...); names from EVE's public ESI (POST /universe/names/), the client only knows three.
STARTING_CORPORATIONS = {
    AMARR: [(1000205, "Amarr Templars"), (1000226, "Ametat Security"), (1000207, "Bragian Order"),
            (1000227, "Company of Marcher Lords"), (1000223, "Fraternity of St. Venefice"),
            (1000231, "Holdfast Syndicate"), (1000229, "Kameira Lodge"), (1000225, "Paladin Survey Force"),
            (1000230, "Red and Silver Hand"), (1000206, "Royal Uhlans"), (1000224, "Shining Flame"),
            (1000228, "Tal-Romon Legion")],
    CALDARI: [(1000237, "Commando Perkone"), (1000233, "Expert Intervention"), (1000240, "Ikomari-Onu Enforcement"),
              (1000239, "Intara Direct Action"), (1000238, "Isuuaya Tactical"), (1000232, "Kinsho Swords"),
              (1000235, "Kirkinen Risk Control"), (1000234, "Onikanabo Brigade"), (1000213, "Osmon Surveillance"),
              (1000214, "Seituoda Taskforce Command"), (1000236, "Storm Wind Strikeforce"),
              (1000208, "Zumari Force Projection")],
    GALLENTE: [(1000215, "Algintal Core"), (1000247, "Chatelain Rapid Response"), (1000250, "Condotta Rouvenor"),
               (1000216, "Crux Special Tasks Group"), (1000248, "Edimmu Warfighters"),
               (1000249, "Kang Lo Directorate"), (1000244, "Mannar Focused Warfare"), (1000243, "Namtar Elite"),
               (1000222, "Ostrakon Agency"), (1000245, "Resheph Interstellar Strategy"),
               (1000246, "Sinq Laison Gendarmes"), (1000217, "Villore Sec Ops")],
    MINMATAR: [(1000251, "Brutor Vanguard"), (1000218, "Circle of Huskarl"), (1000255, "Eyniletti Rangers"),
               (1000257, "Forty-Nine Fedayeen"), (1000253, "Krullefor Organization"),
               (1000259, "Krusual Covert Operators"), (1000254, "Mikramurka Shock Troop"),
               (1000220, "Sanmatar Kelkoons"), (1000256, "Sebiestor Field Sappers"),
               (1000258, "Seykal Expeditionary Group"), (1000219, "Tronhadar Free Guard"),
               (1000252, "Vherokior Combat Logistics")],
}
NPC_CORPORATION_NAMES = {cid: name for corps in STARTING_CORPORATIONS.values() for cid, name in corps}
# The corporation a new character joins: those of CCP's offline characters 1-3 (offlineResourceUserCharacter),
# for Minmatar (no offline character) the first of its list. How CCP's backend picked one is not known.
NPC_CORPORATIONS = {AMARR: 1000205, CALDARI: 1000214, GALLENTE: 1000216, MINMATAR: 1000251}

# Problems with a new character: (title, message) as the client's popup shows them.
NAME_INVALID = ("Invalid name", "Names may only contain letters, digits, spaces, apostrophes and hyphens.")
NAME_LENGTH = ("Invalid name", f"Names must be {NAME_MIN} to {NAME_MAX} characters long.")
NAME_TAKEN = ("Name taken", "Another mercenary already has this name.")
UNKNOWN_BLOODLINE = ("Character creation failed", "Unknown bloodline.")
NO_FREE_SLOT = ("Character creation failed", f"An account can have at most {MAX_CHARACTERS} mercenaries.")
DELETE_NOT_READY = ("Deletion not possible", "The mercenary is not ready for deletion yet.")


def clean_name(name):
    """The name as stored: surrounding and doubled spaces removed (the client sends "<given> <family>")."""
    return " ".join(str(name or "").split())


def check_new(name, bloodline_id, existing, name_taken):
    """None if a character `name` (already cleaned) of `bloodline_id` may be created, else a problem from above.

    `existing` is the number of the account's characters (also those waiting for deletion), `name_taken` a function.
    """
    if existing >= MAX_CHARACTERS:
        return NO_FREE_SLOT
    if bloodline_id not in BLOODLINES:
        return UNKNOWN_BLOODLINE
    if not NAME_MIN <= len(name) <= NAME_MAX:
        return NAME_LENGTH
    if not NAME_CHARS.match(name):
        return NAME_INVALID
    if name_taken(name):
        return NAME_TAKEN
    return None


def race_of(bloodline_id):
    return BLOODLINES[bloodline_id][1]


def delete_prepare_date(delete_ready_at):
    """deletePrepareDate for the mercenary list: when the delete becomes possible, or None."""
    if delete_ready_at is None:
        return None
    return datetime.datetime.fromtimestamp(delete_ready_at, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def may_delete(delete_ready_at, now):
    return delete_ready_at is not None and delete_ready_at <= now
