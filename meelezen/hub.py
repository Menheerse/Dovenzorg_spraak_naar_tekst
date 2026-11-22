"""Centrale toestand: de zinnen van de lopende dienst, de verbonden telefoons en het archief."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("meelezen.hub")

EINDE_ZIN = re.compile(r"(?<=[.!?…])[\"”’)]*\s+(?=[\"“‘(]?[A-ZÀ-Ý0-9'])")
MAX_GESCHIEDENIS = 2000
INHAAL = 60  # zoveel eerdere zinnen worden vertaald als iemand een taal kiest


@dataclass
class Zin:
    id: int
    nl: str
    start: float          # seconden sinds begin dienst
    eind: float
    t: float = field(default_factory=time.time)
    vert: dict[str, str] = field(default_factory=dict)
    soort: str = "spraak"     # "spraak", "zang" of "orgel"
    refs: list = field(default_factory=list)   # gevonden bijbelverwijzingen/-citaten

    def voor(self, taal: str) -> dict:
        d = {"id": self.id, "nl": self.nl, "start": round(self.start, 1), "t": int(self.t * 1000),
             "tekst": self.nl if taal == "nl" else self.vert.get(taal)}
        if self.refs:
            d["refs"] = self.refs
        if self.soort != "spraak":
            d["soort"] = self.soort
            d["duur"] = round(self.eind - self.start)
        return d

    def in_taal(self, taal: str) -> str:
        if taal == "nl" or self.soort != "spraak":
            return self.nl
        return self.vert.get(taal) or self.nl


class Abonnee:
    def __init__(self, taal: str):
        self.taal = taal
        self.q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.weg = False

    def stuur(self, soort: str, data: dict):
        if self.weg:
            return
        try:
            self.q.put_nowait((soort, data))
        except asyncio.QueueFull:
            self.weg = True  # te trage verbinding; de telefoon maakt zelf opnieuw verbinding


def _tijd(s: float, srt=False) -> str:
    s = max(0.0, s)
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    if srt:
        return f"{int(h):02}:{int(m):02}:{int(sec):02},{int((sec % 1) * 1000):03}"
    return f"{int(h):02}:{int(m):02}:{int(sec):02}"


def tekstregels(zinnen: list[Zin], taal: str) -> str:
    regels = []
    for z in zinnen:
        if z.soort != "spraak":
            regels.append(f"\n[{_tijd(z.start)}] {z.nl} ({max(1, round((z.eind - z.start) / 60))} min)\n")
        else:
            bron = "".join(f"  [{r['label']}]" for r in z.refs if r.get("soort") == "citaat")
            regels.append(f"[{_tijd(z.start)}] {z.in_taal(taal)}{bron}")
    return "\n".join(regels) + "\n"


class Archief:
    """Schrijft per dienst een map met opname, tekst en ondertitels naar de NAS."""

    def __init__(self, cfg, basis=None):
        self.basis = basis if basis is not None else cfg.opslag
        self.cfg = cfg
        self.fout = ""

    @property
    def aan(self) -> bool:
        return self.basis is not None

    def map_voor(self, start: datetime) -> Path | None:
        if not self.aan:
            return None
        deel = "ochtend" if start.hour < 12 else "middag" if start.hour < 18 else "avond"
        return self.basis / f"{start:%Y-%m-%d_%H%M}_{deel}"

    def schrijf(self, map_: Path, info: dict, zinnen: list[Zin], talen: list[str]) -> bool:
        if not (self.aan and self.cfg.opslag_tekst and zinnen):
            return True
        try:
            map_.mkdir(parents=True, exist_ok=True)
            kop = f"{info.get('kerknaam', '')} — dienst van {info['start']:%d-%m-%Y %H:%M}\n\n"
            self._atomisch(map_ / "tekst.txt", kop + tekstregels(zinnen, "nl"))
            self._atomisch(map_ / "ondertitels.srt", self._srt(zinnen, "nl"))
            for taal in talen:
                if any(z.vert.get(taal) for z in zinnen):
                    self._atomisch(map_ / f"tekst_{taal}.txt", tekstregels(zinnen, taal))
                    self._atomisch(map_ / f"ondertitels_{taal}.srt", self._srt(zinnen, taal))
            self._atomisch(map_ / "dienst.json", json.dumps({
                "start": info["start"].isoformat(timespec="seconds"),
                "zinnen": [{"start": round(z.start, 2), "eind": round(z.eind, 2), "nl": z.nl, **{k: v for k, v in z.vert.items() if v}} for z in zinnen],
            }, ensure_ascii=False, indent=1))
            self.fout = ""
            return True
        except OSError as e:
            self.fout = f"NAS niet bereikbaar: {e}"
            log.warning(self.fout)
            return False

    @staticmethod
    def _srt(zinnen: list[Zin], taal: str) -> str:
        regels = []
        for i, z in enumerate(zinnen, 1):
            tekst = z.in_taal(taal) + (" ♪" if z.soort != "spraak" else "")
            eind = max(z.eind, z.start + 1.5)
            regels.append(f"{i}\n{_tijd(z.start, True)} --> {_tijd(eind, True)}\n{tekst}\n")
        return "\n".join(regels)

    @staticmethod
    def _atomisch(pad: Path, tekst: str):
        tmp = pad.with_suffix(pad.suffix + ".tmp")
        tmp.write_text(tekst, encoding="utf-8")
        tmp.replace(pad)

    def opruimen(self):
        if not (self.aan and self.cfg.bewaar_dagen > 0 and self.basis.exists()):
            return
        grens = datetime.now() - timedelta(days=self.cfg.bewaar_dagen)
        for d in self.basis.iterdir():
            m = re.match(r"(\d{4}-\d{2}-\d{2})_\d{4}_", d.name)
            if d.is_dir() and m and datetime.strptime(m.group(1), "%Y-%m-%d") < grens:
                shutil.rmtree(d, ignore_errors=True)
                log.info("oude dienst verwijderd: %s", d.name)


class Hub:
    def __init__(self, cfg, vertaler, archief: Archief, naam: str | None = None):
        self.cfg, self.vertaler, self.archief = cfg, vertaler, archief
        self.naam = naam or cfg.kerknaam
        self.verwijzer = None   # wordt door de server gezet als er een bijbel is
        self.corrector = None   # vaste teksten rechtzetten (Bijbel, psalmen, formulieren)
        self.zinnen: list[Zin] = []
        self.deel = ""
        self.buf, self.buf_start, self.buf_eind, self.buf_t = "", 0.0, 0.0, 0.0
        self.status = {"toestand": "opstarten", "detail": ""}
        self.abonnees: set[Abonnee] = set()
        from .luisteren import Uitzending
        self.uitzending = Uitzending()   # het geluid zelf, voor wie wil luisteren
        self.dienst: dict | None = None
        self.laatst_actief = 0.0
        self.laatst_inhoud = 0.0     # laatste echte tekst of muziek
        self.melding = False         # de zender speelt 'er is op dit moment geen uitzending'
        self.niet_sluiten_voor = 0.0
        self._kandidaat = None
        self.volgend_id = 1
        self._gewijzigd = False
        self._taken: set[asyncio.Task] = set()

    # ---- telefoons ----
    def talen_actief(self) -> Counter:
        return Counter(a.taal for a in self.abonnees if not a.weg)

    def abonneer(self, taal: str) -> Abonnee:
        a = Abonnee(taal)
        self.abonnees.add(a)
        a.stuur("status", self._status())
        a.stuur("geschiedenis", {"zinnen": [z.voor(taal) for z in self.zinnen], "deel": self.deel,
                                 "dienst": self._dienst_info()})
        if taal != "nl":
            for z in self.zinnen[-INHAAL:]:
                if taal not in z.vert:
                    self._vertaal_later(z, taal)
        return a

    def opzeggen(self, a: Abonnee):
        self.abonnees.discard(a)

    def _naar_allen(self, soort: str, maak):
        for a in list(self.abonnees):
            if a.weg:
                self.abonnees.discard(a)
                continue
            data = maak(a)
            if data is not None:
                a.stuur(soort, data)

    def _status(self) -> dict:
        s = dict(self.status)
        if self.archief.fout:
            s["opslag"] = self.archief.fout
        s["luisteraars"] = sum(self.talen_actief().values())
        return s

    def zet_status(self, toestand: str, detail: str = ""):
        nieuw = {"toestand": toestand, "detail": detail}
        if nieuw != self.status:
            self.status = nieuw
            log.info("status: %s %s", toestand, detail)
            self._naar_allen("status", lambda a: self._status())

    # ---- diensten ----
    def _dienst_info(self):
        if not self.dienst:
            return None
        return {"start": self.dienst["start"].isoformat(timespec="minutes")}

    def heeft_lopende_dienst(self) -> bool:
        return self.dienst is not None

    def nieuwe_dienst(self) -> dict:
        self.sluit_dienst()
        start = datetime.now()
        self.dienst = {"start": start, "t0": time.time(), "kerknaam": self.naam,
                       "map": self.archief.map_voor(start)}
        self.zinnen, self.deel, self.buf = [], "", ""
        self.laatst_actief = time.time()
        log.info("nieuwe dienst: %s", start)
        self._naar_allen("reset", lambda a: {"dienst": self._dienst_info()})
        return self.dienst

    def sluit_dienst(self):
        if not self.dienst:
            return
        self.leeg_buffer()
        self.bewaar()
        self.archief.opruimen()

    def inhoud_gehoord(self):
        """Echte tekst of muziek: de dienst loopt (weer)."""
        self.laatst_actief = self.laatst_inhoud = time.time()
        if self.melding:
            self.melding = False
            log.info("%s: uitzending begonnen", self.naam)
            if self.dienst:
                self.zet_status("live")

    def geen_uitzending_gehoord(self):
        """De zender herhaalt 'Geachte luisteraar, er is op dit moment geen uitzending'. Dat telt
        niet als geluid: de dienst is afgelopen (of nog niet begonnen) en wordt na de ingestelde
        tijd na het laatste échte geluid afgesloten."""
        if not self.melding:
            log.info("%s: zender meldt 'geen uitzending'", self.naam)
        self.melding = True
        begin = self.dienst["t0"] if self.dienst else 0.0
        self.laatst_actief = max(self.laatst_inhoud, begin)
        self.zet_status("geen-uitzending", "afgelopen" if self.zinnen else "")

    def dienst_is_leeg(self) -> bool:
        return not self.zinnen

    def seconden_in_dienst(self) -> float:
        return time.time() - self.dienst["t0"] if self.dienst else 0.0

    def bewaar(self):
        if self.dienst and self.dienst["map"] and self._gewijzigd:
            self._gewijzigd = False
            if not self.archief.schrijf(self.dienst["map"], self.dienst, list(self.zinnen), self.cfg.talen):
                self._gewijzigd = True  # later opnieuw proberen

    # ---- tekst ----
    def gedeeltelijk(self, tekst: str):
        """Tekst die nog wordt uitgesproken (alleen voor de demo-modus)."""
        self.deel = tekst
        self._naar_allen("deel", lambda a: {"nl": tekst})

    def fragment(self, tekst: str, start: float, eind: float):
        tekst = tekst.strip()
        if not tekst:
            return
        self.inhoud_gehoord()
        if not self.buf:
            self.buf_start = start
        self.buf = (self.buf + " " + tekst).strip()
        self.buf_eind, self.buf_t = eind, time.time()
        delen = EINDE_ZIN.split(self.buf)
        compleet, rest = delen[:-1], delen[-1]
        if re.search(r"[.!?…][\"”’)]*$", rest):
            compleet, rest = delen, ""
        elif len(rest) > 260:  # erg lange zin zonder punt: afbreken bij een komma
            k = rest.rfind(", ", 0, 240)
            if k > 60:
                compleet.append(rest[:k + 1])
                rest = rest[k + 2:]
        totaal = max(1, sum(len(z) for z in compleet) + len(rest))
        duur = self.buf_eind - self.buf_start
        t = self.buf_start
        for z in compleet:
            d = duur * len(z) / totaal
            self._nieuwe_zin(z, t, t + d)
            t += d
        self.buf, self.buf_start = rest, t
        self.deel = rest
        self._naar_allen("deel", lambda a: {"nl": rest})

    def leeg_buffer(self, ouder_dan: float = 0):
        if self.buf and time.time() - self.buf_t >= ouder_dan:
            z, self.buf = self.buf, ""
            self._nieuwe_zin(z, self.buf_start, self.buf_eind)
            self.deel = ""
            self._naar_allen("deel", lambda a: {"nl": ""})

    def context(self, n=220) -> str:
        tekst = " ".join(z.nl for z in self.zinnen[-4:] if z.soort == "spraak") + " " + self.buf
        return tekst.strip()[-n:]

    def _nieuwe_zin(self, tekst: str, start: float, eind: float):
        tekst = tekst.strip()
        if not tekst:
            return
        bron = None
        if self.corrector and self.cfg.vaste_teksten:
            try:
                tekst, bron = self.corrector.corrigeer(tekst)
                if bron:
                    log.debug("rechtgezet uit %s: %s", bron, tekst)
            except Exception as e:
                log.warning("vaste tekst rechtzetten mislukt: %s", e)
        z = Zin(self.volgend_id, tekst, start, eind)
        if self.verwijzer:
            try:
                recent = {(r["boek"], r["h"]) for x in self.zinnen[-40:] for r in x.refs}
                if bron and bron not in self.corrector.bijbelbronnen:
                    # voorgelezen uit een formulier, de Twaalf Artikelen, een psalmvers...:
                    # geen 'citaat'-links naar losse bijbelteksten, alleen genoemde verwijzingen
                    z.refs = self.verwijzer.genoemd(tekst)
                else:
                    z.refs = self.verwijzer.vind(tekst, recent)
            except Exception as e:  # een fout in de herkenning mag het meelezen niet stoppen
                log.warning("verwijzingen zoeken mislukt: %s", e)
        self.volgend_id += 1
        self.zinnen.append(z)
        del self.zinnen[:-MAX_GESCHIEDENIS]
        self._gewijzigd = True
        self._naar_allen("zin", lambda a: z.voor(a.taal))
        for taal in self.talen_actief():
            if taal != "nl":
                self._vertaal_later(z, taal)

    def muziek(self, soort: str, start: float, eind: float):
        """Orgelspel of samenzang.

        Aansluitende muziek van dezelfde soort wordt samengevoegd. Wisselt de soort (voorspel ->
        zingen -> naspel), dan komt er een nieuwe melding, maar pas als de nieuwe soort minstens
        30 seconden aanhoudt; een orgeltussenspel tussen twee verzen telt dus niet.
        """
        from .muziek import LABELS
        self.inhoud_gehoord()
        self.leeg_buffer()
        vorige = self.zinnen[-1] if self.zinnen else None
        aansluitend = vorige is not None and vorige.soort != "spraak" and start - vorige.eind < 25
        if aansluitend and vorige.soort != soort and vorige.eind - vorige.start < 15:
            # de melding is nog maar net begonnen: dan klopte het eerste stukje niet, alleen het label aanpassen
            vorige.soort, vorige.nl, vorige.eind = soort, LABELS[soort], eind
            self._kandidaat = None
            self._gewijzigd = True
            self._naar_allen("zin", lambda a: vorige.voor(a.taal))
            return
        if aansluitend and vorige.soort == soort:
            vorige.eind = eind
            self._kandidaat = None
            self._gewijzigd = True
            return
        if aansluitend:
            k = self._kandidaat if self._kandidaat and self._kandidaat["soort"] == soort else \
                {"soort": soort, "start": start, "aantal": 0}
            k["aantal"] += 1
            k["eind"] = eind
            self._kandidaat = k
            lang_genoeg = k["eind"] - k["start"] >= 30 and (k["aantal"] >= 2 or eind - start >= 30)
            if not lang_genoeg:
                vorige.eind = eind   # voorlopig bij de huidige melding houden
                self._gewijzigd = True
                return
            vorige.eind = k["start"]
            start = k["start"]
            self._kandidaat = None
        z = Zin(self.volgend_id, LABELS[soort], start, eind, soort=soort)
        self.volgend_id += 1
        self.zinnen.append(z)
        self._gewijzigd = True
        self._naar_allen("zin", lambda a: z.voor(a.taal))

    def muziek_bezig(self, start: float, binnen: float = 3) -> str | None:
        """'zang'/'orgel' als er tot vlak voor dit moment (binnen .. s) muziek klonk, anders None."""
        z = self.zinnen[-1] if self.zinnen else None
        if z and z.soort != "spraak" and start - z.eind < binnen:
            return z.soort
        return None

    def _vertaal_later(self, z: Zin, taal: str):
        if z.soort != "spraak":
            return
        if not self.vertaler.aan or taal not in self.vertaler.talen:
            return
        idx = next((i for i in range(len(self.zinnen) - 1, -1, -1) if self.zinnen[i] is z), len(self.zinnen))
        context = [x.nl for x in self.zinnen[max(0, idx - 4):idx] if x.soort == "spraak"]
        z.vert.setdefault(taal, None)  # markeren als 'bezig'

        async def werk():
            uit = await self.vertaler.vertaal(z.nl, taal, context)
            if uit:
                z.vert[taal] = uit
                self._gewijzigd = True
                self._naar_allen("vertaling", lambda a: {"id": z.id, "tekst": uit} if a.taal == taal else None)
            else:
                z.vert.pop(taal, None)

        taak = asyncio.create_task(werk())
        self._taken.add(taak)
        taak.add_done_callback(self._taken.discard)
