"""Ollama: gratis vertalen op de NVIDIA-videokaart van deze computer.

Gebruik:
  python -m meelezen.ollama installeren   Ollama + vertaalmodel installeren en instellen (bij NVIDIA)
  python -m meelezen.ollama controle      laat zien of Ollama draait en het model er is

De app start Ollama zelf als het nog niet draait, en laadt het model alvast in het geheugen,
zodat de eerste vertaalde zin niet hoeft te wachten.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("meelezen.ollama")

ADRES = "http://localhost:11434"
BLIJF = "3h"   # model zo lang in het geheugen houden: een hele dienst plus marge


def pad() -> str | None:
    """Waar staat ollama.exe?"""
    kandidaten = [shutil.which("ollama")]
    if sys.platform == "win32":
        kandidaten += [os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
                       os.path.expandvars(r"%ProgramFiles%\Ollama\ollama.exe")]
    for k in kandidaten:
        if k and Path(k).exists():
            return k
    return None


def _get(pad_: str, timeout=3):
    with urllib.request.urlopen(ADRES + pad_, timeout=timeout) as r:
        return json.load(r)


def draait() -> bool:
    try:
        _get("/api/version")
        return True
    except Exception:
        return False


def modellen() -> list[str]:
    try:
        return [m["name"] for m in _get("/api/tags").get("models", [])]
    except Exception:
        return []


def heeft(model: str) -> bool:
    return any(m == model or m == model + ":latest" for m in modellen())


def start(wacht: float = 20) -> bool:
    """Ollama op de achtergrond starten als het nog niet draait."""
    if draait():
        return True
    exe = pad()
    if not exe:
        return False
    env = dict(os.environ, OLLAMA_KEEP_ALIVE=BLIJF)
    vlaggen = 0
    if sys.platform == "win32":
        vlaggen = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    try:
        subprocess.Popen([exe, "serve"], env=env, creationflags=vlaggen,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        log.warning("Ollama starten lukt niet: %s", e)
        return False
    eind = time.time() + wacht
    while time.time() < eind:
        if draait():
            return True
        time.sleep(0.5)
    return False


def opwarmen(model: str):
    """Model alvast in het videogeheugen laden en daar houden."""
    body = json.dumps({"model": model, "prompt": "", "keep_alive": BLIJF}).encode()
    req = urllib.request.Request(ADRES + "/api/generate", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        r.read()


def klaarzetten(model: str):
    """Bij het starten van de app: Ollama starten en het model opwarmen (in een achtergrondthread)."""
    if not start():
        log.warning("Ollama draait niet en kon niet worden gestart; vertalen werkt dan niet. "
                    "Start Ollama via het startmenu.")
        return
    if not heeft(model):
        log.warning("Vertaalmodel %s ontbreekt in Ollama. Voer uit: ollama pull %s", model, model)
        return
    try:
        t0 = time.time()
        opwarmen(model)
        log.info("Vertaalmodel %s staat klaar op de videokaart (%.0f s)", model, time.time() - t0)
    except Exception as e:
        log.warning("Vertaalmodel opwarmen mislukt: %s", e)


def kies_model(geheugen_gb: float) -> str | None:
    """Vertaalmodel dat naast Whisper large-v3 (± 4 GB) op de kaart past."""
    if geheugen_gb >= 14:
        return "gemma3:12b"   # ± 9 GB, goede vertalingen (RTX PRO 2000 Blackwell: 16 GB)
    if geheugen_gb >= 7:
        return "gemma3:4b"    # ± 3,5 GB
    return None


def installeren(basis: Path) -> int:
    from .stt import gpu_info
    info = gpu_info()
    if not info:
        print("Geen NVIDIA-videokaart: Ollama wordt niet geïnstalleerd (vertalen kan via OpenAI of DeepL).")
        return 0
    model = kies_model(info["geheugen_gb"])
    if not model:
        print(f"{info['naam']} heeft te weinig geheugen ({info['geheugen_gb']:.0f} GB) voor vertalen op de kaart.")
        return 0
    print(f"Gratis vertalen op de {info['naam']} ({info['geheugen_gb']:.0f} GB) met Ollama, model {model}.")

    if not pad():
        if sys.platform != "win32" or not shutil.which("winget"):
            print("Installeer Ollama via https://ollama.com/download en voer dit daarna opnieuw uit.")
            return 1
        print("Ollama installeren…")
        subprocess.run(["winget", "install", "--id", "Ollama.Ollama", "-e", "--silent",
                        "--accept-source-agreements", "--accept-package-agreements"])
        if not pad():
            print("Ollama is niet gevonden na de installatie. Installeer het via https://ollama.com/download")
            return 1

    if sys.platform == "win32":
        # ook voor de Ollama-app zelf (systeemvak): het model niet na 5 minuten stilte weggooien
        subprocess.run(["setx", "OLLAMA_KEEP_ALIVE", BLIJF], stdout=subprocess.DEVNULL)

    if not start(wacht=40):
        print("Ollama start niet. Start Ollama via het startmenu en voer installeren.bat opnieuw uit.")
        return 1
    if heeft(model):
        print(f"Vertaalmodel {model} is er al.")
    else:
        print(f"Vertaalmodel {model} ophalen (eenmalig, enkele GB)…")
        r = subprocess.run([pad(), "pull", model])
        if r.returncode != 0 or not heeft(model):
            print(f"Ophalen mislukt. Later opnieuw: ollama pull {model}")
            return 1

    cfg = basis / "config.toml"
    if not cfg.exists():
        shutil.copyfile(basis / "config.voorbeeld.toml", cfg)
    from .inrichten import ollama as instellen
    instellen(cfg, model)
    try:
        print("Proefvertaling…", end=" ", flush=True)
        body = json.dumps({"model": model, "stream": False, "keep_alive": BLIJF, "messages": [
            {"role": "user", "content": "Translate into English, output only the translation: "
                                        "De Heere is mijn Herder, mij zal niets ontbreken."}]}).encode()
        req = urllib.request.Request(ADRES + "/api/chat", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            print(json.load(r)["message"]["content"].strip())
    except Exception as e:
        print(f"mislukt ({e})")
    return 0


def main():
    basis = Path(__file__).resolve().parent.parent
    opdracht = sys.argv[1] if len(sys.argv) > 1 else "controle"
    if opdracht == "installeren":
        sys.exit(installeren(basis))
    print("Ollama:", pad() or "niet geïnstalleerd")
    print("Draait:", "ja" if draait() else "nee")
    print("Modellen:", ", ".join(modellen()) or "-")


if __name__ == "__main__":
    main()
