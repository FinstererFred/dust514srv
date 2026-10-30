"""Without DUST_CHAR_STORE the server answers as before the character server (tools/legacy_parity.py).

Needs the CATMA service (DUST_OFFLINE_SERVICE, default :8090) and git; skipped if either is missing.
"""

import os
import sys
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import legacy_parity

SERVICE = os.environ.get("DUST_OFFLINE_SERVICE", "http://127.0.0.1:8090")


def service_up():
    try:
        urllib.request.urlopen(f"{SERVICE}/catalog", timeout=120).close()
        return True
    except OSError:
        return False


@unittest.skipUnless(service_up(), f"CATMA service not reachable at {SERVICE}")
class LegacyParityTest(unittest.TestCase):
    def test_offline_characters_unchanged(self):
        self.assertEqual(legacy_parity.compare(service=SERVICE), [])


if __name__ == "__main__":
    unittest.main()
