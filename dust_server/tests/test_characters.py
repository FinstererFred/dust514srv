"""Tests for characters.py (creation and deletion rules): python -m unittest discover -s dust_server/tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import characters


def taken(*names):
    return lambda name: name.lower() in {n.lower() for n in names}


class CreationTest(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(characters.clean_name("  Kado   Omanid "), "Kado Omanid")
        self.assertEqual(characters.clean_name("Kado "), "Kado")  # empty family name
        self.assertEqual(characters.clean_name(None), "")

    def test_check_new(self):
        free = taken()
        self.assertIsNone(characters.check_new("Kado Omanid", 5, 0, free))
        self.assertIsNone(characters.check_new("O'Neil-7 X", 1, 2, free))
        self.assertEqual(characters.check_new("Kado Omanid", 5, 3, free), characters.NO_FREE_SLOT)
        self.assertEqual(characters.check_new("Kado Omanid", 6, 0, free), characters.UNKNOWN_BLOODLINE)  # Ni-Kunni
        self.assertEqual(characters.check_new("Kado Omanid", None, 0, free), characters.UNKNOWN_BLOODLINE)
        self.assertEqual(characters.check_new("Ka", 5, 0, free), characters.NAME_LENGTH)
        self.assertEqual(characters.check_new("K" * 38, 5, 0, free), characters.NAME_LENGTH)
        self.assertEqual(characters.check_new("Kadö Omanid", 5, 0, free), characters.NAME_INVALID)
        self.assertEqual(characters.check_new("Kado_Omanid", 5, 0, free), characters.NAME_INVALID)
        self.assertEqual(characters.check_new("kado omanid", 5, 0, taken("Kado Omanid")), characters.NAME_TAKEN)

    def test_tables(self):
        races = {race for _, race, _ in characters.BLOODLINES.values()}
        self.assertEqual(races, set(characters.PORTRAIT_BY_RACE))
        self.assertEqual(races, set(characters.NPC_CORPORATIONS))
        self.assertEqual(races, set(characters.STARTING_CORPORATIONS))
        self.assertEqual(len(characters.NPC_CORPORATION_NAMES), 48)  # 12 per race, no ID twice
        for race, corp_id in characters.NPC_CORPORATIONS.items():  # each race's default is one of its own
            self.assertIn(corp_id, dict(characters.STARTING_CORPORATIONS[race]))
        self.assertEqual(characters.race_of(5), characters.AMARR)
        self.assertEqual(characters.race_of(11), characters.CALDARI)  # Achura


class DeletionTest(unittest.TestCase):
    def test_delete_prepare_date(self):
        self.assertIsNone(characters.delete_prepare_date(None))
        self.assertEqual(characters.delete_prepare_date(0), "1970-01-01T00:00:00")
        self.assertEqual(characters.delete_prepare_date(1792800000.9), "2026-10-24T00:00:00")

    def test_may_delete(self):
        self.assertFalse(characters.may_delete(None, 100))
        self.assertFalse(characters.may_delete(101, 100))
        self.assertTrue(characters.may_delete(100, 100))


if __name__ == "__main__":
    unittest.main()
