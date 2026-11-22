"""Geluid binnenhalen met ffmpeg en opknippen bij pauzes in de spraak."""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import AsyncIterator

import numpy as np

log = logging.getLogger("meelezen.audio")
RATE = 16000
FRAME = 480  # 30 ms


def ffmpeg_pad() -> str:
    pad = shutil.which("ffmpeg")
    if not pad:
        raise RuntimeError("ffmpeg niet gevonden. Installeer ffmpeg (zie LEESMIJ).")
    return pad


VANAF = 0.0  # testen: start zoveel seconden in een bestand

YOUTUBE = ("youtube.com/", "youtu.be/")


def is_youtube(url: str) -> bool:
    return any(y in url for y in YOUTUBE)


async def youtube_live_url(url: str) -> str | None:
    """Zoekt het directe geluidsadres van een YouTube-livestream. None = nu niet live."""
    import sys
    cmd = [sys.executable, "-m", "yt_dlp", "-g", "--no-warnings", "--no-playlist",
           "--match-filter", "is_live", "-f", "bestaudio/worst", url]
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), 90)
    except FileNotFoundError:
        log.error("yt-dlp ontbreekt: voer installeren.bat opnieuw uit")
        return None
    except asyncio.TimeoutError:
        log.warning("YouTube reageert niet")
        return None
    regels = [r for r in out.decode(errors="replace").splitlines() if r.startswith("http")]
    if proc.returncode != 0 or not regels:
        melding = err.decode(errors="replace").strip().splitlines()
        if melding:
            log.info("YouTube: %s", melding[-1][:200])
        return None
    return regels[0]


def _invoer(url: str, realtime: bool) -> list[str]:
    if url.startswith(("http://", "https://")):
        return ["-reconnect", "1", "-reconnect_streamed", "1",
                "-reconnect_delay_max", "10", "-rw_timeout", "15000000", "-i", url]
    return (["-re"] if realtime else []) + (["-ss", str(VANAF)] if VANAF else []) + ["-i", url]


