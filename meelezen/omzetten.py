"""Bestaande opnames (mp3, wav, m4a, ...) omzetten naar tekst en ondertitels.

Gebruik:
  python -m meelezen.omzetten                 -> kies bestanden in een venster
  python -m meelezen.omzetten dienst.mp3 ...  -> deze bestanden
  python -m meelezen.omzetten --talen en,de   -> ook vertalen

Naast elk bestand komen:  <naam>.txt  en  <naam>.srt  (VLC laadt de .srt vanzelf),
en per vertaling  <naam>.en.txt / <naam>.en.srt.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import muziek, stt
from .audio import Knipper, pcm
from .config import TAALNAMEN, laad
from .hub import Archief, Hub, _tijd, tekstregels
from .vertaal import Vertaler

EXTENSIES = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wma", ".mp4", ".mkv")


class _GeenVertaler:
    aan = False
    talen: list = []


def kies_bestanden() -> list[Path]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        pad = input("Sleep een geluidsbestand in dit venster (of typ het pad) en druk op Enter:\n> ").strip().strip('"')
        return [Path(pad)] if pad else []
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    namen = filedialog.askopenfilenames(
        title="Kies een of meer opnames om om te zetten naar tekst",
        filetypes=[("Geluid", " ".join("*" + e for e in EXTENSIES)), ("Alle bestanden", "*.*")])
    root.destroy()
    return [Path(n) for n in namen]


def youtube_downloaden(url: str, map_: Path) -> Path | None:
    """Downloadt het geluid van een YouTube-video als mp3."""
    map_.mkdir(parents=True, exist_ok=True)
    print(f"YouTube-geluid downloaden naar {map_} …")
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "-x", "--audio-format", "mp3", "--audio-quality", "5",
                        "--no-playlist", "--no-simulate", "--print", "after_move:filepath", "-o",
                        str(map_ / "%(upload_date>%Y-%m-%d)s %(title).80B.%(ext)s"), url],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    paden = [r_.strip() for r_ in r.stdout.splitlines() if r_.strip()]
    if r.returncode != 0 or not paden or not Path(paden[-1]).exists():
        print("  Downloaden mislukt:", (r.stderr.strip().splitlines() or ["onbekende fout"])[-1][:300])
        return None
    return Path(paden[-1])


_V = []


def _verwijzer():
    """Bijbelverwijzingen ook in omgezette opnames (eenmalig laden)."""
    if not _V:
        from .bijbel import Bijbel
        from .config import BASIS
        b = Bijbel(BASIS / "data" / "bijbel.json")
        from .verwijzingen import Verwijzer
        _V.append(Verwijzer(b.data) if b.data else None)
    return _V[0]


_C = []


def _corrector():
    """Voorgelezen Bijbel, psalmen en formulieren rechtzetten (eenmalig laden)."""
    if not _C:
        from .bijbel import Bijbel
        from .config import BASIS
        from .correctie import Corrector
        from .formulieren import Formulieren
        from .psalmen import Psalmboek
        b = Bijbel(BASIS / "data" / "bijbel.json")
        _C.append(Corrector(b.data, Psalmboek().psalmen, Formulieren().teksten(), BASIS / "data" / "vaste-teksten"))
    return _C[0]


def duur(pad: Path) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(pad)],
                           capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _mmss(s: float) -> str:
    return _tijd(s)[3:] if s < 3600 else _tijd(s)


async def zet_om(pad: Path, cfg, spraak, vertaler, talen: list[str]) -> list[Path]:
    totaal = duur(pad)
    hub = Hub(cfg, _GeenVertaler(), Archief(cfg))
    hub.dienst = {"start": None, "t0": time.time(), "map": None}
    hub.verwijzer = _verwijzer()
    if cfg.vaste_teksten:
        hub.corrector = _corrector()
    knipper = Knipper(cfg.min_fragment, cfg.max_fragment, cfg.pauze, cfg.stilte_drempel)
    t0 = time.time()
    verwerkt = 0.0

    async def doe(audio, start):
        nonlocal verwerkt
        if cfg.muziek_aan:
            s = muziek.soort_in_context(muziek.kenmerken(audio), cfg, hub, start)
            if s != "spraak":
                hub.muziek(s, start, start + len(audio) / 16000)
                verwerkt = start + len(audio) / 16000
                return
        prompt = (cfg.woordenlijst + ". " + hub.context()).strip(". ")
        tekst = stt.schoon(await spraak.transcribeer(audio, prompt), cfg.woordenlijst)
        if stt.is_geen_uitzending(tekst):
            tekst = ""          # 'Geachte luisteraar, er is op dit moment geen uitzending'
        hub.fragment(tekst, start, start + len(audio) / 16000)
        verwerkt = start + len(audio) / 16000
        if totaal:
            deel = min(1.0, verwerkt / totaal)
            verstreken = time.time() - t0
            rest = verstreken / deel - verstreken if deel > 0.02 else 0
            print(f"\r  {_mmss(verwerkt)} / {_mmss(totaal)}  ({deel:4.0%})   nog ± {rest / 60:3.0f} min   ",
                  end="", flush=True)

    async for data in pcm(str(pad), realtime_bestand=False):
        for audio, start in knipper.voed(data):
            await doe(audio, start)
    for audio, start in knipper.leeg():
        await doe(audio, start)
    hub.leeg_buffer()
    zinnen = hub.zinnen
    print(f"\r  Klaar: {len(zinnen)} zinnen in {(time.time() - t0) / 60:.1f} min." + " " * 30)
    if not zinnen:
        print("  Er is geen spraak gevonden in dit bestand.")
        return []

    for taal in talen:
        print(f"  Vertalen naar {TAALNAMEN[taal][0]}…", end="", flush=True)
        for i, z in enumerate(zinnen):
            if z.soort != "spraak":
                continue
            context = [x.nl for x in zinnen[max(0, i - 4):i] if x.soort == "spraak"]
            uit = await vertaler.vertaal(z.nl, taal, context)
            if uit:
                z.vert[taal] = uit
            print(f"\r  Vertalen naar {TAALNAMEN[taal][0]}: {i + 1}/{len(zinnen)}", end="", flush=True)
        print()

    basis = pad.with_suffix("")
    gemaakt = []

    def schrijf(p: Path, tekst: str):
        p.write_text(tekst, encoding="utf-8")
        gemaakt.append(p)

    kop = f"{pad.name} — omgezet op {time.strftime('%d-%m-%Y %H:%M')}\n\n"
    schrijf(basis.with_suffix(".txt"), kop + tekstregels(zinnen, "nl"))
    schrijf(basis.with_suffix(".srt"), Archief._srt(zinnen, "nl"))
    for taal in talen:
        if any(z.vert.get(taal) for z in zinnen):
            schrijf(Path(f"{basis}.{taal}.txt"), tekstregels(zinnen, taal))
            schrijf(Path(f"{basis}.{taal}.srt"), Archief._srt(zinnen, taal))
    schrijf(basis.with_suffix(".json"), json.dumps(
        {"bestand": pad.name, "zinnen": [{"start": round(z.start, 2), "eind": round(z.eind, 2), "nl": z.nl,
                                          **{k: v for k, v in z.vert.items() if v}} for z in zinnen]},
        ensure_ascii=False, indent=1))
    return gemaakt


async def hoofd(args):
    cfg = laad(args.config)
    if args.model:
        cfg.model = args.model
    if cfg.spraak_engine == "demo":
        cfg.spraak_engine = "auto"
    invoer = [b.strip('"') for b in args.bestanden]
    if not invoer and sys.stdin.isatty():
        link = input("Plak een YouTube-link en druk op Enter, of druk alleen op Enter om een bestand te kiezen:\n> ").strip()
        if link:
            invoer = [link]
    from .config import BASIS
    youtube_map = (cfg.opslag / "youtube") if cfg.opslag else BASIS / "opnames"
    bestanden: list[Path] = []
    for b in invoer:
        if b.startswith("http"):
            pad = youtube_downloaden(b, youtube_map)
            if pad:
                bestanden.append(pad)
        else:
            bestanden.append(Path(b))
    if not invoer:
        bestanden = kies_bestanden()
    bestanden = [b for b in bestanden if b.exists()]
    if not bestanden:
        print("Geen bestand gekozen.")
        return 1
    if not shutil.which("ffmpeg"):
        print("ffmpeg ontbreekt: voer installeren.bat opnieuw uit.")
        return 1

    vertaler = Vertaler(cfg)
    talen: list[str] = []
    if args.talen is not None:
        gevraagd = [t.strip() for t in args.talen.split(",") if t.strip()]
    elif vertaler.aan and sys.stdin.isatty():
        print("Beschikbare vertalingen:", ", ".join(f"{t} ({TAALNAMEN[t][0]})" for t in vertaler.talen))
        gevraagd = [t.strip() for t in input("Ook vertalen? Typ taalcodes, bijv. en,de (leeg = nee): ").split(",") if t.strip()]
    else:
        gevraagd = []
    for t in gevraagd:
        if t in vertaler.talen:
            talen.append(t)
        else:
            print(f"  Vertaling naar '{t}' is niet beschikbaar en wordt overgeslagen.")

    print("Spraakherkenning voorbereiden…")
    spraak = await asyncio.to_thread(stt.maak, cfg)
    for i, b in enumerate(bestanden, 1):
        print(f"\n[{i}/{len(bestanden)}] {b.name}")
        try:
            for p in await zet_om(b, cfg, spraak, vertaler, talen):
                print(f"  -> {p}")
        except Exception as e:
            print(f"\n  Mislukt: {e}")
    return 0


def main():
    p = argparse.ArgumentParser(description="Opnames omzetten naar tekst")
    p.add_argument("bestanden", nargs="*", help="geluidsbestanden; leeg = kiezen in een venster")
    p.add_argument("--talen", help="ook vertalen, bijv. en,de")
    p.add_argument("--model", help="ander Whisper-model, bijv. medium (nauwkeuriger, trager)")
    p.add_argument("--config")
    a = p.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    sys.exit(asyncio.run(hoofd(a)))


if __name__ == "__main__":
    main()
