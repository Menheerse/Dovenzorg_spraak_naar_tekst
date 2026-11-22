"""De klassieke liturgische formulieren (Statenvertaling-versie).

Ophalen:   python -m meelezen.formulieren      (of formulieren-ophalen.bat)
Opslag:    data/formulieren.json  ->  {"formulieren": [{"id", "titel", "alineas": [...]}]}

Bron: ipsalm.nl (serie 'SV · Klassiek'). Elke pagina bevat één formulier; de tekst staat tussen
de titel ('Formulier om ...') en het kopje 'Voetnoten'. Voetnootnummers worden weggelaten.
Een eigen of afwijkende tekst kan ook: zet een .txt-bestand in data/vaste-teksten/ (dat wordt
gebruikt voor het rechtzetten van voorgelezen tekst), of pas formulieren.json zelf aan.
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from .config import BASIS

DOEL = BASIS / "data" / "formulieren.json"
BRON = "https://ipsalm.nl/forms/{}"

FORMULIEREN = [
    ("avondmaal", "sv-supper-classic", "Heilig Avondmaal"),
    ("doop-kinderen", "sv-baptism-child-classic", "Doop (kinderen)"),
    ("doop-volwassenen", "sv-baptism-adult-classic", "Doop (volwassenen)"),
    ("belijdenis", "sv-confession-classic", "Openbare geloofsbelijdenis"),
    ("bevestiging-predikant", "sv-confirmation-minister-classic", "Bevestiging dienaren des Woords"),
    ("bevestiging-ouderlingen", "sv-confirmation-elder-classic", "Bevestiging ouderlingen en diakenen"),
    ("huwelijk", "sv-marriage-classic", "Huwelijk"),
    ("ban", "sv-ban-classic", "Christelijke ban"),
    ("wederopneming", "sv-restoration-classic", "Wederopneming"),
]
# woorden die zeker in het formulier staan: controle dat de goede tekst is opgehaald
KENMERK = {"avondmaal": "inzetting", "doop-kinderen": "doop", "doop-volwassenen": "doop",
           "belijdenis": "belijdenis", "bevestiging-predikant": "dienaar", "bevestiging-ouderlingen": "ouderling",
           "huwelijk": "huwelijk", "ban": "ban", "wederopneming": "gemeente"}

BLOK = {"p", "blockquote", "li", "h1", "h2", "h3", "h4", "h5", "div", "br", "tr"}
OVERSLAAN = {"script", "style", "nav", "header", "footer", "noscript", "svg", "button", "select"}


class _Lezer(HTMLParser):
    """Zet html om in een lijst tekstblokken (alinea's/koppen), zonder menu's en voetnootlinks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blokken: list[tuple[str, str]] = []
        self.diep_overslaan = 0
        self.voetnoot = 0
        self.huidig: list[str] = []
        self.soort = "p"

    def _sluit(self):
        tekst = re.sub(r"\s+", " ", "".join(self.huidig)).strip()
        if tekst:
            self.blokken.append((self.soort, tekst))
        self.huidig = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in OVERSLAAN:
            self.diep_overslaan += 1
            return
        if tag == "sup" or (tag == "a" and str(a.get("href", "")).startswith("#fn")):
            self.voetnoot += 1
            return
        if tag in BLOK:
            self._sluit()
            if tag != "br":
                self.soort = tag

    def handle_endtag(self, tag):
        if tag in OVERSLAAN:
            self.diep_overslaan = max(0, self.diep_overslaan - 1)
            return
        if tag == "sup" or (tag == "a" and self.voetnoot):
            self.voetnoot = max(0, self.voetnoot - 1)
            return
        if tag in BLOK:
            self._sluit()

    def handle_data(self, data):
        if not self.diep_overslaan and not self.voetnoot:
            self.huidig.append(data)


def uit_html(pagina: str) -> tuple[str, list[str]]:
    lezer = _Lezer()
    lezer.feed(pagina)
    lezer._sluit()
    blokken = lezer.blokken
    begin = next((i for i, (s, t) in enumerate(blokken)
                  if s in ("h1", "h2", "h3") and t.lower().startswith("formulier")), None)
    if begin is None:
        begin = next((i for i, (s, t) in enumerate(blokken) if t.lower().startswith("formulier")), None)
    if begin is None:
        raise ValueError("titel van het formulier niet gevonden")
    titel = blokken[begin][1]
    alineas = []
    for s, t in blokken[begin + 1:]:
        if t.lower().startswith(("voetnoten", "noten")) and len(t) < 40:
            break
        t = schoon(t)
        if not t or (alineas and t == alineas[-1]):
            continue
        alineas.append(t)
    return titel, alineas


def schoon(t: str) -> str:
    t = html.unescape(t).replace("­ ", "").replace("­", "")
    t = re.sub(r"(\w)- (\w)", r"\1\2", t)               # afbrekingen uit de scan
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def _haal(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Meelezen/1.0 (kerkdienst meelezen)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def ophalen(doel: Path = DOEL) -> int:
    print("Formulieren (klassiek, Statenvertaling) ophalen van ipsalm.nl…")
    uit, fouten = [], 0
    for fid, slug, naam in FORMULIEREN:
        try:
            titel, alineas = uit_html(_haal(BRON.format(slug)))
            tekst = " ".join(alineas)
            if len(tekst) < 1500 or KENMERK[fid] not in tekst.lower():
                raise ValueError(f"tekst lijkt niet compleet ({len(tekst)} tekens)")
            uit.append({"id": fid, "naam": naam, "titel": titel, "alineas": alineas})
            print(f"  ✓ {naam}: {len(alineas)} alinea's, {len(tekst.split())} woorden")
        except Exception as e:
            fouten += 1
            print(f"  ✗ {naam}: {e}")
    if not uit:
        print("\nEr is niets opgehaald. Is er internet? Probeer het later opnieuw.")
        return 1
    doel.parent.mkdir(parents=True, exist_ok=True)
    doel.write_text(json.dumps({"bron": "ipsalm.nl, SV klassiek", "formulieren": uit}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"\nOpgeslagen in {doel}")
    a = next((f for f in uit if f["id"] == "avondmaal"), uit[0])
    print("Controle, begin van", a["naam"] + ":", a["alineas"][0][:110] + "…")
    return 0 if not fouten else 2


class Formulieren:
    """Leest data/formulieren.json (opnieuw als het bestand verandert)."""

    def __init__(self, pad: Path = DOEL):
        self.pad = pad
        self._mtime = None
        self.lijst: list[dict] = []
        self.ververs()

    def ververs(self) -> bool:
        try:
            m = self.pad.stat().st_mtime
        except OSError:
            return False
        if m == self._mtime:
            return False
        try:
            self.lijst = json.loads(self.pad.read_text(encoding="utf-8")).get("formulieren", [])
            self._mtime = m
            return True
        except (OSError, json.JSONDecodeError):
            return False

    def overzicht(self) -> list[dict]:
        return [{"id": f["id"], "naam": f.get("naam", f["titel"]), "titel": f["titel"]} for f in self.lijst]

    def get(self, fid: str) -> dict | None:
        return next((f for f in self.lijst if f["id"] == fid), None)

    def teksten(self) -> dict[str, str]:
        """Voor het rechtzetten van voorgelezen tekst: naam -> hele tekst."""
        return {f"Formulier {f.get('naam', f['titel'])}": " ".join(f["alineas"]) for f in self.lijst}


if __name__ == "__main__":
    sys.exit(ophalen())
