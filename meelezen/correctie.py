"""Vaste teksten rechtzetten.

Whisper verstaat voorgelezen teksten niet altijd goed ('gedachten is', 'nog' i.p.v. 'noch',
'ons schuldig' i.p.v. 'onschuldig'). Bij een tekst die letterlijk wordt voorgelezen is de goede
tekst bekend: de Statenvertaling, de berijmde psalmen, de Twaalf Artikelen, het Onze Vader, het
votum en de formulieren. Herkent de app zo'n stuk, dan zet hij de officiële tekst neer.

Werkwijze (behoudend):
1. Elke bron wordt opgesplitst in woorden; van elke drie opeenvolgende woorden (in een
   'klankvorm', zodat 'Heeren'/'Heere' en 'zij'/'zei' gelijk zijn) wordt een index gemaakt.
2. Van een uitgesproken zin worden de drietallen opgezocht. Liggen genoeg treffers op één lijn
   in dezelfde bron, dan is dat het voorgelezen stuk.
3. Het stuk in de zin en in de bron wordt letter voor letter vergeleken. Alleen bij een zeer
   grote overeenkomst (standaard 82%) wordt het vervangen. Eigen woorden van de predikant
   ervoor of erna blijven staan.

Eigen teksten (formulieren, gebeden) kunnen in data/vaste-teksten/*.txt: één tekst per bestand,
gewone tekst. De app leest de map bij het starten.
"""
from __future__ import annotations

import logging
import re
import unicodedata
import zlib
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

log = logging.getLogger("meelezen.correctie")

# Kort en zeker: deze teksten liggen vast in de gereformeerde liturgie.
INGEBOUWD = {
    "Votum": "Onze hulp is in den Naam des HEEREN, Die hemel en aarde gemaakt heeft, Die trouw houdt "
             "tot in eeuwigheid, en niet laat varen de werken Zijner handen. Amen.",
    "Onze Vader": "Onze Vader, Die in de hemelen zijt! Uw Naam worde geheiligd; Uw Koninkrijk kome; "
                  "Uw wil geschiede, gelijk in den hemel alzo ook op de aarde. Geef ons heden ons "
                  "dagelijks brood; en vergeef ons onze schulden, gelijk ook wij vergeven onze "
                  "schuldenaren; en leid ons niet in verzoeking, maar verlos ons van den boze. Want Uw "
                  "is het Koninkrijk, en de kracht, en de heerlijkheid in der eeuwigheid. Amen.",
    "Twaalf Artikelen": "Ik geloof in God den Vader, den Almachtige, Schepper des hemels en der aarde. "
                        "En in Jezus Christus, Zijn eniggeboren Zoon, onzen Heere; Die ontvangen is van "
                        "den Heiligen Geest, geboren uit de maagd Maria; Die geleden heeft onder Pontius "
                        "Pilatus, is gekruisigd, gestorven en begraven, nedergedaald ter helle; ten "
                        "derden dage wederom opgestaan van de doden; opgevaren ten hemel, zittende ter "
                        "rechterhand Gods des almachtigen Vaders; van waar Hij komen zal om te oordelen "
                        "de levenden en de doden. Ik geloof in den Heiligen Geest. Ik geloof een heilige, "
                        "algemene, christelijke Kerk, de gemeenschap der heiligen; vergeving der zonden; "
                        "wederopstanding des vleses; en een eeuwig leven. Amen.",
}


