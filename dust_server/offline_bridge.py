"""Client for catma_service/offline_service.py, the Python 2.7 service that runs CCP's original offline
CREST handlers with the client's real CATMA database. Same dispatch() contract as offline_loader."""

import json
import urllib.request

SERVICE_URL = "http://127.0.0.1:8090/dispatch"
OFFLINE_HOST = "http://127.0.0.1:26004"


class OfflineHandlerError(RuntimeError):
    """An offline handler raised; the message carries the Python 2 traceback."""


def dispatch(method, path, parameters=None, resource=None):
    """Return (found, result); result is an OfflineHandlerError if the handler failed."""
    request = json.dumps({"method": method.capitalize(), "path": path, "parameters": parameters, "data": resource})
    req = urllib.request.Request(SERVICE_URL, request.encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        reply = json.loads(response.read())
    if not reply["found"]:
        return False, None
    if "error" in reply:
        last_line = reply["error"].strip().splitlines()[-1]
        return True, OfflineHandlerError(last_line + "\n" + reply["error"])
    return True, reply["result"]
