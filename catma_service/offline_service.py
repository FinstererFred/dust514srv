# Python 2.7 (run with -O) -- internal service that answers CREST requests with CCP's original offline
# handlers (offline/offlineResource*.pyo from the client) backed by the real CATMA database.
#
#   POST /dispatch  {"method": "Get", "path": "/characters/1/mercenary/skills/", "parameters": {...}, "data": ...}
#   -> {"found": true, "result": ...} | {"found": true, "error": "<traceback>"} | {"found": false}
import BaseHTTPServer
import SocketServer
import json
import logging
import os
import re
import sys
import threading
import traceback

import clientenv

clientenv.setup()
logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger('offline_service')

from catma import catmaUtil, catmaDB

with open(os.path.join(clientenv.VAULT, 'CATMADB.PICKLE'), 'rb') as f:
    catmaDB.SetDB(catmaUtil.SafeLoad(f.read()))

import offline.offlineSession  # imports and registers the offline handler modules it knows about
import offline.offlineResource as offlineResource

# offlineSession does not import every handler module (the VGS store module is loaded elsewhere in the
# client), so register all of them.
_offline_dir = os.path.join(clientenv.EXTRACTED, 'COMMON', 'offline')
for _name in sorted(os.listdir(_offline_dir)):
    if _name.startswith('offlineResource') and _name.endswith('.pyo'):
        __import__('offline.' + _name[:-len('.pyo')])

OFFLINE_HOST = 'http://127.0.0.1:26004'
_lock = threading.Lock()  # the handlers and the CATMA DB were written for a single game thread


def dispatch(method, path, parameters=None, data=None):
    resource = offlineResource.OfflineResource(OFFLINE_HOST + path)
    handlers = resource._GetHandlers()
    if not any(re.match(resource._CompileRoute(h.Route())[0], resource.path) for h in handlers):
        return {'found': False}
    try:
        with _lock:
            result = resource._ProcessRequest(method, parameters, False, data)
        return {'found': True, 'result': result}
    except Exception:
        return {'found': True, 'error': traceback.format_exc()}


class Handler(BaseHTTPServer.BaseHTTPRequestHandler):

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.getheader('content-length', 0))))
        reply = dispatch(request['method'], request['path'], request.get('parameters'), request.get('data'))
        body = json.dumps(reply, default=repr)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


class Server(SocketServer.ThreadingMixIn, BaseHTTPServer.HTTPServer):
    daemon_threads = True


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    server = Server(('127.0.0.1', port), Handler)
    print('offline service with %r on 127.0.0.1:%d' % (catmaDB.GetDB(), port))
    sys.stdout.flush()
    server.serve_forever()
