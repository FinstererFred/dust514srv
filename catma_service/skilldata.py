# Python 2.7 -- every skill from the client's CATMA database (class Skill): type ID, internal and English name, cost
# multiplier, prerequisites (dust.skill.GetRequiredSkillList) and the skill book's base price in ISK, plus the cost
# table. Served by offline_service.py as GET /skills for dust_server/skills.py, which does the checks in Python 3.
from catma import catmaDB

import catalog
import dust.skill


def Build():
    catalog._LoadStrings()
    db = catmaDB.GetDB()
    skills = []
    for ct in db.GetTypeOfClass('Skill'):
        skills.append({
            'id': int(ct.GetTypeID()), 'typeName': ct.GetTypeName(),
            'name': catalog._Text(ct, 'mDisplayName') or ct.GetTypeName(),
            'costMultiplier': int(ct.GetValue('costMultiplier', 0) or 0),
            'basePrice': int(ct.GetValue('basePrice', 0) or 0),
            'required': [{'typeID': int(r['typeID']), 'level': int(r['level'] or 1)}
                         for r in dust.skill.GetRequiredSkillList(ct) if r['typeID']],
        })
    return {'costTable': list(dust.skill.SKILL_COST_TABLE), 'maxLevel': dust.skill.MAX_SKILL_LEVEL, 'skills': skills}
