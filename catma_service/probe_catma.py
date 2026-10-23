# Python 2.7 (run with -O so the original .pyo files are used) -- loads the client's CATMA database.
import logging
import os
import sys
import time

import clientenv

clientenv.setup()
logging.basicConfig(level=logging.INFO)

from catma import catmaUtil, catmaDB

t0 = time.time()
with open(os.path.join(clientenv.VAULT, 'CATMADB.PICKLE'), 'rb') as f:
    cdb = catmaUtil.SafeLoad(f.read())
print('loaded in %.1fs: %r' % (time.time() - t0, cdb))
catmaDB.SetDB(cdb)
db = catmaDB.GetDB()
for cls in ('DustQuestDailyBonus', 'DustSkill'):
    try:
        types_ = db.GetTypeOfClass(cls)
        print(cls, len(types_), [(t.GetTypeID(), t.GetTypeName()) for t in types_[:3]])
    except Exception as e:
        print(cls, 'ERROR', repr(e))
