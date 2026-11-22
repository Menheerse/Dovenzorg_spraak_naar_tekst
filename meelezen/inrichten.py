"""Hulpje voor INSTALLEREN-NIEUWE-COMPUTER.bat: config.toml klaarzetten voor deze computer.

Gebruik: python -m meelezen.inrichten <installatiemap>
- maakt config.toml aan (uit config.voorbeeld.toml) als die er nog niet is;
- zet de opslagmap op <installatiemap>\\opnames als die leeg is of nog naar een andere
  standaardmap ...\\meelezen\\opnames wijst (bijv. na overzetten naar een andere map);
- maakt de map opnames aan.
Een eigen NAS-map in config.toml blijft ongemoeid.

Met --ollama MODEL wordt de vertaling ingesteld op Ollama op deze computer (gratis, op de
videokaart), behalve als er al een OpenAI- of DeepL-sleutel is ingesteld.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path


def _zet(tekst: str, sectie: str, sleutel: str, waarde: str) -> str:
    """Zet sleutel = "waarde" binnen [sectie] (vervangt of voegt toe)."""
    m = re.search(rf"(?m)^\[{sectie}\]\s*$", tekst)
    if not m:
        return tekst.rstrip() + f'\n\n[{sectie}]\n{sleutel} = "{waarde}"\n'
    eind = re.search(r"(?m)^\[", tekst[m.end():])
    eind = m.end() + eind.start() if eind else len(tekst)
    blok = tekst[m.end():eind]
    regel = re.search(rf"(?m)^{sleutel}\s*=.*$", blok)
    if regel:
        blok = blok[:regel.start()] + f'{sleutel} = "{waarde}"' + blok[regel.end():]
    else:
        blok = f'\n{sleutel} = "{waarde}"' + blok
    return tekst[:m.end()] + blok + tekst[eind:]


def _waarde(tekst: str, sectie: str, sleutel: str) -> str:
    m = re.search(rf"(?ms)^\[{sectie}\]\s*$(.*?)(?=^\[|\Z)", tekst)
    r = re.search(rf"(?m)^{sleutel}\s*=\s*(['\"])(.*?)\1", m.group(1)) if m else None
    return r.group(2) if r else ""


def ollama(cfg: Path, model: str):
    tekst = cfg.read_text(encoding="utf-8")
    if _waarde(tekst, "sleutels", "openai") or _waarde(tekst, "sleutels", "deepl"):
        print("Er is al een OpenAI- of DeepL-sleutel: de vertaling blijft daarop staan.")
        return
    tekst = _zet(tekst, "vertaling", "engine", "openai")
    tekst = _zet(tekst, "vertaling", "api_url", "http://localhost:11434/v1")
    tekst = _zet(tekst, "vertaling", "openai_model", model)
    cfg.write_text(tekst, encoding="utf-8")
    print(f"Vertalen gaat nu gratis op deze computer met Ollama ({model}).")


def main():
    args = sys.argv[1:]
    model_ollama = None
    if "--ollama" in args:
        i = args.index("--ollama")
        model_ollama = args[i + 1] if i + 1 < len(args) else "gemma3:12b"
        del args[i:i + 2]
    doel = Path(args[0] if args else ".").resolve()
    cfg = doel / "config.toml"
    if not cfg.exists():
        shutil.copyfile(doel / "config.voorbeeld.toml", cfg)
        print("config.toml aangemaakt")

    opnames = doel / "opnames"
    tekst = cfg.read_text(encoding="utf-8")
    m = re.search(r"(?m)^map\s*=\s*(['\"])(.*?)\1", tekst)
    huidig = m.group(2) if m else None
    standaard = huidig is not None and (huidig.strip() == "" or re.search(r"[\\/]meelezen[\\/]opnames[\\/]?$", huidig, re.I))
    if m and standaard and huidig != str(opnames):
        tekst = tekst[:m.start()] + f"map = '{opnames}'" + tekst[m.end():]
        cfg.write_text(tekst, encoding="utf-8")
        print(f"Opnames en tekst worden bewaard in {opnames}")
    elif huidig:
        print(f"Opslagmap blijft: {huidig}")

    if standaard or not m:
        opnames.mkdir(exist_ok=True)
    if model_ollama:
        ollama(cfg, model_ollama)


if __name__ == "__main__":
    main()
