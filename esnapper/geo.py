"""Entfernung zwischen deutschen Postleitzahlen (Daten: GeoNames, CC BY 4.0).

eBay zeigt die PLZ des Artikelstandorts oft nur teilweise (z. B. "257**"). Darum rechnen wir
mit dem Mittelpunkt aller PLZ, die mit den bekannten Ziffern beginnen. Bei 2 Ziffern liegt
das auf etwa ±50 km genau, für Umkreise von einigen hundert Kilometern reicht das.
"""
import io
import math
import re
import zipfile
from pathlib import Path

import requests

SOURCE = "https://download.geonames.org/export/zip/DE.zip"
CACHE = Path("data/geo/DE.txt")


def load_postal_codes(cache=CACHE):
    """{plz: (lat, lon)}; lädt die Datei beim ersten Mal herunter."""
    if not cache.exists():
        r = requests.get(SOURCE, timeout=60)
        r.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(zipfile.ZipFile(io.BytesIO(r.content)).read("DE.txt"))
    codes = {}
    for line in cache.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        codes.setdefault(cols[1], (float(cols[9]), float(cols[10])))
    return codes


def haversine_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


class Locator:
    def __init__(self, codes):
        self.codes = codes
        self._prefix_cache = {}

    def locate(self, postal_code):
        """Koordinaten zu einer (evtl. maskierten) PLZ, None wenn unbekannt."""
        digits = re.match(r"\d*", postal_code or "").group()
        if len(digits) < 2:
            return None
        digits = digits[:5]
        if digits not in self._prefix_cache:
            points = [p for code, p in self.codes.items() if code.startswith(digits)]
            self._prefix_cache[digits] = (
                (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))
                if points else None)
        return self._prefix_cache[digits]

    def distance_km(self, from_code, to_code):
        a, b = self.locate(from_code), self.locate(to_code)
        return haversine_km(a, b) if a and b else None
