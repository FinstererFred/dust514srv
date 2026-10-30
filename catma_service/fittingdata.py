# Python 2.7 -- every adapter (dropsuit, vehicle; class Adapter) from the client's CATMA database with its fitting
# category (dust.fitting.GetAdapterCategory: 1 dropsuit, 2 vehicle, ...) and its slots in order, named like CCP's
# offline handler does (offlineResourceFittings.GetOfflineFittingData: slot type plus a count per type, "IH-2"),
# with the default module a preset (militia) suit comes with. Served by offline_service.py as GET /fittings for the
# per-character fittings in crest_app/store.
from catma import catmaDB

import dust.fitting


def _Slots(ct):
    slots = ct.GetValue('mModuleSlots', None)
    result, counts = [], {}
    while slots is not None:
        elem = slots.GetValue(str(len(result)))
        if not elem:
            break
        slotType = elem.GetValue('slotType')
        counts[slotType] = counts.get(slotType, 0) + 1
        default = elem.GetValue('defaultModuleType', None)
        result.append({'name': '%s-%d' % (slotType, counts[slotType]), 'visible': bool(elem.GetValue('visible')),
                       'defaultModule': int(default) if default else None})
    return result


def Build():
    db = catmaDB.GetDB()
    adapters = []
    for ct in db.GetTypeOfClass('Adapter'):
        typeID = int(ct.GetTypeID())
        adapters.append({'id': typeID, 'typeName': ct.GetTypeName(),
                         'category': dust.fitting.GetAdapterCategory(typeID), 'slots': _Slots(ct)})
    return {'adapters': adapters}
