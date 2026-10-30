# Python 2.7 -- starting values per character specialty from the client's CATMA database (class CharacterSpecialty,
# one "Enforcer" per race): race, starting SP (includes the cost of the starting skills), SP per day, starting ISK,
# starting skills and starting inventory. Served by offline_service.py as GET /specialties for crest_app/store.
from catma import catmaDB

import dust.character


def _List(ct, name, fields):
    """CATMA list attribute as dicts, e.g. startingSkills.0.skillTypeID."""
    result = []
    while True:
        prefix = '%s.%d' % (name, len(result))
        entry = {}
        for field in fields:
            value = ct.GetValue(prefix + '.' + field, None)
            if value is not None:
                entry[field] = value
        if not entry:
            return result
        result.append(entry)


def _Int(value):
    return int(value) if value is not None else None


def _RaceID(value):
    # ERace is stored as the editor name (dust.character.GetEditorRaceName); map it back to the race ID.
    if isinstance(value, (int, long)):
        return value
    for raceID in (1, 2, 4, 8):
        if dust.character.GetEditorRaceName(raceID) == value:
            return raceID
    return None


def Build():
    db = catmaDB.GetDB()
    result = []
    for ct in db.GetTypeOfClass('CharacterSpecialty'):
        result.append({
            'id': ct.GetTypeID(), 'typeName': ct.GetTypeName(),
            'race': _RaceID(ct.GetValue('race', None)),
            'startingSkillPoints': _Int(ct.GetValue('startingSkillPoints', 0)),
            'skillPointsPerDay': _Int(ct.GetValue('skillPointsPerDay', 0)),
            'startingISK': _Int(ct.GetValue('startingISK', 0)),
            'startingSkills': [{'skillTypeID': _Int(s.get('skillTypeID')), 'skillLevel': _Int(s.get('skillLevel'))}
                               for s in _List(ct, 'startingSkills', ('skillTypeID', 'skillLevel'))],
            'startingInventory': [{'type': _Int(i.get('type')), 'quantity': _Int(i.get('quantity', 1)),
                                   'shouldGiveFitting': bool(i.get('shouldGiveFitting')),
                                   'shouldMakeFittingDefault': bool(i.get('shouldMakeFittingDefault'))}
                                  for i in _List(ct, 'startingInventory',
                                                 ('type', 'quantity', 'shouldGiveFitting', 'shouldMakeFittingDefault'))],
        })
    return result
