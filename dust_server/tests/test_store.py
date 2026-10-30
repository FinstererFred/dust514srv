"""Tests for store.py and np_ticket.py without a running game: python -m unittest discover dust_server/tests"""

import base64
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import np_ticket
import store

SPECIALTY = {"id": 353915, "race": 4, "startingSkillPoints": 500000, "skillPointsPerDay": 24000, "startingISK": 25000,
             "startingSkills": [{"skillTypeID": 353352, "skillLevel": 1}, {"skillTypeID": 364519, "skillLevel": 2}]}
DAY = 86400


class TicketTest(unittest.TestCase):
    def test_round_trip(self):
        ticket = base64.b64encode(np_ticket.build("DustTester2", 42)).decode()
        self.assertEqual(np_ticket.parse(ticket),
                         {"online_id": "DustTester2", "user_id": 42, "service_id": "UP5018-NPUB30643_00"})

    def test_same_size_as_rpcn(self):
        self.assertEqual(len(np_ticket.build("FinstererFred")), 254)

    def test_garbage(self):
        for data in (b"", b"\x00" * 16, np_ticket.build("x")[:40]):
            with self.assertRaises(np_ticket.TicketError):
                np_ticket.parse(data)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "dust.sqlite"
        self.store = store.Store(self.path)

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def char(self, user_id, name="Merc", now=1000.0):
        return self.store.create_character(user_id, name, 1, 5, 4, SPECIALTY, 2, 1000205, npe_state=1, now=now)

    def test_users_and_ids(self):
        a = self.store.user_for_online_id("FinstererFred")
        b = self.store.user_for_online_id("DustTester2")
        self.assertEqual((a["id"], b["id"]), (store.FIRST_USER_ID, store.FIRST_USER_ID + 1))
        self.assertEqual(self.store.user_for_online_id("FinstererFred")["id"], a["id"])

    def test_tokens(self):
        user = self.store.user_for_online_id("DustTester2")
        token, refresh = self.store.issue_token(user["id"], now=0)
        self.assertEqual(self.store.user_for_token(token, now=10)["id"], user["id"])
        self.assertEqual(self.store.user_for_refresh_token(refresh, now=4000)["id"], user["id"])
        self.assertIsNotNone(self.store.user_for_token(token, now=store.TOKEN_LIFETIME + 100))  # grace
        self.assertIsNone(self.store.user_for_token(token, now=store.TOKEN_LIFETIME + store.TOKEN_GRACE + 1))
        self.assertIsNone(self.store.user_for_token("unknown"))

    def test_character_start_values(self):
        user = self.store.user_for_online_id("DustTester2")
        char = self.char(user["id"])
        self.assertEqual(char["id"], store.FIRST_CHARACTER_ID)
        self.assertEqual((char["sp_base"], char["sp_per_day"], char["isk"], char["passive_sp"]), (500000, 24000, 25000, 0))
        self.assertEqual(self.store.skills_of(char["id"]), {353352: 1, 364519: 2})
        self.assertEqual([c["id"] for c in self.store.characters_of(user["id"])], [char["id"]])
        self.assertTrue(self.store.name_taken("MERC"))

    def test_passive_sp(self):
        user = self.store.user_for_online_id("DustTester2")
        a, b = self.char(user["id"], "A"), self.char(user["id"], "B")
        self.assertEqual(store.total_sp(a, now=1000 + DAY), 500000)  # off by default
        self.store.set_passive(a["id"], 1, now=1000)
        a = self.store.character(a["id"])
        self.assertEqual(store.total_sp(a, now=1000 + DAY / 2), 512000)
        # switching B on books A's SP and switches A off
        self.store.set_passive(b["id"], 1, now=1000 + DAY / 2)
        a, b = self.store.character(a["id"]), self.store.character(b["id"])
        self.assertEqual((a["passive_sp"], b["passive_sp"]), (0, 1))
        self.assertEqual(store.total_sp(a, now=1000 + 2 * DAY), 512000)
        self.assertEqual(store.total_sp(b, now=1000 + DAY), 512000)
        self.store.add_sp(b["id"], 100, now=1000 + DAY)
        self.assertEqual(store.total_sp(self.store.character(b["id"]), now=1000 + DAY), 512100)

    def test_update_whitelist(self):
        char = self.char(self.store.user_for_online_id("x")["id"])
        self.assertEqual(self.store.update_character(char["id"], portrait_id=3, npe_state=2)["portrait_id"], 3)
        with self.assertRaises(ValueError):
            self.store.update_character(char["id"], sp_base=1)

    def test_reopen_keeps_data_and_backs_up_on_migration(self):
        self.char(self.store.user_for_online_id("x")["id"])
        self.store.close()
        self.store = store.Store(self.path)
        self.assertEqual(len(self.store.users()), 1)
        self.store.close()
        # a new schema version: the next open migrates and keeps a copy of version 1
        migrations = list(store.MIGRATIONS)
        store.MIGRATIONS.append("CREATE TABLE extra (x INTEGER)")
        try:
            self.store = store.Store(self.path)
        finally:
            store.MIGRATIONS[:] = migrations
        self.assertEqual(len(self.store.users()), 1)
        self.assertTrue(self.path.with_name("dust.sqlite.bak-1").exists())

if __name__ == "__main__":
    unittest.main()