def _plat(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def klank(woord: str) -> str:
    """Woord in een 'klankvorm', zodat kleine verschillen in uitspraak/spelling niet tellen."""
    w = re.sub(r"[^a-z0-9]", "", _plat(woord))
    if not w:
        return ""
    w = w.replace("ij", "y").replace("ei", "y").replace("ch", "g").replace("ph", "f").replace("dt", "t")
    w = re.sub(r"(.)\1+", r"\1", w)          # dubbele letters
    if len(w) > 3 and w.endswith("n"):      # den/de, Heeren/Heere, harten/harte
        w = w[:-1]
    if w.endswith("d"):
        w = w[:-1] + "t"
    return w


def _tokens(tekst: str) -> list[str]:
    return [t for t in tekst.split() if re.search(r"\w", t)]


class Corrector:
    def __init__(self, bijbel_data: dict | None = None, psalmen: dict | None = None,
                 extra: dict[str, str] | None = None, map_vast: Path | None = None, drempel: float = 0.82):
        self.drempel = drempel
        self.toon: list[str] = []     # woorden zoals ze in de bron staan
        self.kl: list[str] = []       # klankvorm
        self.bron: list[int] = []     # bronnummer per woord (een hoofdstuk, psalm of tekst)
        self.namen: list[str] = []
        self._klankcache: dict[str, str] = {}
        self.bijbelbronnen: set[str] = set()
        if bijbel_data:
            for boek, hs in bijbel_data.items():
                for h, vs in hs.items():
                    self._voeg_toe(f"{boek} {h}", " ".join(vs[v] for v in sorted(vs, key=int)))
                    self.bijbelbronnen.add(f"{boek} {h}")
        if psalmen:
            for nr, vs in psalmen.items():
                self._voeg_toe(f"Psalm {nr} (berijmd)",
                               " ".join(vs[v].replace("\n", " ") for v in sorted(vs, key=int)))
        for naam, tekst in {**INGEBOUWD, **(extra or {})}.items():
            self._voeg_toe(naam, tekst)
        if map_vast and map_vast.is_dir():
            for p in sorted(map_vast.glob("*.txt")):
                try:
                    self._voeg_toe(p.stem, p.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError) as e:
                    log.warning("vaste tekst %s niet te lezen: %s", p.name, e)
        self._index()

    def _voeg_toe(self, naam: str, tekst: str):
        nr = len(self.namen)
        self.namen.append(naam)
        cache = self._klankcache
        for t in _tokens(tekst):
            k = cache.get(t)
            if k is None:
                k = cache[t] = klank(t)
            self.toon.append(t)
            self.kl.append(k)
            self.bron.append(nr)

    @staticmethod
    def _h(a, b, c) -> int:
        return zlib.crc32(f"{a} {b} {c}".encode())

    def _index(self):
        kl, bron = self.kl, self.bron
        hs, pos = [], []
        for i in range(len(kl) - 2):
            if bron[i] == bron[i + 2]:
                hs.append(self._h(kl[i], kl[i + 1], kl[i + 2]))
                pos.append(i)
        if not hs:
            self.h = np.zeros(0, np.uint32)
            self.pos = np.zeros(0, np.int64)
            return
        h = np.array(hs, np.uint32)
        p = np.array(pos, np.int64)
        u, terug, n = np.unique(h, return_inverse=True, return_counts=True)
        goed = n[terug] <= 40          # 'en de HEERE' zegt niets
        volg = np.argsort(h[goed], kind="stable")
        self.h, self.pos = h[goed][volg], p[goed][volg]
        self.bron_np = np.array(self.bron, np.int32)
        log.info("vaste teksten: %d bronnen, %d woorden", len(self.namen), len(self.toon))

    def _beste_stuk(self, kl, z0, z1, basis, bron):
        doel = "".join(kl[z0:z1])
        lengte = z1 - z0
        beste = (0.0, 0, 0)
        for s in range(basis + z0 - 5, basis + z0 + 6):
            if s < 0 or s >= len(self.kl) or self.bron[s] != bron:
                continue
            for e in range(s + max(2, lengte - 6), s + lengte + 7):
                if e > len(self.kl) or self.bron[e - 1] != bron:
                    break
                r = SequenceMatcher(None, doel, "".join(self.kl[s:e]), autojunk=False).ratio()
                if r > beste[0]:
                    beste = (r, s, e)
        return beste

    # ------------------------------------------------------------------ zoeken
    def corrigeer(self, tekst: str) -> tuple[str, str | None]:
        """Geeft (tekst, bronnaam) terug; bronnaam None als de zin niet uit een bekende tekst komt."""
        woorden = tekst.split()
        if len(woorden) < 5 or not len(self.h):
            return tekst, None
        idx = [i for i, w in enumerate(woorden) if re.search(r"\w", w)]
        kl = [klank(woorden[i]) for i in idx]
        if len(kl) < 5:
            return tekst, None
        # treffers per 'diagonaal' (positie in bron min positie in zin)
        diag: dict[int, list[int]] = {}
        n3 = len(kl) - 2
        for j in range(n3):
            hh = self._h(kl[j], kl[j + 1], kl[j + 2])
            a = np.searchsorted(self.h, hh)
            b = a
            while b < len(self.h) and self.h[b] == hh:
                d = int(self.pos[b]) - j
                diag.setdefault(d // 4, []).append(j)   # een paar woorden speling
                b += 1
        if not diag:
            return tekst, None
        sleutel, js = max(diag.items(), key=lambda kv: len(set(kv[1])))
        js = sorted(set(js))
        if len(js) < max(3 if len(kl) < 10 else 2, int(0.3 * n3)):
            return tekst, None
        # de positie in de bron rond die diagonaal
        kandidaten = []
        for j in js:
            hh = self._h(kl[j], kl[j + 1], kl[j + 2])
            a = np.searchsorted(self.h, hh)
            b = a
            while b < len(self.h) and self.h[b] == hh:
                if (int(self.pos[b]) - j) // 4 == sleutel:
                    kandidaten.append(int(self.pos[b]) - j)
                b += 1
        basis = int(np.median(kandidaten))
        bron = self.bron[basis + js[0]]
        # welk stuk van de zin: liefst de hele zin, anders zonder eigen woorden aan het begin/eind
        m0, m1 = js[0], js[-1] + 3
        opties = [(0, len(kl)), (0, m1), (m0, len(kl)), (m0, m1)]
        if m0 <= 4 and len(kl) - m1 <= 4:
            opties = opties[:1] + opties[3:]
        gekozen = None
        for z0, z1 in dict.fromkeys(opties):
            r, s, e = self._beste_stuk(kl, z0, z1, basis, bron)
            if r < self.drempel:
                continue
            # alleen randen meenemen die zelf ook op de bron lijken (geen eigen woorden overschrijven)
            def lijkt(a, b):
                return SequenceMatcher(None, "".join(a), "".join(b), autojunk=False).ratio() >= 0.55
            if z0 < m0 and not lijkt(kl[z0:m0], self.kl[s:max(s, basis + m0)]):
                continue
            if z1 > m1 and not lijkt(kl[m1:z1], self.kl[min(e, basis + m1):e]):
                continue
            if True:
                gekozen = (r, s, e, z0, z1)
                break
        if not gekozen:
            return tekst, None
        r, s, e, z0, z1 = gekozen
        nieuw = " ".join(self.toon[s:e])
        if nieuw.count("(") != nieuw.count(")"):
            nieuw = nieuw.replace("(", "").replace(")", "")
        if [klank(w) for w in self.toon[s:e]] == kl[z0:z1] and \
                re.sub(r"\W", "", nieuw.lower()) == re.sub(r"\W", "", " ".join(woorden[idx[z0]:idx[z1 - 1] + 1]).lower()):
            return tekst, self.namen[bron]      # al goed, maar wel herkend
        voor = " ".join(woorden[:idx[z0]])
        na = " ".join(woorden[idx[z1 - 1] + 1:])
        oud_eind = woorden[idx[z1 - 1]]
        if not na and re.search(r"[.!?]$", oud_eind) and not re.search(r"[.!?;:]$", nieuw):
            nieuw = nieuw.rstrip(",;") + oud_eind[-1]
        uit = " ".join(x for x in (voor, nieuw, na) if x)
        return uit, self.namen[bron]
