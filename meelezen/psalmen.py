"""Het psalmboek (berijming 1773) met de Enige Gezangen.

Bestand: data/psalmen.json
  {"bron": "...",
   "psalmen":  {"23": {"1": "regel\\nregel\\n...", "2": "..."}, ...},
   "gezangen": [{"titel": "Lofzang van Maria", "verzen": {"1": "..."}}, ...]}

Ophalen: python -m meelezen.psalmen  (of psalmen-ophalen.bat)
De berijming van 1773 is vrij van auteursrecht.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import unicodedata
import urllib.request
from pathlib import Path

from .config import BASIS

DOEL = BASIS / "data" / "psalmen.json"
# Bron: het open-source programma Stream & Beam (HHG Tholen); psalmen "zoals de gemeente zingt",
# gecontroleerd tegen een tweede bron.
GITHUB_REPO = "RichardLindhout/streamandbeam"


def _plat(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", s) + " "


class Psalmboek:
    def __init__(self, pad: Path = DOEL):
        self.pad = pad
        self._mtime = None
        self.psalmen: dict[str, dict[str, str]] = {}
        self.gezangen: list[dict] = []
        self.ververs()

    def ververs(self):
        """Opnieuw inlezen als het bestand nieuw of gewijzigd is (geen herstart nodig)."""
        try:
            mtime = self.pad.stat().st_mtime
        except OSError:
            return
        if mtime == self._mtime:
            return
        try:
            d = json.loads(self.pad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self._mtime = mtime
        psalmen = {k: v for k, v in d.get("psalmen", {}).items() if str(k).isdigit()}
        gezangen = list(d.get("gezangen", []))
        # sommige bronnen nummeren de Enige Gezangen door als 151, 152, ...
        extra = sorted((int(k) for k in psalmen if int(k) > 150))
        if extra and not gezangen:
            for i, k in enumerate(extra, 1):
                verzen = psalmen[str(k)]
                eerste = next(iter(verzen.values()), "").split("\n")[0].rstrip(" ,;:")
                gezangen.append({"titel": f"Gezang {i}: {eerste}" if eerste else f"Gezang {i}", "verzen": verzen})
        for k in extra:
            psalmen.pop(str(k), None)
        self.psalmen, self.gezangen = psalmen, gezangen

    @property
    def aan(self) -> bool:
        return bool(self.psalmen)

    def overzicht(self) -> dict:
        return {"psalmen": [{"nr": int(n), "verzen": len(v)} for n, v in sorted(self.psalmen.items(), key=lambda x: int(x[0]))],
                "gezangen": [{"nr": i + 1, "titel": g.get("titel", f"Gezang {i + 1}"), "verzen": len(g.get("verzen", {}))}
                             for i, g in enumerate(self.gezangen)]}

    def psalm(self, nr: int) -> dict | None:
        verzen = self.psalmen.get(str(nr))
        if not verzen:
            return None
        return {"titel": f"Psalm {nr}", "nr": nr,
                "verzen": [{"nr": int(v), "tekst": t} for v, t in sorted(verzen.items(), key=lambda x: int(x[0]))]}

    def gezang(self, nr: int) -> dict | None:
        if not 1 <= nr <= len(self.gezangen):
            return None
        g = self.gezangen[nr - 1]
        return {"titel": g.get("titel", f"Gezang {nr}"), "nr": nr, "gezang": True,
                "verzen": [{"nr": int(v), "tekst": t} for v, t in sorted(g.get("verzen", {}).items(), key=lambda x: int(x[0]))]}

    def ontleed(self, tekst: str) -> tuple[int, list[int]] | None:
        """'Psalm 42 : 1 en 5' / 'ps 119:1-3' / 'psalm 23' -> (42, [1, 5])."""
        m = re.match(r"^\s*(?:psalm|ps\.?)\s*(\d{1,3})(?:\s*[:,]\s*|\s+vers(?:en)?\s+|\s+)?(.*)$", tekst, re.I)
        if not m or str(int(m.group(1))) not in self.psalmen:
            return None
        nr, rest = int(m.group(1)), m.group(2)
        verzen: list[int] = []
        for a, b in re.findall(r"(\d+)(?:\s*(?:-|–|t/m|tot en met)\s*(\d+))?", rest or ""):
            a, b = int(a), int(b or a)
            verzen += list(range(a, min(b, a + 100) + 1))
        bestaand = self.psalmen[str(nr)]
        return nr, [v for v in dict.fromkeys(verzen) if str(v) in bestaand]

    def zoek(self, vraag: str, max_aantal: int = 60) -> tuple[list[dict], bool]:
        woorden = [w for w in _plat(vraag).split() if w]
        if not woorden:
            return [], False
        uit = []
        bronnen = [("psalm", int(n), v) for n, vs in self.psalmen.items() for v in vs] + \
                  [("gezang", i + 1, v) for i, g in enumerate(self.gezangen) for v in g.get("verzen", {})]
        for soort, nr, v in sorted(bronnen, key=lambda x: (x[0] != "psalm", x[1], int(x[2]))):
            tekst = self.psalmen[str(nr)][v] if soort == "psalm" else self.gezangen[nr - 1]["verzen"][v]
            if all(w in _plat(tekst) for w in woorden):
                if len(uit) >= max_aantal:
                    return uit, True
                titel = f"Psalm {nr}" if soort == "psalm" else self.gezangen[nr - 1].get("titel", f"Gezang {nr}")
                uit.append({"soort": soort, "nr": nr, "v": int(v), "titel": titel, "tekst": tekst})
        return uit, False


# ======================================================================== ophalen en omzetten
def _haal(url: str, binair=False):
    req = urllib.request.Request(url, headers={"User-Agent": "Meelezen/1.0 (kerk-app)",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    return data if binair else data.decode("utf-8", "replace")


def _schoon_vers(tekst) -> str:
    if isinstance(tekst, list):
        tekst = "\n".join(str(x) for x in tekst)
    tekst = re.sub(r"<br\s*/?>", "\n", str(tekst))
    tekst = re.sub(r"<[^>]+>", "", tekst)
    regels = [re.sub(r"[ \t]+", " ", r).strip() for r in tekst.replace("\r", "").split("\n")]
    return "\n".join(r for r in regels if r)


NUMMER_VELDEN = ("psalm", "psalmnummer", "nummer", "number", "nr", "num", "n", "id", "chapter", "hoofdstuk")
VERS_VELDEN = ("vers", "verse", "couplet", "stanza", "versnummer", "v")
TEKST_VELDEN = ("tekst", "text", "lines", "regels", "content", "inhoud", "body", "lyrics")
TITEL_VELDEN = ("titel", "title", "naam", "name")


def _omzetten_json(d) -> tuple[dict, list]:
    """Probeert uit (vrijwel) elke JSON-opbouw psalmen en gezangen te halen."""
    psalmen: dict[str, dict[str, str]] = {}
    gezangen: list[dict] = []

    def is_tekst(x):
        return (isinstance(x, str) and len(x) > 15) or (isinstance(x, list) and x and all(isinstance(i, str) for i in x))

    def verzen_uit(obj) -> dict[str, str]:
        """obj is een verzameling verzen (dict of lijst)."""
        uit = {}
        items = obj.items() if isinstance(obj, dict) else enumerate(obj, 1)
        for k, v in items:
            nr = None
            tekst = None
            if is_tekst(v):
                tekst = v
                nr = int(k) if str(k).isdigit() else None
            elif isinstance(v, dict):
                for f in VERS_VELDEN + NUMMER_VELDEN:
                    if str(v.get(f, "")).isdigit():
                        nr = int(v[f])
                        break
                if nr is None and str(k).isdigit():
                    nr = int(k)
                for f in TEKST_VELDEN:
                    if is_tekst(v.get(f)):
                        tekst = v[f]
                        break
            if nr is not None and tekst is not None:
                uit[str(nr)] = _schoon_vers(tekst)
        return uit

    def lied_uit(k, v):
        """Een psalm of gezang: geeft (nummer|None, titel|None, verzen)."""
        nr, titel, verzen = None, None, {}
        if str(k).isdigit():
            nr = int(k)
        if isinstance(v, dict):
            for f in NUMMER_VELDEN:
                if str(v.get(f, "")).isdigit():
                    nr = int(v[f])
                    break
            for f in TITEL_VELDEN:
                if isinstance(v.get(f), str):
                    titel = v[f]
                    break
            for f in ("verzen", "verses", "coupletten", "stanzas", "vers", "verse"):
                if isinstance(v.get(f), (dict, list)):
                    verzen = verzen_uit(v[f])
                    break
            if not verzen:
                verzen = verzen_uit({kk: vv for kk, vv in v.items() if str(kk).isdigit()})
        elif isinstance(v, list):
            verzen = verzen_uit(v)
        return nr, titel, verzen

    # platte lijst van regels {psalm, vers, tekst}
    if isinstance(d, list) and d and isinstance(d[0], dict) and any(f in d[0] for f in VERS_VELDEN):
        for r in d:
            p = next((r[f] for f in ("psalm", "psalmnummer", "nummer", "nr", "chapter") if str(r.get(f, "")).isdigit()), None)
            v = next((r[f] for f in VERS_VELDEN if str(r.get(f, "")).isdigit()), None)
            t = next((r[f] for f in TEKST_VELDEN if is_tekst(r.get(f))), None)
            if p and v and t:
                psalmen.setdefault(str(int(p)), {})[str(int(v))] = _schoon_vers(t)
        return psalmen, gezangen

    def zoek_verzameling(obj, diepte=0):
        """Zoek een dict/lijst met ~150 psalmen; daarnaast een met gezangen."""
        nonlocal psalmen, gezangen
        if diepte > 4:
            return
        if isinstance(obj, dict):
            sleutels = {str(k).lower(): k for k in obj}
            for naam in ("psalmen", "psalms", "psalm"):
                if naam in sleutels and not psalmen:
                    zoek_lijst(obj[sleutels[naam]], "psalm")
            for naam in ("gezangen", "enige gezangen", "enigegezangen", "hymns", "liederen"):
                if naam in sleutels and not gezangen:
                    zoek_lijst(obj[sleutels[naam]], "gezang")
            if not psalmen and sum(str(k).isdigit() for k in obj) >= 140:
                zoek_lijst(obj, "psalm")
            for v in obj.values():
                if isinstance(v, (dict, list)) and not psalmen:
                    zoek_verzameling(v, diepte + 1)
        elif isinstance(obj, list) and len(obj) >= 140 and not psalmen:
            zoek_lijst(obj, "psalm")

    def zoek_lijst(obj, soort):
        items = obj.items() if isinstance(obj, dict) else enumerate(obj, 1)
        for k, v in items:
            nr, titel, verzen = lied_uit(k, v)
            if not verzen:
                continue
            if soort == "psalm" and nr:
                psalmen[str(nr)] = verzen
            elif soort == "gezang":
                gezangen.append({"titel": titel or f"Gezang {nr or len(gezangen) + 1}", "verzen": verzen})

    zoek_verzameling(d)
    return psalmen, gezangen


def _omzetten_tekst(t: str) -> tuple[dict, list]:
    """Platte tekst met kopjes 'Psalm 23' en verzen die met een nummer beginnen."""
    psalmen: dict[str, dict[str, str]] = {}
    huidig, vers, regels = None, None, []

    def bewaar():
        if huidig and vers and regels:
            psalmen.setdefault(str(huidig), {})[str(vers)] = _schoon_vers(regels)

    for r in t.replace("\r", "").split("\n"):
        kop = re.match(r"^\s*psalm\s+(\d{1,3})\s*$", r, re.I)
        if kop:
            bewaar()
            huidig, vers, regels = int(kop.group(1)), None, []
            continue
        v = re.match(r"^\s*(\d{1,2})[.)]?\s+(\S.*)$", r)
        if huidig and v:
            bewaar()
            vers, regels = int(v.group(1)), [v.group(2)]
        elif huidig and vers and r.strip():
            regels.append(r.strip())
    bewaar()
    return psalmen, []


def controle(psalmen: dict, gezangen: list) -> list[str]:
    fouten = []
    ontbreekt = [n for n in range(1, 151) if str(n) not in psalmen or not psalmen[str(n)]]
    if ontbreekt:
        fouten.append(f"{len(ontbreekt)} psalmen ontbreken (bijv. {', '.join(map(str, ontbreekt[:8]))})")
    if len(psalmen.get("119", {})) < 80:
        fouten.append(f"Psalm 119 heeft {len(psalmen.get('119', {}))} verzen (verwacht 88)")
    return fouten


def ophalen_github() -> tuple[dict, list, str]:
    """Zoekt in de map assets/data van Stream & Beam naar het psalmenbestand."""
    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/assets/data"
    lijst = json.loads(_haal(api))
    kandidaten = [f for f in lijst if f.get("type") == "file" and re.search(r"psalm|1773", f["name"], re.I)]
    kandidaten.sort(key=lambda f: (not f["name"].lower().endswith(".json"), f["name"]))
    if not kandidaten:
        raise RuntimeError("geen psalmenbestand gevonden; bestanden: " + ", ".join(f["name"] for f in lijst))
    gezangen_bestand = [f for f in lijst if f.get("type") == "file" and re.search(r"gezang", f["name"], re.I)]
    for f in kandidaten:
        print(f"  {f['name']} ({f.get('size', 0) // 1024} kB) proberen…")
        tekst = _haal(f["download_url"])
        try:
            psalmen, gezangen = _omzetten_json(json.loads(tekst))
        except json.JSONDecodeError:
            psalmen, gezangen = _omzetten_tekst(tekst)
        if not controle(psalmen, gezangen):
            for g in gezangen_bestand:
                if not gezangen:
                    try:
                        _, gezangen = _omzetten_json({"gezangen": json.loads(_haal(g["download_url"]))})
                    except Exception:
                        pass
            return psalmen, gezangen, f"github.com/{GITHUB_REPO} – {f['name']}"
        print("   ", "; ".join(controle(psalmen, gezangen)))
    raise RuntimeError("geen bruikbaar psalmenbestand")


def opslaan(psalmen, gezangen, bron):
    extra = [k for k in psalmen if k.isdigit() and int(k) > 150]
    if extra and not gezangen:
        print(f"  Psalm 151 t/m {max(map(int, extra))} worden als Enige Gezangen getoond.")
    if DOEL.exists():
        shutil.copy(DOEL, DOEL.with_suffix(".json.bak"))
    DOEL.write_text(json.dumps({"bron": bron, "psalmen": psalmen, "gezangen": gezangen}, ensure_ascii=False), encoding="utf-8")
    verzen = sum(len(v) for v in psalmen.values())
    print(f"\nOpgeslagen in {DOEL}")
    print(f"  {len(psalmen)} psalmen, {verzen} verzen, {len(gezangen)} gezangen")
    if gezangen:
        print("  Gezangen:", ", ".join(g["titel"] for g in gezangen))
    print("  Controle Psalm 134:", " / ".join(psalmen.get("134", {}).get("1", "").split("\n")[:1]), "…")


def main():
    eigen = [a for a in sys.argv[1:] if not a.startswith("-")]
    if eigen:   # een eigen bestand omzetten
        pad = Path(eigen[0])
        tekst = pad.read_text(encoding="utf-8", errors="replace")
        try:
            psalmen, gezangen = _omzetten_json(json.loads(tekst))
        except json.JSONDecodeError:
            psalmen, gezangen = _omzetten_tekst(tekst)
        bron = pad.name
    else:
        print("Psalmen (berijming 1773) ophalen…")
        try:
            psalmen, gezangen, bron = ophalen_github()
        except Exception as e:
            print(f"\nOphalen mislukt: {e}")
            print("Stuur deze melding naar de maker van de app, of zet zelf een psalmenbestand neer en start:")
            print("  psalmen-ophalen.bat pad\\naar\\psalmen.json   (of .txt)")
            sys.exit(1)
    fouten = controle(psalmen, gezangen)
    if fouten:
        print("\nHet psalmboek is onvolledig; data/psalmen.json is NIET vervangen:")
        for f in fouten:
            print("  -", f)
        sys.exit(1)
    opslaan(psalmen, gezangen, bron)


if __name__ == "__main__":
    main()
