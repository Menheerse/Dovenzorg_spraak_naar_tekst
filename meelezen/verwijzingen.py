"""Bijbelverwijzingen en -citaten herkennen in uitgeschreven preektekst.

1. Genoemde verwijzingen: "Johannes 10 vers 11", "Psalm drieëntwintig", "in de eerste brief aan de
   Korinthiërs, hoofdstuk 13", "Romeinen 8:28".
2. Citaten: een stuk tekst dat (bijna) letterlijk uit de Statenvertaling komt, ook als de bron
   niet genoemd wordt. Daarvoor is er een index van woordreeksen van 5 woorden.
"""
from __future__ import annotations

import logging
import re
import unicodedata
import zlib
from collections import Counter

import numpy as np

log = logging.getLogger("meelezen.verwijzingen")

# ---------------------------------------------------------------- getallen in woorden
_EEN = ["", "een", "twee", "drie", "vier", "vijf", "zes", "zeven", "acht", "negen"]
_TIEN = ["tien", "elf", "twaalf", "dertien", "veertien", "vijftien", "zestien", "zeventien", "achttien", "negentien"]
_TIENTAL = {2: "twintig", 3: "dertig", 4: "veertig", 5: "vijftig", 6: "zestig", 7: "zeventig", 8: "tachtig", 9: "negentig"}


def _woord(n: int) -> str:
    if n >= 100:
        return "honderd" + (_woord(n - 100) if n > 100 else "")
    if n < 10:
        return _EEN[n]
    if n < 20:
        return _TIEN[n - 10]
    t, e = divmod(n, 10)
    if not e:
        return _TIENTAL[t]
    voeg = "en" if not _EEN[e].endswith("e") else "en"  # 'tweeen' -> na normalisatie gelijk aan 'tweeën'
    return _EEN[e] + voeg + _TIENTAL[t]


GETALWOORDEN = {_woord(n): n for n in range(1, 177)}
GETALWOORDEN.update({"eerste": 1})  # 'het eerste vers'
_GETAL = r"(?:\d{1,3}|" + "|".join(sorted((re.escape(w) for w in GETALWOORDEN if w != "eerste"), key=len, reverse=True)) + r")"


def getal(s: str) -> int | None:
    s = s.strip()
    if s.isdigit():
        return int(s)
    return GETALWOORDEN.get(s)


# ---------------------------------------------------------------- boeknamen
EXTRA = {  # gesproken / alternatieve vormen  -> genormaliseerde basisnaam zoals in de bijbel
    "psalmen": ["psalm", "psalmen", "ps"],
    "mattheus": ["mattheus", "matteus", "matthéüs"],
    "markus": ["markus", "marcus"],
    "lukas": ["lukas", "lucas"],
    "handelingen": ["handelingen der apostelen", "handelingen van de apostelen", "handelingen"],
    "korinthe": ["korinthe", "korinthiers", "korintiers", "korinte", "corinthiers", "brief aan de korinthiers",
                 "brief aan de korintiers", "brief aan korinthe"],
    "efeze": ["efeze", "efeziers", "brief aan de efeziers"],
    "filippenzen": ["filippenzen", "filippensen", "filippiers", "brief aan de filippenzen"],
    "kolossenzen": ["kolossenzen", "kolossensen", "kolossers", "brief aan de kolossenzen"],
    "thessalonicenzen": ["thessalonicenzen", "tessalonicenzen", "thessalonicensen", "brief aan de thessalonicenzen"],
    "timotheus": ["timotheus", "brief aan timotheus"],
    "hebreeen": ["hebreeen", "hebreeers", "brief aan de hebreeen"],
    "romeinen": ["romeinen", "brief aan de romeinen"],
    "galaten": ["galaten", "brief aan de galaten"],
    "openbaring": ["openbaring", "openbaringen", "openbaring van johannes"],
    "prediker": ["prediker"], "spreuken": ["spreuken"], "hooglied": ["hooglied"],
    "klaagliederen": ["klaagliederen"],
}
RANGTELWOORD = {"1": ["1", "eerste", "1e", "i"], "2": ["2", "tweede", "2e", "ii"], "3": ["3", "derde", "3e", "iii"]}
# boeken die ook een gewone voornaam zijn: alleen herkennen met 'vers' of ':' erbij, of met cijfers
NAMEN = {"johannes", "petrus", "jakobus", "judas", "daniel", "samuel", "ruth", "ester", "esther", "job",
         "jona", "amos", "titus", "filemon", "timotheus", "micha", "joel", "nahum", "ezra", "nehemia"}


