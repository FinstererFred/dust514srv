"""Skill rules for the store's characters (docs/character_server_plan.md, stage 2), mirroring dust/skill.py.

The data comes from the CATMA service (GET /skills, catma_service/skilldata.py). A character's skills are
{typeID: level}; level 0 is a skill whose book was read but no level trained (the client then offers the upgrade
to level 1). Free SP are total SP minus the cumulative cost of every known skill, as the client computes them.
"""

# Error codes as in dust/skill.py
NOT_A_SKILL = 1
NOT_ENOUGH_SP = 2
MISSING_PREREQ = 3
MISSING_PREVIOUS_LEVEL = 4
ALREADY_MAX_LEVEL = 5
PREREQ_TOO_LOW = 6
CANNOT_DOWNGRADE = 7
ALREADY_KNOWN = 100  # ours: a second book for a known skill
LEVEL_MISMATCH = 101  # ours: the client's currentLevel is not the stored one (stale data)

ERROR_TEXT = {
    NOT_A_SKILL: "not a skill", NOT_ENOUGH_SP: "not enough skill points", MISSING_PREREQ: "missing prerequisite",
    MISSING_PREVIOUS_LEVEL: "skill not known", ALREADY_MAX_LEVEL: "already at max level",
    PREREQ_TOO_LOW: "prerequisite level too low", CANNOT_DOWNGRADE: "cannot downgrade",
    ALREADY_KNOWN: "skill already known", LEVEL_MISMATCH: "current level does not match",
}


class Rules:
    def __init__(self, data):
        self.cost_table = data["costTable"]
        self.max_level = data["maxLevel"]
        self.skills = {s["id"]: s for s in data["skills"]}

    def cumulative_cost(self, type_id, level):
        return self.skills[type_id]["costMultiplier"] * sum(self.cost_table[:level or 0])

    def spent(self, known):
        return sum(self.cumulative_cost(t, level) for t, level in known.items() if t in self.skills)

    def free_sp(self, total_sp, known):
        return total_sp - self.spent(known)

    def missing_prereq(self, known, type_id):
        """Error code if a prerequisite of `type_id` is missing or too low, else None."""
        for req in self.skills[type_id]["required"]:
            if req["typeID"] not in known:
                return MISSING_PREREQ
            if known[req["typeID"]] < req["level"]:
                return PREREQ_TOO_LOW
        return None

    def check_book(self, known, type_id):
        """Reading a skill book (POST .../skills/): the skill becomes known at level 0, which costs no SP."""
        if type_id not in self.skills:
            return NOT_A_SKILL
        if type_id in known:
            return ALREADY_KNOWN
        return self.missing_prereq(known, type_id)

    def check_upgrade(self, known, total_sp, type_id, current, aim):
        """Upgrade from `current` to `aim` (PUT .../skills/{typeID}/); error code or None."""
        if type_id not in self.skills:
            return NOT_A_SKILL
        if type_id not in known:
            return MISSING_PREVIOUS_LEVEL
        if known[type_id] != current:
            return LEVEL_MISMATCH
        if current >= self.max_level:
            return ALREADY_MAX_LEVEL
        if aim <= current:
            return CANNOT_DOWNGRADE
        if aim > self.max_level:
            return ALREADY_MAX_LEVEL
        if self.cumulative_cost(type_id, aim) - self.cumulative_cost(type_id, current) > self.free_sp(total_sp, known):
            return NOT_ENOUGH_SP
        return None
