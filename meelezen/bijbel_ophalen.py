"""De Statenvertaling downloaden en omzetten naar data/bijbel.json.

Bron: de getBible-API (module 'statenvertaling' van CrossWire), gebaseerd op de
elektronische editie van Statenvertaling Online (statenvertaling.net). Publiek domein.

Gebruik:  python -m meelezen.bijbel_ophalen
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

from .config import BASIS

API = "https://api.getbible.net/v2/statenvertaling"
DOEL = BASIS / "data" / "bijbel.json"


def haal(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Meelezen/1.0 (kerk-app)"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def schoon(tekst: str) -> str:
    tekst = re.sub(r"<[^>]+>", "", tekst or "")
    tekst = re.sub(r"\\[a-z]+\*?", "", tekst)          # eventuele USFM-codes
    return re.sub(r"\s+", " ", html.unescape(tekst)).strip()


def _lijst(x):
    """getBible gebruikt soms lijsten, soms objecten met nummers als sleutel."""
    if isinstance(x, dict):
        return list(x.values())
    return x or []


def omzetten(data) -> dict:
    boeken = _lijst(data.get("books") if isinstance(data, dict) else data)
    uit: dict[str, dict] = {}
    for boek in boeken:
        naam = boek.get("name") or boek.get("book_name")
        hoofdstukken: dict[str, dict] = {}
        for h in _lijst(boek.get("chapters")):
            verzen = {}
            for v in _lijst(h.get("verses")):
                nr = v.get("verse")
                tekst = schoon(v.get("text", ""))
                if nr is not None and tekst:
                    verzen[str(int(nr))] = tekst
            hnr = h.get("chapter") or (_lijst(h.get("verses")) or [{}])[0].get("chapter")
            if hnr is not None and verzen:
                hoofdstukken[str(int(hnr))] = verzen
        if naam and hoofdstukken:
            uit[naam] = hoofdstukken
    return uit


def main():
    print("Statenvertaling downloaden (± 5 MB)…")
    try:
        data = haal(API + ".json")
        bijbel = omzetten(data)
    except Exception as e:
        print(f"Hele vertaling in één keer lukte niet ({e}); per boek proberen…")
        bijbel = {}
        for nr in range(1, 67):
            try:
                bijbel.update(omzetten({"books": [haal(f"{API}/{nr}.json")]}))
                print(f"  boek {nr}/66", end="\r")
            except Exception as e2:
                print(f"\n  boek {nr} mislukt: {e2}")
    verzen = sum(len(h) for b in bijbel.values() for h in b.values())
    print(f"\n{len(bijbel)} boeken, {verzen} verzen.")
    if len(bijbel) < 66 or verzen < 30000:
        print("Dat is onvolledig; data/bijbel.json is NIET vervangen.")
        sys.exit(1)
    if DOEL.exists():
        shutil.copy(DOEL, DOEL.with_suffix(".json.bak"))
    DOEL.write_text(json.dumps(bijbel, ensure_ascii=False), encoding="utf-8")
    eerste = next(iter(bijbel))
    print(f"Opgeslagen in {DOEL}")
    print(f"Boeknamen: {', '.join(list(bijbel)[:5])} … {', '.join(list(bijbel)[-3:])}")
    print(f"Controle {eerste} 1:1: {bijbel[eerste]['1']['1'][:80]}")


if __name__ == "__main__":
    main()
