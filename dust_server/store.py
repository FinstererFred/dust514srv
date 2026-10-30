"""Accounts, tokens, characters and skills in SQLite (docs/character_server_plan.md, stage 1a).

One connection and one lock for the whole server; crest_app.py and admin.py only call the functions here and know
no SQL. The file is dust_server/state/dust.sqlite, or DUST_STATE_DIR/dust.sqlite. Migrations run at open; before
one runs on an existing file, a copy dust.sqlite.bak-<old version> is kept.

Total SP of a character = sp_base + passive_sp * sp_per_day * (now - sp_since) / 86400, rounded down. Every change
of passive_sp or sp_per_day first books the SP earned so far into sp_base (sp_since = now).
"""

import os
import secrets
import shutil
import sqlite3
import threading
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("DUST_STATE_DIR") or Path(__file__).resolve().parent / "state")
FIRST_USER_ID = 1000001000  # CCP's offline data uses 1000000720
FIRST_CHARACTER_ID = 2100100000  # outside CCP's offline characters (2100001611-2100001710)
TOKEN_LIFETIME = 3600  # seconds, as told to the client (expires_in)
TOKEN_GRACE = 86400  # an expired token is still accepted this long: requests in flight while the client refreshes

MIGRATIONS = [
    # version 1
    """
    CREATE TABLE users (id INTEGER PRIMARY KEY, online_id TEXT NOT NULL UNIQUE, created_at REAL NOT NULL);
    CREATE TABLE tokens (token TEXT PRIMARY KEY, refresh_token TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL,
                         expires_at REAL NOT NULL);
    CREATE TABLE characters (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL,
                             gender INTEGER NOT NULL, bloodline_id INTEGER NOT NULL, race_id INTEGER NOT NULL,
                             specialty_id INTEGER NOT NULL, portrait_id INTEGER NOT NULL,
                             corporation_id INTEGER NOT NULL, sp_base INTEGER NOT NULL, sp_per_day INTEGER NOT NULL,
                             sp_since REAL NOT NULL, passive_sp INTEGER NOT NULL DEFAULT 0, isk INTEGER NOT NULL,
                             npe_state INTEGER NOT NULL DEFAULT 0, aur_spent INTEGER NOT NULL DEFAULT 0,
                             delete_ready_at REAL, deleted INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
    CREATE INDEX characters_user ON characters (user_id);
    CREATE TABLE skills (character_id INTEGER NOT NULL, type_id INTEGER NOT NULL, level INTEGER NOT NULL,
                         PRIMARY KEY (character_id, type_id));
    """,
]

