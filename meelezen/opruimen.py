"""Opgeslagen diensten opruimen: de melding 'geen uitzending' eruit halen.

Na een uitzending speelt kerkdienstgemist steeds een korte melding af ("Geachte luisteraar, er is
op dit moment geen uitzending..."). Vóór deze versie van Meelezen werd die melding soms
opgenomen: elke herhaling werd dan een los bestand opname_deel2.mp3, opname_deel3.mp3, ...
en de melding stond tientallen keren in tekst.txt.

Gebruik:  opruimen.bat              (alle diensten in de opslagmap)
          opruimen.bat <map>        (één dienstmap of een andere map)

Er wordt eerst getoond wat er weg kan; pas na 'J' wordt er iets verwijderd.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from .audio import ffmpeg_pad
from .stt import is_geen_uitzending

KORT = 20.0   # een los opnamedeel korter dan dit is (vrijwel) altijd alleen de melding


def duur(pad: Path) -> float:
    r = subprocess.run([ffmpeg_pad(), "-hide_banner", "-i", str(pad)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def _tijden_tekst(regels: list[str]) -> tuple[list[str], set[str]]:
    """Regels met de melding weghalen; geeft de overgebleven regels en de weggehaalde tijden."""
    weg, uit = set(), []
    for r in regels:
        m = re.match(r"\[(\d\d:\d\d:\d\d)\]", r)
        if m and is_geen_uitzending(r):
            weg.add(m.group(1))
            continue
        uit.append(r)
    while uit and not uit[-1].strip():
        uit.pop()
    return uit, weg


def bekijk(map_: Path) -> dict:
    """Wat kan er in deze dienstmap weg?"""
    plan = {"map": map_, "bestanden": [], "tekst": 0, "tijden": set()}
    for p in sorted(map_.glob("opname_deel*.mp3")):
        d = duur(p)
        if d < KORT:
            plan["bestanden"].append((p, d))
    t = map_ / "tekst.txt"
    if t.exists():
        regels = t.read_text(encoding="utf-8").splitlines()
        _, weg = _tijden_tekst(regels)
        plan["tekst"] = len(weg)
        plan["tijden"] = weg
    return plan


def _srt_schoon(tekst: str, weg_nl: bool) -> str:
    blokken = re.split(r"\n\s*\n", tekst.strip())
    uit = []
    for b in blokken:
        if weg_nl and is_geen_uitzending(b):
            continue
        regels = b.splitlines()
        if regels and regels[0].strip().isdigit():
            regels = regels[1:]
        uit.append(regels)
    return "\n\n".join(f"{i}\n" + "\n".join(r) for i, r in enumerate(uit, 1)) + "\n"


def uitvoeren(plan: dict):
    map_: Path = plan["map"]
    for p, _ in plan["bestanden"]:
        p.unlink(missing_ok=True)
    if not plan["tekst"]:
        return
    tijden = plan["tijden"]
    for t in map_.glob("tekst*.txt"):
        regels = t.read_text(encoding="utf-8").splitlines()
        if t.name == "tekst.txt":
            uit, _ = _tijden_tekst(regels)
        else:   # vertalingen: dezelfde tijdstippen weghalen
            uit = [r for r in regels if not (re.match(r"\[(\d\d:\d\d:\d\d)\]", r)
                                             and re.match(r"\[(\d\d:\d\d:\d\d)\]", r).group(1) in tijden)]
        t.write_text("\n".join(uit) + "\n", encoding="utf-8")
    s = map_ / "ondertitels.srt"
    if s.exists():
        s.write_text(_srt_schoon(s.read_text(encoding="utf-8"), True), encoding="utf-8")
    j = map_ / "dienst.json"
    if j.exists():
        try:
            d = json.loads(j.read_text(encoding="utf-8"))
            d["zinnen"] = [z for z in d.get("zinnen", []) if not is_geen_uitzending(z.get("nl", ""))]
            j.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass


def main():
    from .config import laad
    if len(sys.argv) > 1:
        basis = Path(sys.argv[1])
    else:
        basis = laad().opslag
        if not basis:
            print("Er is geen opslagmap ingesteld in config.toml.")
            return 1
    if not basis.exists():
        print(f"Map niet gevonden: {basis}")
        return 1
    mappen = [basis] if (basis / "tekst.txt").exists() or list(basis.glob("opname*.mp3")) else \
        sorted(p for p in basis.iterdir() if p.is_dir())
    print(f"Diensten in {basis} nakijken…\n")
    plannen = []
    for m in mappen:
        plan = bekijk(m)
        if plan["bestanden"] or plan["tekst"]:
            plannen.append(plan)
            print(f"  {m.name}: {len(plan['bestanden'])} losse opnamedelen met alleen de melding, "
                  f"{plan['tekst']} regels met de melding in de tekst")
    if not plannen:
        print("  Niets gevonden: alles is al schoon.")
        return 0
    n = sum(len(p["bestanden"]) for p in plannen)
    print(f"\nSamen {n} opnamedelen (korter dan {KORT:.0f} s) en "
          f"{sum(p['tekst'] for p in plannen)} tekstregels.")
    if input("Opruimen? Typ J en druk op Enter: ").strip().lower() not in ("j", "ja", "y"):
        print("Niets veranderd.")
        return 0
    for p in plannen:
        uitvoeren(p)
    print("Klaar. De melding is uit de opnames en de tekst gehaald.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
