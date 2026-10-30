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

    def test_skills_and_sp(self):
        char = self.char(self.store.user_for_online_id("x")["id"])
        self.store.set_skill(char["id"], 353352, 3)
        self.store.set_skill(char["id"], 1, 0)
        self.assertEqual(self.store.skills_of(char["id"]), {1: 0, 353352: 3, 364519: 2})
        self.store.replace_skills(char["id"], {353352: 1})
        self.assertEqual(self.store.skills_of(char["id"]), {353352: 1})
        self.store.set_total_sp(char["id"], 777, now=5000)
        self.assertEqual(store.total_sp(self.store.character(char["id"]), now=6000), 777)

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
        # a new schema version: the next open migrates and keeps a copy of the current version
        migrations = list(store.MIGRATIONS)
        store.MIGRATIONS.append("CREATE TABLE extra (x INTEGER)")
        try:
            self.store = store.Store(self.path)
        finally:
            store.MIGRATIONS[:] = migrations
        self.assertEqual(len(self.store.users()), 1)
        self.assertTrue(self.path.with_name(f"dust.sqlite.bak-{len(migrations)}").exists())

    def test_inventory(self):
        char = self.char(self.store.user_for_online_id("x")["id"])
        first = self.store.add_items(char["id"], {353120: 50, 367499: 1})
        self.assertEqual([(r["type_id"], r["quantity"]) for r in first], [(353120, 50), (367499, 1)])
        self.assertEqual(first[0]["id"], store.FIRST_ITEM_ID)
        again = self.store.add_items(char["id"], {353120: 5})
        self.assertEqual((again[0]["id"], again[0]["quantity"]), (store.FIRST_ITEM_ID, 55))
        with self.assertRaises(store.NotEnough):
            self.store.add_items(char["id"], {353120: -1, 367499: -2})
        self.assertEqual(self.store.quantity(char["id"], 353120), 55)  # nothing taken
        gone = self.store.add_items(char["id"], {367499: -1})
        self.assertEqual(gone[0]["quantity"], 0)
        self.assertEqual([r["type_id"] for r in self.store.inventory_of(char["id"])], [353120])

    def test_starting_items_once(self):
        char = self.char(self.store.user_for_online_id("x")["id"])
        fittings = [(364740, "Frontline", True), (353486, "LAV", False)]
        self.assertTrue(self.store.give_starting_items(char["id"], {364740: 1, 353486: 10}, fittings))
        self.assertFalse(self.store.give_starting_items(char["id"], {364740: 1}, fittings))
        self.assertEqual(self.store.quantity(char["id"], 364740), 1)
        self.assertEqual([(f["name"], f["idx"], f["is_default"]) for f in self.store.fittings_of(char["id"])],
                         [("Frontline", 0, 1), ("LAV", 1, 0)])

    def test_fittings(self):
        char = self.char(self.store.user_for_online_id("x")["id"])
        a = self.store.create_fitting(char["id"], 354941, "A")
        self.store.set_slot(a["id"], "WP-1", 353120)
        self.store.set_slot(a["id"], "GS-1", None)
        b = self.store.create_fitting(char["id"], 354941, "B", slots=self.store.fitting_slots(a["id"]))
        self.assertEqual(self.store.fitting_slots(b["id"]), {"WP-1": 353120, "GS-1": None})
        self.store.update_fitting(b["id"], name="C", index=0, isDefault=True, readonly=True)
        self.assertEqual([f["name"] for f in self.store.fittings_of(char["id"])], ["A", "C"])  # same index, by id
        self.assertEqual(self.store.fitting(b["id"])["is_default"], 1)
        self.store.delete_fitting(a["id"])
        self.assertIsNone(self.store.fitting(a["id"]))
        self.assertEqual(self.store.fitting_slots(a["id"]), {})

    def test_aur_and_lp_defaults(self):
        user = self.store.user_for_online_id("x")
        char = self.char(user["id"])
        self.assertEqual(self.store.aur(user["id"], 500), 500)
        self.store.set_aur(user["id"], 0)
        self.assertEqual(self.store.aur(user["id"], 500), 0)
        self.assertEqual(self.store.lp(char["id"], 1000198, 7), 7)
        self.store.set_lp(char["id"], 1000198, 3)
        self.assertEqual((self.store.lp(char["id"], 1000198, 7), self.store.lp(char["id"], 1000262, 7)), (3, 7))

    def test_battle_booking(self):
        char = self.char(self.store.user_for_online_id("x")["id"])
        self.store.add_items(char["id"], {111: 2, 222: 1})
        self.store.add_battle_member("cred1", 514001, 2100001612, char["id"], 0, now=1000.0)
        changed, taken = self.store.complete_battle_member("cred1", 800, True, 1300, 140000, {111: 5, 333: 1},
                                                           now=1000.0)
        self.assertEqual(taken, {111: 2})  # never below 0, unknown types skipped
        self.assertEqual([(c["type_id"], c["quantity"]) for c in changed], [(111, 0)])
        after = self.store.character(char["id"])
        self.assertEqual((after["sp_base"], after["isk"]), (501300, 25000 + 140000))
        self.assertIsNone(self.store.complete_battle_member("cred1", 800, True, 1300, 140000, {}, now=1001.0))
        self.assertIsNone(self.store.complete_battle_member("unknown", 0, None, 0, 0, {}))
        self.assertEqual((self.store.battle_sp_since(char["id"], 1000.0), self.store.battle_sp_since(char["id"], 1000.5)),
                         (1300, 0))


if __name__ == "__main__":
    unittest.main()