# Fields a caller may change with update_character (the SP fields go through set_passive/add_sp).
UPDATABLE = {"name", "portrait_id", "npe_state", "aur_spent", "isk", "corporation_id", "delete_ready_at", "deleted"}


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self):
        with self.lock:
            self.db.execute("CREATE TABLE IF NOT EXISTS meta (schema_version INTEGER NOT NULL)")
            row = self.db.execute("SELECT schema_version FROM meta").fetchone()
            version = row[0] if row else 0
            if version >= len(MIGRATIONS):
                return
            if version:
                self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                shutil.copy2(self.path, self.path.with_name(f"{self.path.name}.bak-{version}"))
            with self.transaction():
                for script in MIGRATIONS[version:]:
                    for statement in filter(str.strip, script.split(";")):
                        self.db.execute(statement)
                self.db.execute("DELETE FROM meta")
                self.db.execute("INSERT INTO meta VALUES (?)", (len(MIGRATIONS),))

    def transaction(self):
        return _Transaction(self)

    def close(self):
        self.db.close()

    # --- users and tokens ---------------------------------------------------------------------------------

    def user_for_online_id(self, online_id):
        """The user of an RPCN account, created on first login."""
        with self.transaction():
            user = self._one("SELECT * FROM users WHERE online_id = ?", (online_id,))
            if not user:
                user_id = max(FIRST_USER_ID - 1, self._max_id("users")) + 1
                self.db.execute("INSERT INTO users VALUES (?, ?, ?)", (user_id, online_id, time.time()))
                user = self.user(user_id)
            return user

    def user(self, user_id):
        return self._one("SELECT * FROM users WHERE id = ?", (user_id,))

    def users(self):
        return self._all("SELECT * FROM users ORDER BY id")

    def issue_token(self, user_id, now=None):
        """A new (access token, refresh token) pair; old pairs stay valid until they run out."""
        now = time.time() if now is None else now
        token, refresh = secrets.token_hex(16), secrets.token_hex(16)
        with self.transaction():
            self.db.execute("DELETE FROM tokens WHERE expires_at < ?", (now - TOKEN_GRACE,))
            self.db.execute("INSERT INTO tokens VALUES (?, ?, ?, ?)", (token, refresh, user_id, now + TOKEN_LIFETIME))
        return token, refresh

    def user_for_token(self, token, now=None):
        now = time.time() if now is None else now
        return self._one("SELECT u.* FROM tokens t JOIN users u ON u.id = t.user_id "
                         "WHERE t.token = ? AND t.expires_at >= ?", (token, now - TOKEN_GRACE))

    def user_for_refresh_token(self, refresh_token, now=None):
        now = time.time() if now is None else now
        return self._one("SELECT u.* FROM tokens t JOIN users u ON u.id = t.user_id "
                         "WHERE t.refresh_token = ? AND t.expires_at >= ?", (refresh_token, now - TOKEN_GRACE))

    # --- characters -----------------------------------------------------------------------------------------

    def create_character(self, user_id, name, gender, bloodline_id, race_id, specialty, portrait_id, corporation_id,
                         npe_state=0, now=None):
        """A new character with the specialty's starting SP, ISK and skills (specialty as from GET /specialties)."""
        now = time.time() if now is None else now
        with self.transaction():
            char_id = max(FIRST_CHARACTER_ID - 1, self._max_id("characters")) + 1
            self.db.execute(
                "INSERT INTO characters (id, user_id, name, gender, bloodline_id, race_id, specialty_id, portrait_id,"
                " corporation_id, sp_base, sp_per_day, sp_since, passive_sp, isk, npe_state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                (char_id, user_id, name, int(bool(gender)), bloodline_id, race_id, specialty["id"], portrait_id,
                 corporation_id, specialty["startingSkillPoints"], specialty["skillPointsPerDay"], now,
                 specialty["startingISK"], npe_state, now))
            self.db.executemany("INSERT INTO skills VALUES (?, ?, ?)",
                                [(char_id, s["skillTypeID"], s["skillLevel"]) for s in specialty["startingSkills"]])
        return self.character(char_id)

    def character(self, char_id):
        return self._one("SELECT * FROM characters WHERE id = ? AND deleted = 0", (char_id,))

    def characters_of(self, user_id):
        return self._all("SELECT * FROM characters WHERE user_id = ? AND deleted = 0 ORDER BY id", (user_id,))

    def name_taken(self, name):
        return self._one("SELECT 1 AS taken FROM characters WHERE name = ? COLLATE NOCASE AND deleted = 0",
                         (name,)) is not None

    def update_character(self, char_id, **fields):
        unknown = set(fields) - UPDATABLE
        if unknown:
            raise ValueError(f"not updatable: {sorted(unknown)}")
        if fields:
            with self.transaction():
                self.db.execute(f"UPDATE characters SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                                (*fields.values(), char_id))
        return self.character(char_id)

    def set_passive(self, char_id, status, now=None):
        """Switch passive SP gain; switching one character on switches the account's other characters off."""
        now = time.time() if now is None else now
        with self.transaction():
            char = self.character(char_id)
            if not char:
                return None
            others = [c for c in self.characters_of(char["user_id"]) if c["id"] != char_id and c["passive_sp"]]
            for c in ([char] if bool(status) != bool(char["passive_sp"]) else []) + (others if status else []):
                self._book_sp(c, now)
                self.db.execute("UPDATE characters SET passive_sp = ? WHERE id = ?",
                                (int(bool(status)) if c["id"] == char_id else 0, c["id"]))
        return self.character(char_id)

    def add_sp(self, char_id, amount, now=None):
        now = time.time() if now is None else now
        with self.transaction():
            char = self.character(char_id)
            self._book_sp(char, now)
            self.db.execute("UPDATE characters SET sp_base = sp_base + ? WHERE id = ?", (amount, char_id))
        return self.character(char_id)

    def _book_sp(self, char, now):
        self.db.execute("UPDATE characters SET sp_base = ?, sp_since = ? WHERE id = ?",
                        (total_sp(char, now), now, char["id"]))

    def set_total_sp(self, char_id, total, now=None):
        """Set the total SP as of now (web admin); passive gain continues from there."""
        now = time.time() if now is None else now
        with self.transaction():
            self.db.execute("UPDATE characters SET sp_base = ?, sp_since = ? WHERE id = ?", (total, now, char_id))
        return self.character(char_id)

    def skills_of(self, char_id):
        return {r["type_id"]: r["level"] for r in self._all(
            "SELECT type_id, level FROM skills WHERE character_id = ? ORDER BY type_id", (char_id,))}

    def set_skill(self, char_id, type_id, level):
        with self.transaction():
            self.db.execute("INSERT OR REPLACE INTO skills VALUES (?, ?, ?)", (char_id, type_id, level))

    def replace_skills(self, char_id, skills):
        """Replace all skills of a character with {typeID: level} (web admin: back to the starting skills)."""
        with self.transaction():
            self.db.execute("DELETE FROM skills WHERE character_id = ?", (char_id,))
            self.db.executemany("INSERT INTO skills VALUES (?, ?, ?)",
                                [(char_id, t, level) for t, level in skills.items()])

    def _max_id(self, table):
        return self._one(f"SELECT COALESCE(MAX(id), 0) AS id FROM {table}")["id"]

    def _one(self, sql, args=()):
        with self.lock:
            row = self.db.execute(sql, args).fetchone()
        return dict(row) if row else None

    def _all(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]


class _Transaction:
    """BEGIN IMMEDIATE ... COMMIT under the store's lock; nested use joins the outer transaction."""

    def __init__(self, store):
        self.store, self.outer = store, False

    def __enter__(self):
        self.store.lock.acquire()
        self.outer = not self.store.db.in_transaction
        if self.outer:
            self.store.db.execute("BEGIN IMMEDIATE")
        return self.store.db

    def __exit__(self, kind, value, tb):
        try:
            if self.outer:
                self.store.db.execute("COMMIT" if kind is None else "ROLLBACK")
        finally:
            self.store.lock.release()


def total_sp(char, now=None):
    now = time.time() if now is None else now
    gained = char["passive_sp"] * char["sp_per_day"] * max(0.0, now - char["sp_since"]) / 86400
    return char["sp_base"] + int(gained)


_store = None
_store_lock = threading.Lock()


def get():
    """The server's store, opened on first use."""
    global _store
    with _store_lock:
        if _store is None:
            _store = Store(STATE_DIR / "dust.sqlite")
        return _store
