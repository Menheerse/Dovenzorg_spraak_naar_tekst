"""Webserver: de app voor de telefoons en de live-verbinding (Server-Sent Events)."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import socket
import sys
from pathlib import Path

import uvicorn
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse, FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import bron, stt
from .audio import Opnemer
from .bijbel import Dienst
from .config import BASIS, RTL, TAALNAMEN, laad
from .hub import Archief, Hub
from .vertaal import Vertaler

log = logging.getLogger("meelezen")


class Kanaal:
    """Eén kerk: eigen stream, tekst, opnames en Bijbel bij de dienst."""

    def __init__(self, kerk, cfg, vertaler, bijbel, meerdere: bool):
        self.kerk = kerk
        basis = None
        if cfg.opslag and meerdere:
            basis = cfg.opslag / "".join(c if c.isalnum() or c in " -_." else "_" for c in kerk.naam).strip()
        self.archief = Archief(cfg, basis)
        self.hub = Hub(cfg, vertaler, self.archief, kerk.naam)
        self.dienst = Dienst(BASIS / "data", kerk.id if meerdere else None, bijbel)
        self.opnemer = Opnemer(kerk.stream_url) if self.archief.aan and cfg.opslag_opname else None

    def info(self) -> dict:
        s = self.hub.status
        return {"id": self.kerk.id, "naam": self.kerk.naam, "plaats": self.kerk.plaats,
                "toestand": s["toestand"] if self.kerk.stream_url or s["toestand"] == "live" else "niet-ingesteld",
                "luisteraars": sum(self.hub.talen_actief().values()),
                "geluid": self.hub.uitzending.actief}


class GedeeldeSpraak:
    """Eén spraakmodel voor alle kerken. Lokaal zoveel tegelijk als het model aankan
    (videokaart met genoeg geheugen: 2, processor: 1), via internet onbeperkt."""

    def __init__(self, spraak, lokaal: bool):
        self.spraak = spraak
        self.slot = asyncio.Semaphore(getattr(spraak, "tegelijk", 1)) if lokaal else None

    async def transcribeer(self, audio, prompt):
        if self.slot is None:
            return await self.spraak.transcribeer(audio, prompt)
        async with self.slot:
            return await self.spraak.transcribeer(audio, prompt)


def maak_app(cfg, demo_snelheid: float = 1.0) -> Starlette:
    from .bijbel import Bijbel
    vertaler = Vertaler(cfg)
    bijbel = Bijbel(BASIS / "data" / "bijbel.json")
    meerdere = len(cfg.kerken) > 1
    kanalen = {k.id: Kanaal(k, cfg, vertaler, bijbel, meerdere) for k in cfg.kerken}
    from .psalmen import Psalmboek
    from .verklaring import Verklaring
    psalmboek = Psalmboek()
    verklaring = Verklaring(BASIS / "data" / "henry.db")
    from .formulieren import Formulieren
    formulieren = Formulieren()
    bronnen_stand = {}
    for kn in kanalen.values():
        kn.dienst.psalmboek = psalmboek if psalmboek.aan else None
    def bijbel_bijwerken(eerste=False):
        """Na bijbel-ophalen.bat de nieuwe bijbel gebruiken, zonder herstart."""
        nieuw = bijbel.ververs()
        if nieuw or eerste:
            from .verwijzingen import Verwijzer
            v = Verwijzer(bijbel.data) if bijbel.data else None
            for kn in kanalen.values():
                kn.hub.verwijzer = v
        # vaste teksten (Bijbel, psalmen, formulieren, data/vaste-teksten) voor het rechtzetten
        psalmboek.ververs()
        formulieren.ververs()
        map_vast = BASIS / "data" / "vaste-teksten"
        stand = (id(bijbel.data), psalmboek._mtime, formulieren._mtime,
                 tuple(sorted((p.name, p.stat().st_mtime) for p in map_vast.glob("*.txt"))) if map_vast.is_dir() else ())
        if cfg.vaste_teksten and stand != bronnen_stand.get("s"):
            bronnen_stand["s"] = stand
            from .correctie import Corrector
            try:
                c = Corrector(bijbel.data, psalmboek.psalmen, formulieren.teksten(), map_vast)
            except Exception as e:
                log.warning("vaste teksten laden mislukt: %s", e)
                c = None
            for kn in kanalen.values():
                kn.hub.corrector = c

    bijbel_bijwerken(eerste=True)
    taken: list[asyncio.Task] = []

    def kanaal(request) -> Kanaal:
        return kanalen.get(request.query_params.get("kerk", "")) or next(iter(kanalen.values()))

    @contextlib.asynccontextmanager
    async def levensduur(app):
        for kn in kanalen.values():
            if kn.archief.aan:
                try:
                    kn.archief.basis.mkdir(parents=True, exist_ok=True)
                    log.info("opslag %s: %s", kn.kerk.naam, kn.archief.basis)
                except OSError as e:
                    kn.archief.fout = f"opslagmap niet bereikbaar: {e}"
                    log.error(kn.archief.fout)
        if cfg.spraak_engine == "demo":
            log.info("DEMO-modus: er wordt een voorbeeldpreek afgespeeld")
            for i, kn in enumerate(kanalen.values()):
                kn.opnemer = None
                taken.append(asyncio.create_task(bron.demo(cfg, kn.hub, demo_snelheid * (1 + 0.15 * i))))
        else:
            spraak = await asyncio.to_thread(stt.maak, cfg)
            gedeeld = GedeeldeSpraak(spraak, getattr(cfg, "spraak_gekozen", "") != "openai")
            for kn in kanalen.values():
                if not kn.kerk.stream_url:
                    kn.hub.zet_status("geen-uitzending")
                    log.warning("%s: geen stream_url ingesteld", kn.kerk.naam)
                    continue
                log.info("%s luistert naar %s", kn.kerk.naam, kn.kerk.stream_url[:70])
                taken.append(asyncio.create_task(bron.stream(cfg, kn.hub, gedeeld, kn.opnemer, url=kn.kerk.stream_url)))
        for kn in kanalen.values():
            taken.append(asyncio.create_task(bron.onderhoud(kn.hub, kn.opnemer)))
        if vertaler.aan and cfg.vertaal_api_url.startswith(("http://localhost:11434", "http://127.0.0.1:11434")):
            from . import ollama
            taken.append(asyncio.create_task(asyncio.to_thread(ollama.klaarzetten, cfg.openai_vertaal_model)))
        if not vertaler.aan:
            log.info("vertaling staat uit (geen engine of sleutel ingesteld)")
        yield
        for t in taken:
            t.cancel()
        for kn in kanalen.values():
            if kn.opnemer:
                await kn.opnemer.stop()
            kn.hub.sluit_dienst()

    async def index(request):
        return FileResponse(BASIS / "static" / "index.html", headers={"Cache-Control": "no-cache"})

    async def instellingen(request):
        talen = [{"code": "nl", "naam": TAALNAMEN["nl"][0]}] + [
            {"code": t, "naam": TAALNAMEN[t][0], "rtl": t in RTL} for t in vertaler.talen]
        return JSONResponse({"kerknaam": cfg.kerknaam, "talen": talen,
                             "luisteren": cfg.luisteren and cfg.spraak_engine != "demo",
                             "niet_actief": [{"id": k.id, "naam": k.naam} for k in getattr(cfg, "alle_kerken", [])
                                             if k.id not in kanalen],
                             "kerken": [kn.info() for kn in kanalen.values()]})

    async def kerken(request):
        return JSONResponse([kn.info() for kn in kanalen.values()], headers={"Cache-Control": "no-cache"})

    async def luister(request: Request):
        """Het geluid van de dienst als mp3-stream, een paar seconden vertraagd zodat het gelijk
        oploopt met de tekst (?direct=1: zonder vertraging)."""
        if not cfg.luisteren:
            return JSONResponse({"fout": "luisteren staat uit"}, status_code=404)
        uitz = kanaal(request).hub.uitzending
        vertraging = 0.0 if request.query_params.get("direct") else cfg.luister_vertraging
        return StreamingResponse(uitz.luister(vertraging), media_type="audio/mpeg", headers={
            "Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no", "icy-name": "Meelezen"})

    async def live(request: Request):
        taal = request.query_params.get("taal", "nl")
        if taal != "nl" and taal not in vertaler.talen:
            taal = "nl"
        hub = kanaal(request).hub
        abonnee = hub.abonneer(taal)

        async def gebeurtenissen():
            try:
                while True:
                    soort, data = await abonnee.q.get()
                    yield {"event": soort, "data": json.dumps(data, ensure_ascii=False)}
                    if abonnee.weg:
                        return
            finally:
                hub.opzeggen(abonnee)

        return EventSourceResponse(gebeurtenissen(), ping=15, headers={"X-Accel-Buffering": "no"})

    async def dienst_json(request):
        return JSONResponse(kanaal(request).dienst.get(), headers={"Cache-Control": "no-cache"})

    async def bijbel_hoofdstuk(request):
        boek, h = request.query_params.get("boek", ""), request.query_params.get("h", "")
        bijbel_bijwerken()
        hoofdstuk = bijbel.data.get(boek, {}).get(h)
        if not hoofdstuk:
            return JSONResponse({"fout": "niet gevonden"}, status_code=404)
        hs = sorted(bijbel.data[boek], key=int)
        i = hs.index(h)
        return JSONResponse({"boek": boek, "h": int(h),
                             "verzen": [{"nr": int(v), "tekst": t} for v, t in sorted(hoofdstuk.items(), key=lambda x: int(x[0]))],
                             "vorige": int(hs[i - 1]) if i > 0 else None,
                             "volgende": int(hs[i + 1]) if i + 1 < len(hs) else None},
                            headers={"Cache-Control": "no-cache"})

    async def download(request):
        from datetime import datetime

        from . import export
        kn = kanaal(request)
        hub = kn.hub
        formaat = request.query_params.get("formaat", "pdf")
        taal = request.query_params.get("taal", "nl")
        if taal != "nl" and taal not in vertaler.talen:
            taal = "nl"
        if not any(z.soort == "spraak" for z in hub.zinnen):
            return JSONResponse({"fout": "Er is nog geen tekst van deze dienst."}, status_code=404)
        if taal != "nl":
            await hub.vertaal_alles(taal)
        if formaat == "pdf" and taal in export.PDF_ONGESCHIKT:
            formaat = "docx"   # dit schrift kan de PDF-maker niet goed zetten; Word wel
        start = hub.dienst["start"] if hub.dienst and hub.dienst.get("start") else \
            datetime.fromtimestamp(hub.zinnen[0].t - hub.zinnen[0].start)
        inhoud = export.alineas(list(hub.zinnen), taal)
        maker = export.maak_pdf if formaat == "pdf" else export.maak_docx
        try:
            data = await asyncio.to_thread(maker, kn.kerk.naam, start, taal, inhoud, kn.dienst.get())
        except ImportError:
            return JSONResponse({"fout": "PDF maken is niet geïnstalleerd: voer installeren.bat opnieuw uit."},
                                status_code=500)
        naam = export.bestandsnaam(kn.kerk.naam, start, taal, formaat)
        soort = "application/pdf" if formaat == "pdf" else \
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        from urllib.parse import quote
        return Response(data, media_type=soort, headers={
            "Content-Disposition": f"attachment; filename=\"preek.{formaat}\"; filename*=UTF-8''{quote(naam)}",
            "Cache-Control": "no-store"})

    async def bijbel_boeken(request):
        bijbel_bijwerken()
        return JSONResponse(bijbel.boekenlijst(), headers={"Cache-Control": "no-cache"})

    async def bijbel_zoeken(request):
        vraag = request.query_params.get("q", "").strip()[:100]
        if not vraag:
            return JSONResponse({"resultaten": [], "meer": False})
        ref = bijbel.ontleed(vraag)
        if ref:
            return JSONResponse({"ref": {"boek": ref[0], "h": ref[1], "v": ref[2]}})
        resultaten, meer = await asyncio.to_thread(bijbel.tekst_zoeken, vraag)
        return JSONResponse({"resultaten": resultaten, "meer": meer})

    async def verklaring_hoofdstuk(request):
        boek, h = request.query_params.get("boek", ""), request.query_params.get("h", "0")
        try:
            d = await asyncio.to_thread(verklaring.hoofdstuk, boek, int(h))
        except ValueError:
            d = None
        if not d:
            return JSONResponse({"fout": "geen verklaring"}, status_code=404)
        # bijbelverwijzingen in de verklaring klikbaar maken
        v = next((kn.hub.verwijzer for kn in kanalen.values() if kn.hub.verwijzer), None)
        if v:
            for deel in d["delen"]:
                deel["refs"] = [[{k: r[k] for k in ("label", "boek", "h", "v", "van", "tot")} for r in v.genoemd(a)]
                                for a in deel["tekst"]]
        return JSONResponse(d, headers={"Cache-Control": "no-cache"})

    async def verklaring_aan(request):
        verklaring.ververs()
        return JSONResponse({"aan": verklaring.aan, "naam": "Matthew Henry"})

    async def formulieren_overzicht(request):
        if formulieren.ververs():
            await asyncio.to_thread(bijbel_bijwerken)
        return JSONResponse({"formulieren": formulieren.overzicht()}, headers={"Cache-Control": "no-cache"})

    async def formulier(request):
        formulieren.ververs()
        f = formulieren.get(request.query_params.get("id", ""))
        if not f:
            return JSONResponse({"fout": "onbekend formulier"}, status_code=404)
        return JSONResponse(f)

    async def psalmen_overzicht(request):
        psalmboek.ververs()
        for kn in kanalen.values():
            kn.dienst.psalmboek = psalmboek if psalmboek.aan else None
        return JSONResponse(psalmboek.overzicht(), headers={"Cache-Control": "no-cache"})

    async def psalm(request):
        psalmboek.ververs()
        q = request.query_params
        try:
            d = psalmboek.gezang(int(q["gezang"])) if "gezang" in q else psalmboek.psalm(int(q.get("nr", "0")))
        except ValueError:
            d = None
        if not d:
            return JSONResponse({"fout": "niet gevonden"}, status_code=404)
        return JSONResponse(d, headers={"Cache-Control": "no-cache"})

    async def psalmen_zoeken(request):
        psalmboek.ververs()
        vraag = request.query_params.get("q", "").strip()[:100]
        ref = psalmboek.ontleed(vraag) if vraag else None
        if ref:
            return JSONResponse({"ref": {"nr": ref[0], "v": ref[1]}})
        resultaten, meer = await asyncio.to_thread(psalmboek.zoek, vraag)
        return JSONResponse({"resultaten": resultaten, "meer": meer})

    async def status(request):
        return JSONResponse({"spraak": getattr(cfg, "spraak_gekozen", "") or cfg.spraak_engine,
                             "kerken": [{**kn.info(), **kn.hub._status(), "zinnen": len(kn.hub.zinnen),
                                         "talen": dict(kn.hub.talen_actief())} for kn in kanalen.values()]})

    return Starlette(routes=[
        Route("/", index),
        Route("/bijbel", index),
        Route("/api/instellingen", instellingen),
        Route("/api/kerken", kerken),
        Route("/api/live", live),
        Route("/api/luister", luister),
        Route("/api/dienst", dienst_json),
        Route("/api/status", status),
        Route("/api/bijbel", bijbel_hoofdstuk),
        Route("/api/bijbel/boeken", bijbel_boeken),
        Route("/api/bijbel/zoek", bijbel_zoeken),
        Route("/api/psalmen", psalmen_overzicht),
        Route("/api/formulieren", formulieren_overzicht),
        Route("/api/formulier", formulier),
        Route("/api/verklaring", verklaring_hoofdstuk),
        Route("/api/verklaring/aan", verklaring_aan),
        Route("/api/psalm", psalm),
        Route("/api/psalmen/zoek", psalmen_zoeken),
        Route("/api/download", download),
        Mount("/static", StaticFiles(directory=BASIS / "static"), name="static"),
    ], lifespan=levensduur)


def eigen_adres() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "localhost"


def _tijd_naar_sec(s: str) -> float:
    return float(sum(int(x) * 60 ** i for i, x in enumerate(reversed(s.strip().split(":")))))


def _kies_mp3() -> str | None:
    """Windows-verkennervenster om een geluidsbestand te kiezen."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        pad = input("  Sleep het mp3-bestand in dit venster en druk op Enter:\n  > ").strip().strip('"')
        return pad or None
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    pad = filedialog.askopenfilename(
        title="Kies de opname die je wilt afspelen",
        filetypes=[("Geluid", "*.mp3 *.wav *.m4a *.aac *.ogg *.opus *.flac *.wma *.mp4"), ("Alle bestanden", "*.*")])
    root.destroy()
    return pad or None


