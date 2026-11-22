"""Controleert of deze computer geschikt is en geeft advies.  Gebruik: python -m meelezen.controle"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time

import numpy as np

from .config import laad


def regel(ok, tekst):
    print(f"  {'OK ' if ok is True else '!! ' if ok is False else '-- '} {tekst}")


def geheugen_gb() -> float | None:
    try:
        if sys.platform == "win32":
            import ctypes

            class M(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tot", ctypes.c_ulonglong),
                            ("av", ctypes.c_ulonglong)] + [(f"x{i}", ctypes.c_ulonglong) for i in range(5)]
            m = M()
            m.l = ctypes.sizeof(M)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.tot / 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except Exception:
        return None


def main():
    cfg = laad()
    print("\n=== Meelezen: controle van deze computer ===\n")
    py = sys.version_info
    regel((3, 11) <= py[:2] <= (3, 13), f"Python {py.major}.{py.minor}")
    print(f"      Processor: {platform.processor() or platform.machine()}, {os.cpu_count()} kernen")
    gb = geheugen_gb()
    if gb:
        regel(gb >= 3.5, f"Werkgeheugen: {gb:.0f} GB")
    regel(bool(shutil.which("ffmpeg")), "ffmpeg" if shutil.which("ffmpeg") else "ffmpeg ontbreekt: voer installeren.bat opnieuw uit")

    from .stt import heeft_cuda
    cuda = heeft_cuda()
    regel(cuda or None, "NVIDIA-videokaart bruikbaar" if cuda else "Geen bruikbare NVIDIA-videokaart")
    from .stt import gpu_info, _versie
    gpu = gpu_info()
    if gpu:
        print(f"      {gpu['naam']}, {gpu['geheugen_gb']:.0f} GB, stuurprogramma {gpu['driver']}, "
              f"compute capability {gpu['cc']:.1f}")
        if gpu["cc"] >= 10:
            regel(_versie(gpu["driver"]) >= (572, 0),
                  "Blackwell-kaart: stuurprogramma is actueel genoeg" if _versie(gpu["driver"]) >= (572, 0)
                  else "Blackwell-kaart: stuurprogramma te oud, installeer de nieuwste via de NVIDIA App")
            try:
                from importlib.metadata import version
                cb = version("nvidia-cublas-cu12")
                regel(_versie(cb) >= (12, 8), f"cuBLAS {cb}" + ("" if _versie(cb) >= (12, 8)
                      else " is te oud voor Blackwell: voer installeren.bat opnieuw uit"))
            except Exception:
                regel(False, "nvidia-cublas-cu12 ontbreekt: voer installeren.bat opnieuw uit")

    lokaal_vertalen = cfg.vertaal_api_url.startswith(("http://localhost", "http://127.0.0.1"))
    if lokaal_vertalen and cfg.vertaal_engine != "uit":
        try:
            import json
            import urllib.request
            basis = cfg.vertaal_api_url.rsplit("/v1", 1)[0]
            with urllib.request.urlopen(basis + "/api/tags", timeout=5) as r:
                modellen = [m["name"] for m in json.load(r).get("models", [])]
            gevonden = any(m == cfg.openai_vertaal_model or m.split(":")[0] == cfg.openai_vertaal_model for m in modellen)
            regel(gevonden, f"Ollama draait; vertaalmodel {cfg.openai_vertaal_model} "
                  + ("is aanwezig" if gevonden else f"ontbreekt: ollama pull {cfg.openai_vertaal_model}"))
        except Exception:
            regel(False, "Ollama is niet bereikbaar: start Ollama (staat in het startmenu)")
    from .config import BASIS
    for bestand, naam, bat in (("bijbel.json", "Bijbel (Statenvertaling)", "bijbel-ophalen.bat"),
                               ("psalmen.json", "Psalmboek", "psalmen-ophalen.bat"),
                               ("formulieren.json", "Formulieren", "formulieren-ophalen.bat"),
                               ("henry.db", "Verklaring Matthew Henry", None)):
        er = (BASIS / "data" / bestand).exists()
        regel(er or None, naam + (" aanwezig" if er else (f" ontbreekt: voer {bat} uit" if bat else " ontbreekt")))
    vast = BASIS / "data" / "vaste-teksten"
    eigen = sorted(p.stem for p in vast.glob("*.txt")) if vast.is_dir() else []
    if eigen:
        regel(True, "Eigen vaste teksten: " + ", ".join(eigen))
    if not cfg.vaste_teksten:
        regel(None, "Voorgelezen teksten rechtzetten staat uit ([spraak] vaste_teksten = false)")
    regel(bool(cfg.openai_key) or None, "OpenAI-sleutel ingesteld" if cfg.openai_key else "Geen OpenAI-sleutel ingesteld")

    if cfg.opslag:
        try:
            cfg.opslag.mkdir(parents=True, exist_ok=True)
            test = cfg.opslag / ".meelezen-test"
            test.write_text("ok")
            test.unlink()
            regel(True, f"NAS-map beschrijfbaar: {cfg.opslag}")
        except OSError as e:
            regel(False, f"NAS-map niet bereikbaar: {e}")
    else:
        regel(None, "Geen NAS-map ingesteld ([opslag] map)")

    for kerk in cfg.kerken:
        if not kerk.stream_url:
            regel(False, f"{kerk.naam}: geen stream_url ingesteld in config.toml")
            continue
        if "youtube" in kerk.stream_url:
            regel(None, f"{kerk.naam}: YouTube ({kerk.stream_url})")
            continue
        if shutil.which("ffprobe"):
            try:
                r = subprocess.run(["ffprobe", "-v", "error", "-rw_timeout", "10000000", "-show_entries",
                                    "stream=codec_name", "-of", "csv=p=0", kerk.stream_url],
                                   capture_output=True, text=True, timeout=20)
                regel(None, f"{kerk.naam}: " + ("er is nu een live-uitzending" if r.returncode == 0 and r.stdout.strip()
                      else "nu geen live-uitzending (normaal buiten de diensttijden)"))
            except Exception:
                regel(None, f"{kerk.naam}: uitzending niet te controleren")
    if len(cfg.kerken) > 1 and not cfg.openai_key:
        print("      Let op: twee kerken tegelijk op de processor is zwaar. Vallen de diensten tegelijk,")
        print("      dan is OpenAI sterk aan te raden.")

    snelheid = None
    if not cuda:
        try:
            from faster_whisper import WhisperModel
            model = "small" if cfg.model in ("auto",) or cfg.model.startswith("large") else cfg.model
            print(f"\n  Snelheidstest met model '{model}' op de processor (eerste keer: model downloaden)…")
            m = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
            rng = np.random.default_rng(0)
            t = np.arange(16000 * 12) / 16000
            audio = (rng.normal(0, 1, t.size) * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)) * 0.2).astype(np.float32)
            t0 = time.time()
            list(m.transcribe(audio, language="nl", beam_size=1, vad_filter=False, max_new_tokens=60)[0])
            snelheid = (time.time() - t0) / 12
            regel(snelheid < 0.6, f"12 seconden geluid verwerkt in {snelheid * 12:.1f} s")
        except ImportError:
            regel(None, "faster-whisper niet geïnstalleerd; snelheidstest overgeslagen")
        except Exception as e:
            regel(False, f"Snelheidstest mislukt: {e}")

    print("\n=== Advies ===")
    if cuda:
        print("  Deze computer heeft een geschikte videokaart. Laat engine = \"auto\" staan.")
    elif snelheid is not None and snelheid < 0.35:
        print("  Deze computer is snel genoeg om gratis op de processor te werken (model 'small').")
    elif snelheid is not None and snelheid < 0.6:
        print("  Op de processor lukt het net. Bij achterstand: zet model = \"base\" (minder nauwkeurig)")
        print("  of gebruik OpenAI voor de beste kwaliteit.")
    else:
        print("  Deze computer is te traag voor spraakherkenning op de processor." if snelheid is not None
              else "  De snelheid kon niet worden gemeten; zonder videokaart is OpenAI de veilige keuze.")
        print("  Zet een OpenAI-sleutel in config.toml (onder [sleutels]); de app kiest dan vanzelf OpenAI.")
        print("  Kosten: ongeveer 0,35 euro per uur dienst. Het meelezen zelf blijft op deze laptop draaien.")
    if not cfg.openai_key and not cfg.deepl_key and not lokaal_vertalen:
        print("  Zonder OpenAI-sleutel is er ook geen vertaling naar andere talen.")
        if cuda:
            print("  Met deze videokaart kan het ook gratis: installeer Ollama (zie LEESMIJ, Vertalen).")
    print()


if __name__ == "__main__":
    main()
