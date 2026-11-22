"""Spraakherkenning: faster-whisper (lokaal) of OpenAI (via internet)."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import urllib.request
import uuid
import wave

import numpy as np

from .audio import RATE

log = logging.getLogger("meelezen.spraak")

# Onschuldige meldingen bij het downloaden van het spraakmodel verbergen
import os as _os
_os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
for _naam in ("httpx", "httpx2", "huggingface_hub"):
    logging.getLogger(_naam).setLevel(logging.WARNING)

# Teksten die Whisper bij stilte of muziek soms verzint
HALLUCINATIES = re.compile(
    r"ondertitel|amara\.org|bedankt voor het kijken|bedankt voor het luisteren|"
    r"abonneer|tv gelderland|omroep|thanks for watching|www\.|\.nl\b|\.com\b",
    re.I)


GEEN_UITZENDING = re.compile(
    r"geachte luisteraar|bericht wordt herhaald|totdat de uitzend|geen uitzending"
    r"|op dit moment (?:is er )?(?:geen )?(?:uit)?zending",
    re.I)


def is_geen_uitzending(tekst: str) -> bool:
    """De automatische melding van kerkdienstgemist als er niets wordt uitgezonden."""
    return bool(GEEN_UITZENDING.search(tekst or ""))


def _woorden(s: str) -> list[str]:
    return re.findall(r"\w+", (s or "").lower())


def is_echo(tekst: str, woordenlijst: str) -> bool:
    """Whisper zegt bij stilte of muziek soms de woordenlijst op ('Heere, Jezus Christus, Heilige
    Geest, Heilige Geest, ...'). Zo'n uitkomst bestaat vrijwel alleen uit woorden van die lijst."""
    w = _woorden(tekst)
    lijst = set(_woorden(woordenlijst))
    if len(w) < 4 or not lijst:
        return False
    deel = sum(x in lijst for x in w) / len(w)
    herhaald = len(w) >= 6 and len(set(w)) <= len(w) / 2
    return deel >= 0.8 and (len(w) >= 6 or herhaald)


def _herhaling_weg(tekst: str) -> str:
    """'Heilige Geest, Heilige Geest, Heilige Geest, Heilige Geest' -> één keer."""
    return re.sub(r"(\b[\w']+(?:\s+[\w']+){0,3}\b)(?:[,;]?\s+\1\b){2,}", r"\1", tekst, flags=re.I)


def schoon(tekst: str, woordenlijst: str = "") -> str:
    tekst = re.sub(r"\s+", " ", tekst or "").strip()
    if not re.search(r"\w", tekst):
        return ""
    if is_echo(tekst, woordenlijst):
        return ""
    tekst = _herhaling_weg(tekst)
    zinnen = re.split(r"(?<=[.!?])\s+", tekst)
    zinnen = [z for z in zinnen if not HALLUCINATIES.search(z)]
    # herhalingen ('Amen. Amen. Amen. Amen.') beperken
    uit: list[str] = []
    for z in zinnen:
        if len(uit) >= 2 and z == uit[-1] == uit[-2]:
            continue
        uit.append(z)
    return " ".join(uit).strip()


def _cuda_dlls_windows():
    """Op Windows de CUDA-bestanden uit de pip-pakketten nvidia-cublas/cudnn vindbaar maken."""
    import os
    import sys
    if sys.platform != "win32":
        return
    import site
    from pathlib import Path
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        for bin_ in Path(sp).glob("nvidia/*/bin"):
            os.add_dll_directory(str(bin_))
            os.environ["PATH"] = str(bin_) + os.pathsep + os.environ.get("PATH", "")


def heeft_cuda() -> bool:
    _cuda_dlls_windows()
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def gpu_info() -> dict | None:
    """Naam, stuurprogramma, compute capability en geheugen van de (eerste) NVIDIA-kaart."""
    import shutil
    import subprocess
    if not shutil.which("nvidia-smi"):
        return None
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,compute_cap,memory.total",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
        naam, driver, cc, mem = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        return {"naam": naam, "driver": driver, "cc": float(cc), "geheugen_gb": float(mem) / 1024}
    except Exception:
        return None


def _proefaudio(sec: float) -> np.ndarray:
    """Spraakachtige ruis (geen stilte, anders slaat Whisper alles over)."""
    rng = np.random.default_rng(0)
    t = np.arange(int(RATE * sec)) / RATE
    return (rng.normal(0, 1, t.size) * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)) * 0.2).astype(np.float32)


class FasterWhisper:
    def __init__(self, model: str, apparaat: str, rekentype: str = "auto", tegelijk: int = 1,
                 zuinig: bool = False):
        _cuda_dlls_windows()
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError("faster-whisper is niet geïnstalleerd: pip install faster-whisper") from e
        if apparaat == "auto":
            apparaat = "cuda" if heeft_cuda() else "cpu"
        self.beam = 5
        self.tegelijk = 1
        if apparaat == "cuda":
            if self._laad_gpu(WhisperModel, model, rekentype, tegelijk, zuinig):
                return
            model = "small"
        if model == "auto" or model.startswith("large"):
            model = "small"  # large-modellen zijn op een processor veel te traag voor live
        import os
        log.info("Whisper-model %s laden op de processor (%d kernen)…", model, os.cpu_count() or 1)
        self.model = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
        self.beam = 1  # sneller; op een processor telt elke seconde
        self.apparaat = "cpu"

    def _laad_gpu(self, WhisperModel, model: str, rekentype: str, tegelijk: int, zuinig: bool = False) -> bool:
        """Model op de videokaart laden, met het snelste rekentype dat deze kaart echt aankan.

        Blackwell (RTX 50 / RTX PRO 2000-6000 Blackwell, compute capability 12.x) kan in
        CTranslate2 geen int8 via cuBLAS ('CUBLAS_STATUS_NOT_SUPPORTED'); float16 werkt wel en
        is met de Tensor Cores ook snel. Elk rekentype wordt met een proefrun gecontroleerd.
        """
        import time
        info = gpu_info() or {}
        blackwell = info.get("cc", 0) >= 10
        gb = info.get("geheugen_gb", 0)
        if info:
            log.info("Videokaart: %s, %.0f GB, stuurprogramma %s, compute capability %.1f",
                     info["naam"], gb, info["driver"], info["cc"])
        if blackwell and info.get("driver") and _versie(info["driver"]) < (572, 0):
            log.warning("Het stuurprogramma (%s) is te oud voor Blackwell; installeer de nieuwste "
                        "NVIDIA-driver (572 of hoger) via de NVIDIA App.", info["driver"])
        if rekentype == "auto":
            volgorde = ["float16", "bfloat16", "float32"] if blackwell else ["float16", "int8_float16", "float32"]
        else:
            volgorde = [rekentype]
        # Twee kerken tegelijk: op een videokaart is één werker meestal snel genoeg (om de beurt,
        # een fractie van een seconde per stuk). Alleen bij ruim geheugen een tweede kopie, zodat er
        # naast Whisper ook plaats blijft voor een vertaalmodel (Ollama) op dezelfde kaart.
        werkers = max(1, min(tegelijk, 2 if gb >= 20 else 1))
        if model != "auto":
            kandidaten = [model]
        elif gb == 0 or gb >= 12 or (gb >= 6 and not zuinig):
            kandidaten = ["large-v3", "large-v3-turbo"]
        else:
            # kleinere kaart die ook het vertaalmodel (Ollama) moet dragen: turbo is half zo groot
            kandidaten = ["large-v3-turbo", "medium"]
        for naam in kandidaten:
            for rt in volgorde:
                try:
                    log.info("Whisper-model %s laden op de videokaart (%s, %d tegelijk)…", naam, rt, werkers)
                    m = WhisperModel(naam, device="cuda", compute_type=rt, num_workers=werkers)
                    proef = _proefaudio(15)

                    def meet():
                        t0 = time.time()
                        list(m.transcribe(proef, language="nl", beam_size=5, vad_filter=False,
                                          condition_on_previous_text=False, max_new_tokens=60)[0])
                        return (time.time() - t0) / 15
                    # De eerste keer is altijd traag: de kaart vertaalt dan nog rekenkernen voor deze
                    # nieuwe chip (Blackwell) en reserveert geheugen. Pas de tweede meting telt.
                    meet()
                    rtf = meet()
                except Exception as e:
                    log.warning("  %s met %s lukt niet op deze kaart: %s", naam, rt, e)
                    continue
                log.info("  15 s geluid in %.1f s verwerkt (%s, %s)", rtf * 15, naam, rt)
                if model == "auto" and rtf > 0.35 and naam != kandidaten[-1]:
                    log.info("  te traag voor live met twee kerken; sneller model proberen")
                    del m
                    break
                self.model, self.apparaat, self.rekentype, self.tegelijk = m, "cuda", rt, werkers
                self.modelnaam = naam
                return True
        log.error("Videokaart werkt niet met Whisper. Terugval op de processor met model 'small'. "
                  "Zie LEESMIJ → Problemen.")
        return False

    def _run(self, audio: np.ndarray, prompt: str) -> str:
        segs, _ = self.model.transcribe(
            audio, language="nl", beam_size=self.beam, vad_filter=True,
            initial_prompt=prompt or None, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segs
                        if s.no_speech_prob < 0.6 and s.avg_logprob > -1.0)

    async def transcribeer(self, audio: np.ndarray, prompt: str) -> str:
        return await asyncio.to_thread(self._run, audio, prompt)


def _versie(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split(".")[:2])
    except ValueError:
        return (0, 0)


def wav_bytes(audio: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


class OpenAISpraak:
    URL = "https://api.openai.com/v1/audio/transcriptions"

    def __init__(self, sleutel: str, model: str):
        if not sleutel:
            raise RuntimeError("Geen OpenAI-sleutel ingesteld (config.toml → [sleutels] openai).")
        self.sleutel, self.model = sleutel, model

    def _run(self, audio: np.ndarray, prompt: str) -> str:
        grens = uuid.uuid4().hex
        delen = []
        for naam, waarde in (("model", self.model), ("language", "nl"),
                             ("response_format", "json"), ("prompt", prompt[-800:])):
            delen.append(f'--{grens}\r\nContent-Disposition: form-data; name="{naam}"\r\n\r\n{waarde}\r\n'.encode())
        delen.append(f'--{grens}\r\nContent-Disposition: form-data; name="file"; filename="f.wav"\r\n'
                     f"Content-Type: audio/wav\r\n\r\n".encode() + wav_bytes(audio) + b"\r\n")
        delen.append(f"--{grens}--\r\n".encode())
        req = urllib.request.Request(self.URL, data=b"".join(delen), method="POST", headers={
            "Authorization": f"Bearer {self.sleutel}",
            "Content-Type": f"multipart/form-data; boundary={grens}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r).get("text", "")

    async def transcribeer(self, audio: np.ndarray, prompt: str) -> str:
        for poging in range(3):
            try:
                return await asyncio.to_thread(self._run, audio, prompt)
            except Exception as e:
                log.warning("OpenAI-spraak mislukt (poging %d): %s", poging + 1, e)
                await asyncio.sleep(1 + poging * 2)
        return ""


def maak(cfg):
    """Kiest de spraakherkenning. Bij "auto": videokaart > OpenAI > processor."""
    engine = cfg.spraak_engine
    if engine == "auto":
        if heeft_cuda():
            engine, cfg.apparaat = "faster-whisper", "cuda"
            log.info("NVIDIA-videokaart gevonden: spraakherkenning op deze computer")
        elif cfg.openai_key:
            engine = "openai"
            log.info("Geen geschikte videokaart: spraakherkenning via OpenAI")
        else:
            engine, cfg.apparaat = "faster-whisper", "cpu"
            log.warning("Geen videokaart en geen OpenAI-sleutel: spraakherkenning op de processor. "
                        "Op een oudere laptop kan de tekst dan achterlopen; zie LEESMIJ.")
    cfg.spraak_gekozen = engine
    if engine == "faster-whisper":
        # vertaalt Ollama op dezelfde videokaart, dan het geheugen delen
        zuinig = cfg.vertaal_engine != "uit" and cfg.vertaal_api_url.startswith(("http://localhost", "http://127.0.0.1"))
        return FasterWhisper(cfg.model, cfg.apparaat, cfg.rekentype, len(cfg.kerken), zuinig)
    if engine == "openai":
        return OpenAISpraak(cfg.openai_key, cfg.openai_stt_model)
    return None
