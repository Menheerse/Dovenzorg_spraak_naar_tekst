"""Laat zien wat de muziekherkenning van een opname maakt, zonder spraakherkenning (snel).

Gebruik: python -m meelezen.muziektest opname.mp3
Vergelijk de tijdlijn met wat er echt gebeurde en pas zo nodig [muziek] in config.toml aan.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from . import muziek
from .audio import Knipper, pcm
from .config import laad
from .hub import _tijd


async def hoofd(pad: str):
    from .hub import Archief, Hub

    cfg = laad()
    knipper = Knipper(cfg.min_fragment, cfg.max_fragment, cfg.pauze, cfg.stilte_drempel)

    class GeenVertaler:
        aan = False
        talen: list = []

    hub = Hub(cfg, GeenVertaler(), Archief(cfg, None))   # Archief zonder map: er wordt niets opgeslagen
    hub.nieuwe_dienst()
    regels = []

    def verwerk(stukken):
        # precies dezelfde stappen als tijdens een live dienst, alleen zonder spraakherkenning
        for audio, start in stukken:
            eind = start + len(audio) / 16000
            k = muziek.kenmerken(audio)
            srt = muziek.soort_in_context(k, cfg, hub, start)
            regels.append((start, eind, srt, k))
            if srt == "spraak":
                hub.fragment("…", start, eind)
            else:
                hub.muziek(srt, start, eind)

    print(f"{Path(pad).name} analyseren…")
    async for data in pcm(pad, realtime_bestand=False):
        verwerk(knipper.voed(data))
    verwerk(knipper.leeg())

    print("\nPer fragment:   tijd      soort    kenmerken")
    for s, e, srt, k in regels:
        print(f"  {_tijd(s)}  {srt:7}  {k}")

    print("\nZo verschijnt het in de app (muziekmeldingen):")
    for z in hub.zinnen:
        if z.soort != "spraak":
            print(f"  {_tijd(z.start)} – {_tijd(z.eind)}  {z.nl}")
    print("\nKlopt het niet? Kijk in config.toml onder [muziek]:")
    print("  - spraak wordt als muziek gezien      -> min_aanhoudend hoger (bijv. 0.4)")
    print("  - muziek wordt als spraak gezien      -> min_aanhoudend lager (bijv. 0.2)")
    print("  - zingen wordt 'orgelspel' genoemd     -> zang_min_vlakheid lager, of spraak_niveau lager")
    print("  - orgel wordt 'samenzang' genoemd      -> zang_min_vlakheid hoger, of spraak_niveau hoger")


def main():
    pad = sys.argv[1] if len(sys.argv) > 1 else input("Sleep een opname in dit venster en druk op Enter:\n> ").strip().strip('"')
    asyncio.run(hoofd(pad))


if __name__ == "__main__":
    main()
