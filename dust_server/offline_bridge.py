"""Client for catma_service/offline_service.py, the Python 2.7 service that runs CCP's original offline
CREST handlers with the client's real CATMA database. Same dispatch() contract as offline_loader."""

import json
import os
import urllib.request

SERVICE_BASE = os.environ.get("DUST_OFFLINE_SERVICE", "http://127.0.0.1:8090")
SERVICE_URL = f"{SERVICE_BASE}/dispatch"
CATALOG_URL = f"{SERVICE_BASE}/catalog"
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


def catalog():
    """Market groups and items from the client's CATMA database (catma_service/catalog.py)."""
    with urllib.request.urlopen(CATALOG_URL, timeout=60) as response:
        return json.loads(response.read())


def skills():
    """Skills with cost multiplier, prerequisites and the cost table (catma_service/skilldata.py)."""
    with urllib.request.urlopen(f"{SERVICE_BASE}/skills", timeout=60) as response:
        return json.loads(response.read())


def specialties():
    """Starting values per character specialty from the client's CATMA database (catma_service/specialties.py)."""
    with urllib.request.urlopen(f"{SERVICE_BASE}/specialties", timeout=60) as response:
        return json.loads(response.read())


def fittings():
    """Adapters (dropsuits, vehicles) with fitting category and slots (catma_service/fittingdata.py)."""
    with urllib.request.urlopen(f"{SERVICE_BASE}/fittings", timeout=60) as response:
        return json.loads(response.read())