def _keuze(vraag: str, opties: list[str]) -> int:
    print(vraag)
    for i, o in enumerate(opties, 1):
        print(f"    {i}. {o}")
    while True:
        k = input("  Typ het nummer en druk op Enter: ").strip() or "1"
        if k.isdigit() and 1 <= int(k) <= len(opties):
            return int(k) - 1
        print(f"  Typ alleen een nummer van 1 tot {len(opties)}.")


def startmenu(cfg):
    """Vraagt bij het starten zonder opties: livestream of mp3-bestand."""
    print("\n  ===  Meelezen  ===\n")
    keus = _keuze("  Wat wil je doen?", ["Livestream volgen (zoals ingesteld in config.toml)",
                                         "Een mp3-bestand afspelen",
                                         "Demo: voorbeeldpreek zonder geluid"])
    if keus == 1:
        pad = _kies_mp3()
        if not pad or not Path(pad).exists():
            print("  Geen bestand gekozen; de livestream wordt gevolgd.")
            return
        print(f"  Gekozen: {pad}")
        kerk = cfg.kerken[0]
        if len(cfg.kerken) > 1:
            kerk = cfg.kerken[_keuze("\n  Bij welke kerk hoort deze opname?", [k.naam for k in cfg.kerken])]
        vanaf = input("\n  Vanaf welk tijdstip afspelen? Bijv. 35:00 (Enter = vanaf het begin): ").strip()
        if vanaf:
            try:
                from . import audio
                audio.VANAF = _tijd_naar_sec(vanaf)
            except ValueError:
                print("  Dat tijdstip begrijp ik niet; er wordt vanaf het begin afgespeeld.")
        kerk.stream_url = pad
        cfg.kerken = [kerk]
        cfg.stream_url = pad
        cfg.opslag_opname = False   # het bestand bestaat al; alleen de tekst opslaan
    elif keus == 2:
        cfg.spraak_engine = "demo"
    elif len(cfg.kerken) > 1:
        opties = [k.naam for k in cfg.kerken] + ["Beide" if len(cfg.kerken) == 2 else "Alle kerken"]
        k = _keuze("\n  Welke livestream?", opties)
        cfg.alle_kerken = list(cfg.kerken)
        if k < len(cfg.kerken):
            cfg.kerken = [cfg.kerken[k]]
        print("  Gekozen: " + ", ".join(x.naam for x in cfg.kerken))


