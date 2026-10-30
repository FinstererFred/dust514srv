"""Tests for skills.py with a small made-up skill set: python -m unittest discover -s dust_server/tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import skills

DATA = {"costTable": [6220, 18650, 43530, 87060, 155460], "maxLevel": 5, "skills": [
    {"id": 1, "costMultiplier": 1, "required": []},
    {"id": 2, "costMultiplier": 2, "required": [{"typeID": 1, "level": 2}]},
    {"id": 3, "costMultiplier": 5, "required": [{"typeID": 2, "level": 1}]},
]}


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.rules = skills.Rules(DATA)

    def test_costs(self):
        self.assertEqual(self.rules.cumulative_cost(1, 0), 0)
        self.assertEqual(self.rules.cumulative_cost(1, 2), 6220 + 18650)
        self.assertEqual(self.rules.cumulative_cost(2, 5), 2 * 310920)
        self.assertEqual(self.rules.spent({1: 2, 2: 1, 999: 5}), 24870 + 12440)  # unknown types cost nothing
        self.assertEqual(self.rules.free_sp(100000, {1: 2}), 100000 - 24870)

    def test_book(self):
        self.assertEqual(self.rules.check_book({}, 42), skills.NOT_A_SKILL)
        self.assertIsNone(self.rules.check_book({}, 1))
        self.assertEqual(self.rules.check_book({1: 0}, 1), skills.ALREADY_KNOWN)
        self.assertEqual(self.rules.check_book({}, 2), skills.MISSING_PREREQ)
        self.assertEqual(self.rules.check_book({1: 1}, 2), skills.PREREQ_TOO_LOW)
        self.assertIsNone(self.rules.check_book({1: 2}, 2))

    def test_upgrade(self):
        known = {1: 0}
        self.assertIsNone(self.rules.check_upgrade(known, 6220, 1, 0, 1))
        self.assertEqual(self.rules.check_upgrade(known, 6219, 1, 0, 1), skills.NOT_ENOUGH_SP)
        self.assertEqual(self.rules.check_upgrade(known, 10 ** 7, 1, 1, 2), skills.LEVEL_MISMATCH)
        self.assertEqual(self.rules.check_upgrade(known, 10 ** 7, 2, 0, 1), skills.MISSING_PREVIOUS_LEVEL)
        self.assertEqual(self.rules.check_upgrade(known, 10 ** 7, 1, 0, 0), skills.CANNOT_DOWNGRADE)
        self.assertEqual(self.rules.check_upgrade(known, 10 ** 7, 1, 0, 6), skills.ALREADY_MAX_LEVEL)
        self.assertEqual(self.rules.check_upgrade({1: 5}, 10 ** 7, 1, 5, 5), skills.ALREADY_MAX_LEVEL)
        # free SP count the SP already spent on other skills
        self.assertEqual(self.rules.check_upgrade({1: 2, 2: 0}, 24870 + 12439, 2, 0, 1), skills.NOT_ENOUGH_SP)
        self.assertIsNone(self.rules.check_upgrade({1: 2, 2: 0}, 24870 + 12440, 2, 0, 1))
        # several levels at once cost the sum of their marginal costs
        self.assertIsNone(self.rules.check_upgrade(known, 6220 + 18650 + 43530, 1, 0, 3))


class RespecTest(unittest.TestCase):
    def test_respec(self):
        known = {1: 4, 2: 1, 3: 0, 9: 2}  # 1 starting (raised), 2 and 3 bought, 9 a corporation skill
        new, refunded = skills.respec(known, starting={1: 1, 4: 1}, keep={9})
        self.assertEqual(new, {1: 1, 4: 1, 9: 2})  # a removed starting skill (4) comes back
        self.assertEqual(refunded, [2, 3])  # also a book read without training (level 0)
        self.assertEqual(skills.respec({1: 1}, {1: 1}, set()), ({1: 1}, []))


if __name__ == "__main__":
    unittest.main()
