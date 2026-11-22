"""De bron: luistert naar de stream (of speelt de demo af) en voedt de hub."""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time

import numpy as np

from .audio import Knipper, Opnemer, is_youtube, pcm, youtube_live_url
from .config import BASIS
from .stt import is_geen_uitzending, schoon
from . import muziek as muz

log = logging.getLogger("meelezen.bron")


async def onderhoud(hub, opnemer: Opnemer | None):
    """Elke paar seconden: half afgemaakte zinnen afronden, archief bijwerken, dienst afsluiten."""
    laatst_bewaard = 0.0
    while True:
        await asyncio.sleep(3)
        hub.leeg_buffer(ouder_dan=12)
        if time.time() - laatst_bewaard > 30:
            laatst_bewaard = time.time()
            await asyncio.to_thread(hub.bewaar)
        stil = time.time() - hub.laatst_actief
        if hub.dienst and stil > hub.cfg.nieuwe_dienst_na and time.time() >= hub.niet_sluiten_voor:
            log.info("%s: %.0f min geen geluid; dienst wordt afgesloten", hub.naam, stil / 60)
            if opnemer:
                await opnemer.stop(laatste_geluid=hub.laatst_actief)
            if hub.dienst_is_leeg():
                # alleen de melding 'geen uitzending' gehoord: niets bewaren
                map_ = hub.dienst.get("map")
                if map_ and map_.exists():
                    import shutil
                    await asyncio.to_thread(shutil.rmtree, map_, True)
                log.info("%s: geen dienst gehoord, niets bewaard", hub.naam)
                hub.dienst = None
                continue
            await asyncio.to_thread(hub.sluit_dienst)
            if hub._gewijzigd:          # NAS onbereikbaar: over een minuut opnieuw proberen
                hub.niet_sluiten_voor = time.time() + 60
            else:
                log.info("%s: opname en tekst opgeslagen, dienst afgesloten", hub.naam)
                hub.dienst = None
                if hub.status["toestand"] == "live":
                    hub.zet_status("geen-uitzending", "afgelopen")