def _plat(s: str) -> str:
    """Kleine letters zonder accenten, met dezelfde lengte als de invoer (voor posities)."""
    uit = []
    for c in s:
        b = unicodedata.normalize("NFKD", c)[:1] or c
        uit.append(b.lower() if b.isascii() else c.lower())
    return "".join(uit)


def _sleutel(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", _plat(s)).strip()


class Verwijzer:
    def __init__(self, bijbel_data: dict):
        self.data = bijbel_data
        self.vorm_naar_boek: dict[str, str] = {}
        for boek in bijbel_data:
            m = re.match(r"^([1-3])\s*(.+)$", boek)
            nr, basis = (m.group(1), m.group(2)) if m else ("", boek)
            bsleutel = _sleutel(basis).replace(" ", "")
            vormen = {_sleutel(basis)}
            for k, lijst in EXTRA.items():
                if (bsleutel.startswith(k) or k.startswith(bsleutel)
                        or any(_sleutel(v).replace(" ", "") == bsleutel for v in lijst)):
                    vormen.update(_sleutel(v) for v in lijst)
            for v in vormen:
                if nr:
                    for r in RANGTELWOORD[nr]:
                        self.vorm_naar_boek.setdefault(f"{r} {v}", boek)
                        self.vorm_naar_boek.setdefault(f"de {r} {v}", boek)
                else:
                    self.vorm_naar_boek.setdefault(v, boek)
        # boeken die alleen genummerd bestaan (1/2 Samuel...) zonder nummer: eerste nemen
        for boek in bijbel_data:
            m = re.match(r"^1\s*(.+)$", boek)
            if m:
                self.vorm_naar_boek.setdefault(_sleutel(m.group(1)), boek)
        vormen = sorted(self.vorm_naar_boek, key=len, reverse=True)
        boeken = "|".join(re.escape(v).replace(r"\ ", r"\s+") for v in vormen)
        self.patroon = re.compile(
            r"(?<![\w])(?P<boek>" + boeken + r")[\s,]+(?:hoofdstuk\s+)?(?P<h>" + _GETAL + r")(?![\w])"
            r"(?:(?:\s*:\s*|[\s,]+(?:en\s+)?(?:in\s+)?(?:het\s+)?(?:vers|verzen|vs\.?)\s+)(?P<v1>" + _GETAL + r")"
            r"(?:\s*(?P<sep>-|–|tot\s+en\s+met|t/m|tot|en)\s*(?P<v2>" + _GETAL + r"))?)?(?![\w])",
            re.I)
        self._citaat_index()

    # ------------------------------------------------------------ genoemde verwijzingen
    def genoemd(self, tekst: str) -> list[dict]:
        plat = _plat(tekst)
        uit = []
        for m in self.patroon.finditer(plat):
            vorm = re.sub(r"\s+", " ", m.group("boek"))
            boek = self.vorm_naar_boek.get(vorm)
            h, v1, v2 = getal(m.group("h")), m.group("v1"), m.group("v2")
            if not boek or not h:
                continue
            if vorm in NAMEN and not v1 and not m.group("h").isdigit():
                continue  # 'Johannes twee keer' is geen verwijzing
            hoofdstuk = self.data[boek].get(str(h))
            if not hoofdstuk:
                continue
            verzen = []
            if v1:
                a = getal(v1)
                b = getal(v2) if v2 else a
                if a and b and m.group("sep") == "en":
                    verzen = [v for v in (a, b) if str(v) in hoofdstuk]
                elif a and b and b >= a and b - a < 60:
                    verzen = [v for v in range(a, b + 1) if str(v) in hoofdstuk]
                elif a and str(a) in hoofdstuk:
                    verzen = [a]
            ref = self._ref(boek, h, verzen, m.start(), m.end(), "genoemd")
            if _plat(boek).startswith("psalm") and re.search(r"\b(zing\w*|gezongen)\b[^.!?]{0,40}$", plat[:m.start()]):
                ref["zingen"] = True   # 'we zingen Psalm 42 vers 5': de berijming tonen
            uit.append(ref)
        return uit

    @staticmethod
    def _ref(boek, h, verzen, van, tot, soort):
        label = f"{boek} {h}"
        if verzen:
            aaneen = verzen == list(range(verzen[0], verzen[-1] + 1))
            label += f":{verzen[0]}" + ((f"-{verzen[-1]}" if aaneen else "," + ",".join(map(str, verzen[1:]))) if len(verzen) > 1 else "")
        return {"label": label, "boek": boek, "h": h, "v": verzen, "van": van, "tot": tot, "soort": soort}

    # ------------------------------------------------------------ citaten
    @staticmethod
    def _woorden(tekst: str) -> list[tuple[str, int, int]]:
        plat = _plat(tekst)
        return [(m.group(0), m.start(), m.end()) for m in re.finditer(r"[a-z0-9]+", plat)]

    @staticmethod
    def _hash(ws) -> int:
        return zlib.crc32(" ".join(ws).encode())

    def _citaat_index(self, n=5):
        self.n = n
        self.verzen: list[tuple[str, int, int]] = []
        hashes, ids = [], []
        for boek, hs in self.data.items():
            for h, vs in hs.items():
                for v, tekst in vs.items():
                    vid = len(self.verzen)
                    self.verzen.append((boek, int(h), int(v)))
                    w = [x[0] for x in self._woorden(tekst)]
                    for i in range(len(w) - n + 1):
                        hashes.append(self._hash(w[i:i + n]))
                        ids.append(vid)
        if not hashes:
            self.h = np.zeros(0, np.uint32)
            self.ids = np.zeros(0, np.int32)
            return
        h = np.array(hashes, dtype=np.uint32)
        ids = np.array(ids, dtype=np.int32)
        uniek, terug, aantal = np.unique(h, return_inverse=True, return_counts=True)
        # veelvoorkomende reeksen ('en het geschiedde als hij') zeggen niets: weglaten
        bruikbaar = aantal[terug] <= 3
        volgorde = np.argsort(h[bruikbaar], kind="stable")
        self.h, self.ids = h[bruikbaar][volgorde], ids[bruikbaar][volgorde]
        log.info("citaat-index: %d woordreeksen", len(self.h))

    def geciteerd(self, tekst: str, min_reeksen: int = 2, recent: set | None = None) -> list[dict]:
        """Citaten herkennen. recent: hoofdstukken (boek, h) die net zijn genoemd of geciteerd;
        daar ligt een citaat veel eerder. Een kort stukje dat ook elders in de Bijbel past, wordt
        alleen gekoppeld als het in zo'n hoofdstuk staat (anders te onzeker)."""
        recent = recent or set()
        w = self._woorden(tekst)
        if len(w) < self.n + min_reeksen - 1 or not len(self.h):
            return []
        treffers: dict[int, list[int]] = {}
        for i in range(len(w) - self.n + 1):
            hh = self._hash([x[0] for x in w[i:i + self.n]])
            a = np.searchsorted(self.h, hh)
            b = a
            while b < len(self.h) and self.h[b] == hh:
                treffers.setdefault(int(self.ids[b]), []).append(i)
                b += 1
        uit = []
        nw = len(w)

        def volgorde(x):
            b, h_, _ = self.verzen[x[0]]
            return (-len(set(x[1])), (b, h_) not in recent, x[0])
        for vid, posities in sorted(treffers.items(), key=volgorde):
            aantal = len(set(posities))
            if aantal < min_reeksen:
                continue
            boek, h, v = self.verzen[vid]
            if (boek, h) not in recent:
                dekking = (max(posities) + self.n - min(posities)) / nw
                if (aantal < 3 and nw < 12) or dekking < 0.5:
                    continue   # kort of maar half: in een ander hoofdstuk te onzeker
            van, tot = w[min(posities)][1], w[max(posities) + self.n - 1][2]
            if any(not (tot <= r["van"] or van >= r["tot"]) for r in uit):
                continue  # overlapt met een al gevonden citaat
            uit.append(self._ref(boek, h, [v], van, tot, "citaat"))
        # aangrenzende verzen uit hetzelfde hoofdstuk samenvoegen
        uit.sort(key=lambda r: r["van"])
        samen: list[dict] = []
        for r in uit:
            p = samen[-1] if samen else None
            if p and p["boek"] == r["boek"] and p["h"] == r["h"] and r["v"][0] == p["v"][-1] + 1:
                samen[-1] = self._ref(p["boek"], p["h"], p["v"] + r["v"], p["van"], r["tot"], "citaat")
            else:
                samen.append(r)
        return samen

    def vind(self, tekst: str, recent: set | None = None) -> list[dict]:
        refs = self.genoemd(tekst)
        recent = set(recent or ()) | {(r["boek"], r["h"]) for r in refs}
        for c in self.geciteerd(tekst, recent=recent):
            if not any(not (c["tot"] <= r["van"] or c["van"] >= r["tot"]) for r in refs):
                refs.append(c)
        return sorted(refs, key=lambda r: r["van"])
