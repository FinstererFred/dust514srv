# Python 2.7 (-O) -- runs CCP's original offline CREST handlers with the real CATMA database.
import json
import logging
import os
import sys
import traceback

import clientenv

clientenv.setup()
logging.basicConfig(level=logging.WARNING)

from catma import catmaUtil, catmaDB

with open(os.path.join(clientenv.VAULT, 'CATMADB.PICKLE'), 'rb') as f:
    catmaDB.SetDB(catmaUtil.SafeLoad(f.read()))

import offline.offlineSession
import offline.offlineResource as res

PATHS = sys.argv[1:] or [
    '/characters/2100001611/mercenary/skills/',
    '/inventory/2100001611/owner/2100001611/all/',
    '/characters/2100001611/mercenary/fittings/',
]
for path in PATHS:
    try:
        result = res.OfflineResource('http://127.0.0.1:26004' + path).Get(accept='x')
        text = json.dumps(result, default=repr)
        print('%s OK %d bytes: %s' % (path, len(text), text[:300]))
    except Exception:
        print('%s FAILED' % path)
        traceback.print_exc()