async def stream(cfg, hub, spraak, opnemer: Opnemer | None, url: str | None = None,
                 realtime_bestand: bool = True, eenmalig: bool = False):
    bron_url = url or cfg.stream_url
    wacht = 0
    while True:
        hub.zet_status("verbinden")
        url = bron_url
        if is_youtube(bron_url):
            url = await youtube_live_url(bron_url)
            if not url:
                hub.zet_status("geen-uitzending")
                if eenmalig:
                    return
                await asyncio.sleep(max(cfg.opnieuw_proberen, 30))
                continue
        knipper = Knipper(cfg.min_fragment, cfg.max_fragment, cfg.pauze, cfg.stilte_drempel)
        rij: asyncio.Queue = asyncio.Queue()
        achterstand = [0.0]
        gewaarschuwd = [False]
        verschuiving = 0.0
        begonnen = False

        async def werker():
            while True:
                item = await rij.get()
                if item is None:
                    return
                audio, start = item
                duur = len(audio) / 16000
                if cfg.muziek_aan:
                    k = muz.kenmerken(audio)
                    s = muz.soort_in_context(k, cfg, hub, start)
                    log.debug("%5.0fs %-6s %s", start, s, k)
                    if s != "spraak":
                        achterstand[0] -= duur
                        hub.muziek(s, start, start + duur)
                        continue
                prompt = (cfg.woordenlijst + ". " + hub.context()).strip(". ")
                try:
                    t0 = time.time()
                    tekst = schoon(await spraak.transcribeer(audio, prompt), cfg.woordenlijst)
                    log.debug("%.1fs geluid in %.1fs: %s", duur, time.time() - t0, tekst)
                except Exception as e:
                    log.exception("spraakherkenning mislukt: %s", e)
                    tekst = ""
                achterstand[0] -= duur
                if is_geen_uitzending(tekst):
                    hub.geen_uitzending_gehoord()
                    continue
                hub.fragment(tekst, start, start + duur)
                if hub.status["toestand"] == "live":
                    hub.zet_status("live", "achterstand" if achterstand[0] > 20 else "")
                if achterstand[0] > 60 and not gewaarschuwd[0]:
                    gewaarschuwd[0] = True
                    log.warning("De spraakherkenning loopt %.0f s achter: deze computer is te traag. "
                                "Kies model = \"base\" of engine = \"openai\" in config.toml.", achterstand[0])

        taak = asyncio.create_task(werker())

        def start_dienst(positie: float):
            """Eerste geluid na stilte: nieuwe dienst en opname starten."""
            d = hub.nieuwe_dienst()
            if opnemer and d["map"] and cfg.opslag_opname:
                opnemer.url = url
                opnemer.kopie = not is_youtube(bron_url) and ".mp3" in bron_url.lower()
                opnemer.wachten = lambda: hub.melding
                opnemer.start(d["map"] / "opname.mp3")
            hub.zet_status("live")
            return -positie   # tijden in deze dienst tellen vanaf dit moment

        try:
            doorgeven = hub.uitzending.voed if cfg.luisteren else None
            async for data in pcm(url, realtime_bestand, geluid=doorgeven, kbps=cfg.luister_kbps):
                if not begonnen:
                    begonnen, wacht = True, 0
                    if hub.dienst:   # stream was even weg, dienst loopt nog
                        verschuiving = hub.seconden_in_dienst()
                        hub.zet_status("live")
                    else:
                        hub.zet_status("live", "wachten")
                stukken = knipper.voed(data)
                blok = np.frombuffer(data[:len(data) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
                if len(blok) and float(np.sqrt(np.mean(blok * blok))) >= knipper._drempel():
                    if not hub.melding:                      # 'geen uitzending'-melding telt niet
                        hub.laatst_actief = time.time()      # er is geluid
                    if not hub.dienst:
                        verschuiving = start_dienst(knipper.totaal / 16000 - len(blok) / 16000)
                    elif not hub.melding and (hub.status["toestand"] != "live" or hub.status.get("detail") == "wachten"):
                        hub.zet_status("live")
                for audio, start in stukken:
                    if not hub.dienst:
                        continue
                    achterstand[0] += len(audio) / 16000
                    await rij.put((audio, max(0.0, verschuiving + start)))
        except Exception as e:
            log.warning("stream-fout: %s", e)
        for audio, start in knipper.leeg():
            if hub.dienst:
                await rij.put((audio, max(0.0, verschuiving + start)))
        await rij.put(None)
        await taak
        hub.leeg_buffer()
        hub.zet_status("geen-uitzending")
        if eenmalig:
            return
        wacht = min(cfg.opnieuw_proberen * 3, cfg.opnieuw_proberen + wacht)
        await asyncio.sleep(cfg.opnieuw_proberen if begonnen else wacht)


async def demo(cfg, hub, snelheid: float = 1.0):
    """Speelt een voorbeeldpreek af zodat de app zonder geluid te testen is."""
    tekst = (BASIS / "data" / "demo_preek.txt").read_text(encoding="utf-8")
    zinnen = [z.strip() for z in re.split(r"(?<=[.!?])\s+", tekst) if z.strip()]
    while True:
        hub.nieuwe_dienst()
        hub.zet_status("live")
        hub.muziek("orgel", 0, 15)                 # voorspel
        await asyncio.sleep(3 / snelheid)
        hub.muziek("zang", 15, 60)                 # er wordt gezongen
        await asyncio.sleep(4 / snelheid)
        t = 65.0
        for i, zin in enumerate(zinnen):
            if i == len(zinnen) // 2:
                hub.muziek("zang", t, t + 120)     # lied halverwege
                t += 125
                await asyncio.sleep(4 / snelheid)
            woorden = zin.split()
            for i in range(1, len(woorden)):
                hub.gedeeltelijk(" ".join(woorden[:i]))
                await asyncio.sleep(0.32 / snelheid)
            duur = len(woorden) * 0.38
            hub.deel = ""
            hub.fragment(zin, t, t + duur)
            t += duur + random.uniform(0.3, 1.2)
            hub.laatst_actief = time.time()
            await asyncio.sleep(random.uniform(0.6, 1.6) / snelheid)
        hub.zet_status("geen-uitzending")
        await asyncio.sleep(30 / snelheid)
