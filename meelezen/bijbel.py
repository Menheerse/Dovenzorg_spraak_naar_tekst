"""Bijbel bij de dienst: lezingen en liederen uit data/dienst.json.

Bijbeltekst kan direct in dienst.json staan, of wordt opgezocht in data/bijbel.json
(formaat: {"Johannes": {"3": {"16": "Want alzo lief ..."}}}).
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

log = logging.getLogger("meelezen.bijbel")

AFKORTINGEN = {"ps": "psalmen", "psalm": "psalmen", "gen": "genesis", "ex": "exodus", "lev": "leviticus",
               "num": "numeri", "deut": "deuteronomium", "dt": "deuteronomium", "joz": "jozua",
               "richt": "richteren", "re": "richteren", "sam": "samuel", "kon": "koningen",
               "kron": "kronieken", "spr": "spreuken", "pred": "prediker", "hgl": "hooglied",
               "jes": "jesaja", "jer": "jeremia", "klgl": "klaagliederen", "ez": "ezechiel",
               "dan": "daniel", "mat": "mattheus", "matt": "mattheus", "matteus": "mattheus",
               "mark": "markus", "marcus": "markus", "luc": "lukas", "lucas": "lukas",
               "joh": "johannes", "hand": "handelingen", "rom": "romeinen", "kor": "korinthe",
               "korintiers": "korinthe", "korinthiers": "korinthe", "gal": "galaten", "ef": "efeze",
               "efeziers": "efeze", "fil": "filippenzen", "kol": "kolossenzen", "kolossenzen": "kolossenzen",
               "thess": "thessalonicenzen", "tess": "thessalonicenzen", "tessalonicenzen": "thessalonicenzen",
               "tim": "timotheus", "hebr": "hebreeen", "heb": "hebreeen", "jak": "jakobus", "petr": "petrus",
               "pet": "petrus", "op": "openbaring", "openb": "openbaring"}

VERWIJZING = re.compile(r"^\s*((?:[1-3]\s*)?[^\d:]+?)\.?\s+(\d+)(?:\s*:\s*([\d\s,\-–a-z]+))?\s*$", re.I)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def _plat_tekst(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", s) + " "


def _verzen(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    uit: list[int] = []
    for deel in re.split(r"\s*,\s*", spec.strip()):
        deel = re.sub(r"[a-z]", "", deel)
        if not deel:
            continue
        if re.search(r"[-–]", deel):
            a, b = re.split(r"\s*[-–]\s*", deel)[:2]
            uit += list(range(int(a), int(b) + 1))
        else:
            uit.append(int(deel))
    return uit


class Bijbel:
    def __init__(self, pad: Path):
        self.gevraagd = pad
        self.pad = pad
        self.data: dict = {}
        self.boeken: dict[str, str] = {}
        self._mtime = None
        self.ververs()

    def ververs(self) -> bool:
        """(Opnieuw) inlezen als het bestand nieuw of gewijzigd is. Geeft True bij een wijziging."""
        pad = self.gevraagd
        if not pad.exists() and pad.name == "bijbel.json":
            pad = pad.with_name("bijbel.voorbeeld.json")   # nog niet opgehaald: het kleine voorbeeld
        try:
            mtime = (pad, pad.stat().st_mtime)
        except OSError:
            return False
        if mtime == self._mtime:
            return False
        try:
            data = json.loads(pad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.error("bijbel kon niet worden gelezen: %s", e)
            return False
        self.pad, self._mtime, self.data = pad, mtime, data
        self.boeken = {_norm(b): b for b in data}
        if hasattr(self, "_plat"):
            del self._plat
        log.info("bijbel geladen: %d boeken (%s)", len(data), pad.name)
        return True

    def _boek(self, naam: str) -> str | None:
        m = re.match(r"^([1-3])\s*(.+)$", naam.strip())
        nr, rest = (m.group(1), m.group(2)) if m else ("", naam)
        ruw = _norm(rest)
        for sleutel in (AFKORTINGEN.get(ruw), ruw):
            if not sleutel:
                continue
            kandidaten = [echt for n, echt in self.boeken.items()
                          if n.lstrip("123").startswith(sleutel) and n.startswith(nr)]
            if kandidaten:
                return min(kandidaten, key=len)
        return None

    def ontleed(self, verwijzing: str) -> tuple[str, int, list[int]] | None:
        """'Joh 3:16-18' -> ('Johannes', 3, [16, 17, 18]); 'Psalm 23' -> ('Psalmen', 23, [])."""
        m = VERWIJZING.match(verwijzing)
        if not (m and self.data):
            return None
        boek = self._boek(m.group(1))
        if not boek or m.group(2) not in self.data[boek]:
            return None
        hoofdstuk = self.data[boek][m.group(2)]
        verzen = [v for v in (_verzen(m.group(3)) or []) if str(v) in hoofdstuk]
        return boek, int(m.group(2)), verzen

    def zoek(self, verwijzing: str) -> list[dict] | None:
        r = self.ontleed(verwijzing)
        if not r:
            return None
        boek, h, verzen = r
        hoofdstuk = self.data[boek][str(h)]
        nummers = verzen or sorted(int(v) for v in hoofdstuk)
        return [{"nr": n, "tekst": hoofdstuk[str(n)]} for n in nummers if str(n) in hoofdstuk]

    def boekenlijst(self) -> list[dict]:
        namen = list(self.data)
        nt = next((i for i, b in enumerate(namen) if _norm(b).startswith(("matth", "matte"))), None)
        if nt is None:  # onvolledige bijbel: op naam bepalen
            nt_namen = ("johannes", "1johannes", "2johannes", "3johannes", "markus", "lukas", "handelingen",
                        "romeinen", "1korinthe", "2korinthe", "galaten", "efeze", "filippenzen", "kolossenzen",
                        "hebreeen", "jakobus", "1petrus", "2petrus", "judas", "openbaring")
            return [{"naam": b, "hoofdstukken": len(self.data[b]), "nt": _norm(b).startswith(nt_namen)} for b in namen]
        return [{"naam": b, "hoofdstukken": len(self.data[b]), "nt": i >= nt} for i, b in enumerate(namen)]

    def tekst_zoeken(self, vraag: str, max_aantal: int = 100) -> tuple[list[dict], bool]:
        """Alle verzen met alle woorden uit de vraag (zonder hoofdletters/accenten)."""
        if not hasattr(self, "_plat"):
            self._plat = [(b, h, v, _plat_tekst(t), t) for b, hs in self.data.items()
                          for h, vs in hs.items() for v, t in vs.items()]
        woorden = [w for w in _plat_tekst(vraag).split() if w]
        if not woorden:
            return [], False
        uit = []
        for b, h, v, plat, tekst in self._plat:
            if all(w in plat for w in woorden):
                if len(uit) >= max_aantal:
                    return uit, True
                uit.append({"boek": b, "h": int(h), "v": int(v), "tekst": tekst})
        return uit, False


class Dienst:
    """Leest data/dienst.json; wijzigingen worden direct opgepikt."""

    def __init__(self, map_: Path, kerk_id: str | None = None, bijbel: "Bijbel | None" = None):
        eigen = map_ / f"dienst-{kerk_id}.json" if kerk_id else None
        self.pad = eigen if eigen and eigen.exists() else map_ / "dienst.json"
        self._eigen = eigen
        self.bijbel = bijbel or Bijbel(map_ / "bijbel.json")
        self.psalmboek = None   # door de server gezet
        self._mtime = None
        self._cache: dict = {}

    def get(self) -> dict:
        if self._eigen and self._eigen.exists() and self.pad != self._eigen:
            self.pad, self._mtime = self._eigen, None   # eigen bestand later aangemaakt
        try:
            mtime = self.pad.stat().st_mtime
        except FileNotFoundError:
            return {"onderdelen": []}
        if mtime != self._mtime:
            try:
                d = json.loads(self.pad.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                log.error("dienst.json bevat een fout: %s", e)
                return self._cache or {"onderdelen": [], "fout": f"dienst.json bevat een fout: {e}"}
            for o in d.get("onderdelen", []):
                if o.get("soort", "lezing") == "lezing" and not o.get("verzen") and not o.get("tekst"):
                    gevonden = self.bijbel.zoek(o.get("verwijzing", ""))
                    if gevonden:
                        o["verzen"] = gevonden
                elif o.get("soort") == "lied" and not o.get("tekst") and self.psalmboek:
                    ps = self.psalmboek.ontleed(o.get("verwijzing") or o.get("titel", ""))
                    if ps:   # tekst uit het psalmboek invullen
                        nr, verzen = ps
                        alle = self.psalmboek.psalm(nr)["verzen"]
                        o["liedverzen"] = [v for v in alle if not verzen or v["nr"] in verzen]
            self._cache, self._mtime = d, mtime
        return self._cache