def kies_kerken(cfg, waarde: str):
    """--kerk gergem / hhg / beide (ook een deel van de naam mag)."""
    w = waarde.strip().lower()
    if w in ("beide", "alle", "alles", "all"):
        return
    gekozen = [k for k in cfg.kerken if k.id.lower() == w] or \
              [k for k in cfg.kerken if w in k.naam.lower() or w in k.id.lower()]
    if not gekozen:
        raise SystemExit(f"Onbekende kerk '{waarde}'. Kies uit: " + ", ".join(k.id for k in cfg.kerken) + " of beide")
    cfg.alle_kerken = list(cfg.kerken)
    cfg.kerken = gekozen[:1]


def main():
    p = argparse.ArgumentParser(description="Meelezen: live preek meelezen en vertalen")
    p.add_argument("--config", help="pad naar config.toml")
    p.add_argument("--demo", action="store_true", help="voorbeeldpreek afspelen, zonder geluid")
    p.add_argument("--live", action="store_true", help="direct de livestream volgen, zonder keuzemenu")
    p.add_argument("--kerk", help="bij --live: welke livestream: gergem, hhg of beide (standaard beide)")
    p.add_argument("--bestand", help="een geluidsbestand gebruiken in plaats van de stream (om te testen)")
    p.add_argument("--vanaf", help="bij --bestand: beginnen op dit tijdstip, bijv. 25:00 of 1:05:00")
    p.add_argument("-v", "--uitgebreid", action="store_true", help="meer meldingen tonen")
    a = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.uitgebreid else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    cfg = laad(a.config)
    if a.demo:
        cfg.spraak_engine = "demo"
    if a.bestand:
        cfg.stream_url = a.bestand
        cfg.kerken = cfg.kerken[:1]
        cfg.kerken[0].stream_url = a.bestand
        cfg.opslag_opname = False
        if a.vanaf:
            from . import audio
            audio.VANAF = _tijd_naar_sec(a.vanaf)
    if a.kerk:
        kies_kerken(cfg, a.kerk)
    if not (a.demo or a.bestand or a.live or a.kerk) and sys.stdin.isatty():
        startmenu(cfg)
    print(f"\n  Meelezen draait.  Open op een telefoon in hetzelfde netwerk:  http://{eigen_adres()}:{cfg.poort}\n")
    # eigen event-loop: op Windows is dat de Proactor-loop, nodig voor ffmpeg als subprocess
    server = uvicorn.Server(uvicorn.Config(maak_app(cfg), host="0.0.0.0", port=cfg.poort,
                                           log_level="warning", loop="none"))
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