async def pcm(url: str, realtime_bestand: bool = True, geluid=None, kbps: int = 128) -> AsyncIterator[bytes]:
    """Geeft 16 kHz mono 16-bit PCM uit de stream. Stopt als de stream eindigt.

    geluid: functie die mp3-stukjes krijgt om door te geven aan luisteraars. ffmpeg maakt die mp3
    uit dezelfde verbinding (tweede uitvoer via een lokale TCP-poort), dus geen extra belasting
    voor de zender en het geluid loopt precies gelijk met wat de spraakherkenning hoort.
    """
    server = None
    extra: list[str] = []
    if geluid is not None:
        async def ontvang(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            try:
                while True:
                    stuk = await reader.read(8192)
                    if not stuk:
                        break
                    geluid(stuk)
            finally:
                writer.close()
        try:
            server = await asyncio.start_server(ontvang, "127.0.0.1", 0)
            poort = server.sockets[0].getsockname()[1]
            extra = ["-vn", "-c:a", "libmp3lame", "-b:a", f"{kbps}k", "-ar", "44100",
                     "-f", "mp3", f"tcp://127.0.0.1:{poort}"]
        except OSError as e:
            log.warning("geluid doorgeven lukt niet: %s", e)
    cmd = [ffmpeg_pad(), "-nostdin", "-hide_banner", "-loglevel", "error",
           *_invoer(url, realtime_bestand), "-vn", "-ac", "1", "-ar", str(RATE),
           "-f", "s16le", "-", *extra]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        while True:
            data = await proc.stdout.read(FRAME * 2 * 16)
            if not data:
                break
            yield data
    finally:
        if proc.returncode is None:
            proc.kill()
        err = (await proc.stderr.read()).decode(errors="replace").strip()
        await proc.wait()
        if server:
            server.close()
        if err:
            log.info("ffmpeg: %s", err[-300:])


class Knipper:
    """Verzamelt geluid en knipt het in fragmenten bij een pauze.

    De drempel voor stilte past zich aan het achtergrondgeluid aan.
    """

    def __init__(self, min_s=4.0, max_s=14.0, pauze_s=0.6, drempel=0.01):
        self.min_n = int(min_s * RATE)
        self.max_n = int(max_s * RATE)
        self.pauze_frames = max(1, int(pauze_s * RATE / FRAME))
        self.drempel = drempel
        self.rest = b""
        self.frames: list[np.ndarray] = []
        self.rms: list[float] = []
        self.vloer = drempel / 3
        self.stil = 0
        self.totaal = 0        # aantal samples gezien
        self.frames_start = 0  # sample-positie van frames[0]

    def _drempel(self) -> float:
        # Achtergrondruis volgen: zakt direct mee, stijgt maar langzaam (verdubbelt in ~1 minuut).
        # Zo telt aanhoudend orgelspel niet als 'stilte', maar past de drempel zich wel aan de zender aan.
        return min(max(self.drempel, self.vloer * 3), self.drempel * 4)

    def voed(self, data: bytes) -> list[tuple[np.ndarray, float]]:
        """Geeft een lijst (geluid, starttijd in seconden)."""
        uit = []
        data = self.rest + data
        n = len(data) // (FRAME * 2) * FRAME * 2
        self.rest = data[n:]
        samples = np.frombuffer(data[:n], dtype=np.int16).astype(np.float32) / 32768.0
        for i in range(0, len(samples), FRAME):
            fr = samples[i:i + FRAME]
            r = float(np.sqrt(np.mean(fr * fr)))
            self.vloer = r if r < self.vloer else self.vloer * 1.0003
            if not self.frames:
                self.frames_start = self.totaal
            self.totaal += len(fr)
            self.frames.append(fr)
            self.rms.append(r)
            self.stil = self.stil + 1 if r < self._drempel() else 0
            lengte = len(self.frames) * FRAME
            if lengte >= self.min_n and self.stil >= self.pauze_frames:
                uit += self._knip(len(self.frames))
            elif lengte >= self.max_n:
                # knip op het stilste moment in de laatste 40%
                start = int(len(self.rms) * 0.6)
                idx = start + int(np.argmin(self.rms[start:])) + 1
                uit += self._knip(idx)
            elif self.stil > 2 * RATE / FRAME and self.stil == len(self.frames):
                self.frames, self.rms = [], []  # alleen stilte: weggooien
        return uit

    def _knip(self, idx: int) -> list[tuple[np.ndarray, float]]:
        frames, rms = self.frames[:idx], self.rms[:idx]
        self.frames, self.rms = self.frames[idx:], self.rms[idx:]
        start = self.frames_start / RATE
        self.frames_start += idx * FRAME
        self.stil = 0
        d = self._drempel()
        spraak = sum(1 for r in rms if r >= d)
        if spraak < 0.15 * len(rms):
            return []
        return [(np.concatenate(frames), start)]

    def leeg(self) -> list[tuple[np.ndarray, float]]:
        return self._knip(len(self.frames)) if self.frames else []


class Opnemer:
    """Neemt de stream ongewijzigd op naar een bestand (los van de transcriptie)."""

    def __init__(self, url: str):
        self.url = url
        self.kopie = True  # mp3-stream ongewijzigd opslaan; anders omzetten naar mp3
        self.proc: asyncio.subprocess.Process | None = None
        self.taak: asyncio.Task | None = None
        self.bestand: Path | None = None
        self.delen: list[tuple[Path, float]] = []   # (bestand, starttijd)
        # geeft True zolang de zender alleen de melding 'geen uitzending' laat horen
        self.wachten = lambda: False

    def start(self, bestand: Path):
        if self.taak and not self.taak.done():
            return
        self.bestand = bestand
        self.delen = []
        self.taak = asyncio.create_task(self._loop())

    async def _loop(self):
        deel = 1
        while True:
            # De zender speelt de melding 'geen uitzending' (steeds een kort los bestandje):
            # dan geen nieuwe opnamedelen maken, maar wachten tot er weer echt geluid is.
            while deel > 1 and self.wachten():
                await asyncio.sleep(5)
            doel = self.bestand if deel == 1 else self.bestand.with_name(
                f"{self.bestand.stem}_deel{deel}{self.bestand.suffix}")
            try:
                doel.parent.mkdir(parents=True, exist_ok=True)
                codec = ["-c:a", "copy"] if self.kopie else ["-c:a", "libmp3lame", "-b:a", "96k"]
                cmd = [ffmpeg_pad(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                       *_invoer(self.url, False), "-vn", *codec, "-f", "mp3", str(doel)]
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
                self.delen.append((doel, time.time()))
                err = (await self.proc.stderr.read()).decode(errors="replace").strip()
                await self.proc.wait()
                if err:
                    log.warning("opname: %s", err[-300:])
            except asyncio.CancelledError:
                raise
            except Exception as e:  # NAS weg, schijf vol, ...
                log.warning("opname mislukt (%s): %s", doel, e)
            if doel.exists() and doel.stat().st_size > 0:
                if deel > 1 and self.wachten():
                    doel.unlink(missing_ok=True)       # alleen de melding opgenomen
                    self.delen = [d for d in self.delen if d[0] != doel]
                else:
                    deel += 1
            await asyncio.sleep(10)

    async def stop(self, laatste_geluid: float | None = None):
        """Opname afsluiten. Met laatste_geluid wordt de stilte aan het eind eraf geknipt."""
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()  # ffmpeg sluit het mp3-bestand netjes af
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except asyncio.TimeoutError:
                self.proc.kill()
        if self.taak:
            self.taak.cancel()
            try:
                await self.taak
            except (asyncio.CancelledError, Exception):
                pass
        self.taak = self.proc = None
        if laatste_geluid and self.delen:
            await self._inkorten(laatste_geluid)

    async def _inkorten(self, laatste_geluid: float, marge: float = 30):
        # delen die pas ná het laatste geluid begonnen, bevatten alleen stilte of de melding
        while len(self.delen) > 1 and self.delen[-1][1] > laatste_geluid + marge:
            oud, _ = self.delen.pop()
            oud.unlink(missing_ok=True)
        bestand, begin = self.delen[-1]
        houden = laatste_geluid - begin + marge
        if not bestand.exists():
            return
        if houden <= 0 and len(self.delen) > 1:
            bestand.unlink(missing_ok=True)   # dit deel was alleen stilte
            return
        tmp = bestand.with_name(bestand.stem + ".tmp.mp3")
        try:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_pad(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(bestand),
                "-t", f"{max(houden, 1):.1f}", "-c", "copy", str(tmp),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await proc.wait()
            if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(bestand)
                log.info("opname ingekort tot %.0f s na het laatste geluid", marge)
        except Exception as e:
            log.warning("inkorten opname mislukt: %s", e)
        finally:
            tmp.unlink(missing_ok=True)
