# Python 2.7 -- catalog from the client's CATMA database: the market group tree (InventoryCategory types under
# MarketGroup-350001), every InventoryItem with its English name, category and base prices, and the battle
# levels (GalaxyLevel: UE3 map, game mode sublevels, terraforming, moods) with the game types (DustGameType).
# Served by offline_service.py as GET /catalog for the admin interface and the market handlers in crest_app.
import os

import clientenv
from catma import catmaDB, catmaUtil

ROOT_MARKET_GROUP = 350001  # dust.inventory.DUST_ROOT_MARKET_GROUP
LANGUAGE = 'EN-US'

_strings = None
_rowset = None


def _LoadStrings():
    global _strings, _rowset
    if _strings is None:
        # The client's own string cache for CATMA texts; names missing there are in the localization rowset
        # (catmaLocalizationSvc._LoadStringFromRowset).
        with open(os.path.join(clientenv.VAULT, 'STRINGCACHE-CATMA-%s.PICKLE' % LANGUAGE), 'rb') as f:
            _strings = catmaUtil.SafeLoad(f.read())
        import stackless
        if not hasattr(stackless, 'current'):
            stackless.main = stackless.current = object()  # crowset checks for the main tasklet
        from sakeccp import crowset
        _rowset = crowset.CIndexRowsetDisk('LOCALIZATION-CATMA-%s' % LANGUAGE, [clientenv.VAULT])


def _Text(ct, attribute):
    stringID = ct.GetValue(attribute, None, localized=False)
    if not stringID:
        return None
    text = _strings.get(int(stringID))
    if text is None:
        mainID, secondaryID = catmaUtil.RemapStringID(int(stringID))
        row = _rowset.get(mainID, None)
        text = row.line.get(secondaryID) if row else None
    return text


def _SortOrder(typeID):
    try:
        import dust.inventory
        return dust.inventory.GetMarketGroupSortOrder(typeID)
    except Exception:
        return 0


def Build():
    _LoadStrings()
    db = catmaDB.GetDB()
    categories = []
    for ct in db.GetTypeOfClass('InventoryCategory'):
        parent = ct.GetValue('parentCategoryID', None)
        categories.append({'id': ct.GetTypeID(), 'parent': parent if parent and parent > 0 else None,
                           'name': _Text(ct, 'categoryName') or ct.GetTypeName(),
                           'description': _Text(ct, 'description'), 'sortOrder': _SortOrder(ct.GetTypeID())})
    items = []
    for ct in db.GetTypeOfClass('InventoryItem'):
        items.append({'id': ct.GetTypeID(), 'typeName': ct.GetTypeName(),
                      'name': _Text(ct, 'mDisplayName') or ct.GetTypeName(),
                      'description': _Text(ct, 'mShortDescription'),
                      'categoryID': ct.GetValue('categoryID', None),
                      'basePrice': ct.GetValue('basePrice', 0) or 0,
                      'baseAurPrice': ct.GetValue('baseAurPrice', 0) or 0,
                      'metaLevel': ct.GetValue('metaLevel', None)})
    levels = []
    for ct in db.GetTypeOfClass('GalaxyLevel'):
        levels.append({'id': ct.GetTypeID(), 'typeName': ct.GetTypeName(), 'name': _Text(ct, 'mDisplayName'),
                       'map': ct.GetValue('mapName', None), 'productionReady': ct.GetValue('mProductionReady', False),
                       'modes': [{'gameType': mode['gameMode'], 'level': mode['mapName'],
                                  'productionReady': mode.get('mProductionReady', False),
                                  'matchmaking': mode.get('useInMatchmaking', False)}
                                 for mode in _List(ct, 'gameModes', ('gameMode', 'mapName', 'mProductionReady',
                                                                     'useInMatchmaking'))],
                       'terraforming': [t['name'] for t in _List(ct, 'terraforming', ('name', 'mProductionReady'))
                                        if t.get('mProductionReady')],
                       'moods': [db.GetTypeByID(m['']).GetValue('mapName', None) for m in _List(ct, 'moods', ('',))
                                 if m.get('')]})
    gameTypes = [{'id': ct.GetTypeID(), 'typeName': ct.GetTypeName(), 'name': _Text(ct, 'mDisplayName')}
                 for ct in db.GetTypeOfClass('DustGameType')]
    return {'root': ROOT_MARKET_GROUP, 'categories': categories, 'items': items, 'levels': levels,
            'gameTypes': gameTypes}


def _List(ct, name, fields):
    """CATMA list attribute as dicts, e.g. gameModes.0.mapName ('' = the element itself, as in moods.0)."""
    result = []
    while True:
        prefix = '%s.%d' % (name, len(result))
        entry = {}
        for field in fields:
            value = ct.GetValue(prefix + ('.' + field if field else ''), None)
            if value is not None:
                entry[field] = value
        if not entry:
            return result
        result.append(entry)
