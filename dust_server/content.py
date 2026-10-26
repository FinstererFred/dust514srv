"""Server content the web admin edits (admin.py) and the CREST handlers serve (crest_app.py).

Each area is one JSON file in content/; a missing file or key means the defaults below. Files are read on
every request, so changes reach the game without a restart (the client caches some data per login).

The market works on the catalog from the CATMA service (catma_service/catalog.py): the market group tree and
every item with its name and base prices. On top of the default rules each area keeps per-item overrides
({"<typeID>": {"enabled": bool, "price": int}}), so a new catalog never loses what was set by hand.
"""

import json
import os
import threading
from pathlib import Path

import offline_bridge

CONTENT_DIR = Path(os.environ.get("DUST_CONTENT_DIR") or Path(__file__).resolve().parent / "content")

LOYALTY_STORES = {  # corporation id -> market group (dust/loyaltyStoreClient.py STORE_GROUPS)
    1000262: 365996,  # Federal Marines
    1000198: 365997,  # Imperial Guard
    1000263: 365998,  # Republic Command
    1000261: 365999,  # State Peacekeepers
}
LOYALTY_ROOT_GROUP = 365995

DEFAULTS = {
    # ISK market: every item with a base price that is not an AUR item, outside the loyalty store groups.
    "market": {"enabled": True, "excluded_groups": [LOYALTY_ROOT_GROUP], "hidden_groups": [], "items": {}},
    # AUR store (VGS): every item with a base AUR price, outside the loyalty store groups (those cost LP).
    "aur_store": {"enabled": True, "items": {}},
    # Loyalty stores: balance per corporation; offers only where set by hand ({"<typeID>": {"lp", "isk"}}).
    "loyalty": {"stores": {str(corp): {"balance": 0, "offers": {}} for corp in LOYALTY_STORES}},
    # Daily login rewards per consecutive day (questsClient/welcomeScreen index this list).
    "rewards": {"daily_login": [{"sp": sp, "aur": aur} for sp, aur in
                                [(10000, 0), (15000, 0), (20000, 0), (25000, 0), (30000, 0), (35000, 0), (40000, 50)]]},
    "wallet": {"isk": 12345, "aur": 0},
    # Market storefront page; None = CCP's offline storefront.
    "storefront": {"layout": None},
}

_lock = threading.Lock()


def path(name):
    return CONTENT_DIR / f"{name}.json"


def load(name):
    data = json.loads(json.dumps(DEFAULTS[name]))
    file = path(name)
    if file.exists():
        data.update(json.loads(file.read_text(encoding="utf-8")))
    return data


def save(name, data):
    with _lock:
        CONTENT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path(name).with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path(name))


# --- catalog ----------------------------------------------------------------------------------------

class Catalog:
    def __init__(self, data):
        self.raw = data
        self.root = data["root"]
        self.groups = {g["id"]: g for g in data["categories"]}
        self.items = {i["id"]: i for i in data["items"]}
        self.children = {}
        for g in data["categories"]:
            self.children.setdefault(g["parent"], []).append(g["id"])
        for ids in self.children.values():
            ids.sort(key=lambda gid: (self.groups[gid]["sortOrder"], gid))

    def subtree(self, group_id):
        """group_id and all groups below it."""
        result, todo = set(), [group_id]
        while todo:
            gid = todo.pop()
            if gid not in result:
                result.add(gid)
                todo.extend(self.children.get(gid, []))
        return result

    def market_groups(self):
        return self.subtree(self.root)


_catalog = []


def catalog():
    if not _catalog:
        _catalog.append(Catalog(offline_bridge.catalog()))
    return _catalog[0]


def _override(overrides, type_id):
    return overrides.get(str(type_id)) or {}


def isk_market(config=None):
    """{typeID: price} of the items the ISK market sells."""
    config = config or load("market")
    if not config["enabled"]:
        return {}
    cat = catalog()
    excluded = set().union(*(cat.subtree(g) for g in config["excluded_groups"])) if config["excluded_groups"] else set()
    hidden = set().union(*(cat.subtree(g) for g in config["hidden_groups"])) if config["hidden_groups"] else set()
    in_market = cat.market_groups() - hidden
    prices = {}
    for item in cat.items.values():
        if item["categoryID"] not in in_market:
            continue
        default = item["basePrice"] > 0 and not item["baseAurPrice"] and item["categoryID"] not in excluded
        override = _override(config["items"], item["id"])
        price = override.get("price") or item["basePrice"]
        if override.get("enabled", default) and price > 0:
            prices[item["id"]] = price
    return prices


def aur_store(config=None):
    """{typeID: AUR price} of the plain offers in the AUR store."""
    config = config or load("aur_store")
    if not config["enabled"]:
        return {}
    cat = catalog()
    in_market = cat.market_groups()
    loyalty = cat.subtree(LOYALTY_ROOT_GROUP)
    prices = {}
    for item in cat.items.values():
        if item["categoryID"] not in in_market:
            continue
        default = item["baseAurPrice"] > 0 and item["categoryID"] not in loyalty
        override = _override(config["items"], item["id"])
        price = override.get("price") or item["baseAurPrice"]
        if override.get("enabled", default) and price > 0:
            prices[item["id"]] = price
    return prices


def loyalty_offers(config=None):
    """{corporation id: [(typeID, lp, isk)]}"""
    config = config or load("loyalty")
    result = {}
    for corp in LOYALTY_STORES:
        store = config["stores"].get(str(corp)) or {}
        result[corp] = [(int(type_id), offer.get("lp", 0), offer.get("isk", 0))
                        for type_id, offer in (store.get("offers") or {}).items()]
    return result
