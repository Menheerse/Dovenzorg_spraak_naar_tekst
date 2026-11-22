"""Herkennen of een stuk geluid spraak, orgelspel of samenzang is.

Eenvoudige signaalkenmerken, alleen numpy:
- pauzes:   spraak heeft veel korte stiltes tussen lettergrepen en zinnen; muziek loopt door.
- aanhoudend: bij muziek blijft de hoofdtoon steeds een tijd (> 0,3 s) op dezelfde noot staan;
              bij spraak verandert hij bij elke lettergreep.
- vlakheid: een orgel alleen geeft scherpe, zuivere tonen; veel zingende stemmen maken het spectrum 'breder'.
De drempels staan in config.toml en zijn af te stellen met muziektest.bat.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .audio import RATE

FRAME = 480          # 30 ms voor energie
FFT = 2048           # 128 ms voor toonhoogte
HOP = 1024
_venster = np.hanning(FFT).astype(np.float32)
_freqs = np.fft.rfftfreq(FFT, 1 / RATE)
_toon = (_freqs >= 100) & (_freqs <= 1000)
_stem = (_freqs >= 300) & (_freqs <= 3000)
_breed = (_freqs >= 100) & (_freqs <= 4000)
_breed_f = _freqs[_breed]


@dataclass
class Kenmerken:
    pauzes: float     # aandeel stille stukjes (0-1); spraak hoog, muziek laag
    aanhoudend: float # aandeel tijd in aangehouden noten van > 0,3 s (0-1); muziek hoog
    vlakheid: float   # spectrale vlakheid 300-3000 Hz (0-1); zang hoger dan orgel
    luid: float = 0.0          # RMS-niveau van het stuk (0-1)
    zwaartepunt: float = 0.0   # spectraal zwaartepunt 100-4000 Hz; zang hoger dan orgel
    duur: float = 0.0          # lengte van het stuk in seconden

    def __str__(self):
        return (f"pauzes {self.pauzes:.2f}  aanhoudend {self.aanhoudend:.2f}  vlakheid {self.vlakheid:.3f}"
                f"  luid {self.luid:.3f}  zwaartepunt {self.zwaartepunt:.0f}")


def kenmerken(audio: np.ndarray) -> Kenmerken:
    audio = audio.astype(np.float32)
    n = len(audio) // FRAME
    if n < 20:
        return Kenmerken(1.0, 0.0, 0.0)
    rms = np.sqrt(np.mean(audio[:n * FRAME].reshape(n, FRAME) ** 2, axis=1)) + 1e-9
    pauzes = float(np.mean(rms < 0.35 * np.median(rms)))

    stappen = (len(audio) - FFT) // HOP
    if stappen < 8:
        return Kenmerken(pauzes, 0.0, 0.0)
    idx = np.arange(FFT)[None, :] + HOP * np.arange(stappen)[:, None]
    spec = np.abs(np.fft.rfft(audio[idx] * _venster, axis=1)) ** 2 + 1e-12
    luid = spec.sum(axis=1) > 0.2 * np.median(spec.sum(axis=1))   # stille frames niet meetellen
    piek = np.argmax(spec[:, _toon], axis=1)
    gelijk = (np.abs(np.diff(piek)) <= 1) & luid[1:] & luid[:-1]
    # lengte van elke reeks 'zelfde toon'; reeksen van >= 5 stappen (~0,32 s) tellen als aangehouden noot
    aangehouden, reeks = 0, 0
    for g in np.append(gelijk, False):
        if g:
            reeks += 1
        else:
            if reeks >= 5:
                aangehouden += reeks
            reeks = 0
    aanhoudend = float(aangehouden / max(1, len(gelijk)))
    s = spec[luid][:, _stem] if luid.any() else spec[:, _stem]
    vlak = np.exp(np.mean(np.log(s), axis=1)) / np.mean(s, axis=1)
    ls = spec[luid][:, _breed] if luid.any() else spec[:, _breed]
    zwaartepunt = float(np.median((ls * _breed_f).sum(axis=1) / ls.sum(axis=1)))
    niveau = float(np.sqrt(np.mean(audio ** 2)))
    return Kenmerken(pauzes, aanhoudend, float(np.median(vlak)), niveau, zwaartepunt, len(audio) / RATE)


def soort(k: Kenmerken, cfg, spraakniveau: float | None = None) -> str:
    """'spraak', 'orgel' of 'zang'.

    Afgesteld op een echte dienst (Ger. Gem., Pinksteren 2026, 1u49):
    - spraak:  veel korte pauzes (>= 0,15) en vrijwel geen aangehouden tonen;
    - muziek:  doorlopend (pauzes < 0,1), of aangehouden tonen met weinig pauzes;
    - zang t.o.v. orgel: twee van de drie kenmerken moeten 'zang' zeggen:
        * breder geluid (vlakheid >= zang_min_vlakheid),
        * duidelijk luider dan de spreker (gemeente zingt hard, orgel solo is zachter),
        * hoger spectraal zwaartepunt (stemmen; orgel zit laag).
    spraakniveau: gemeten RMS van gesproken woord in deze dienst (None = standaard).
    """
    doorlopend = k.pauzes < 0.1
    aangehouden = k.aanhoudend >= cfg.muziek_min_aanhoudend
    if not (doorlopend or (aangehouden and k.pauzes < 0.2)):
        return "spraak"
    if k.vlakheid >= 0.15:
        return "spraak"     # ruis, een losse uitgerekte klank of stilte met brom
    ref = spraakniveau or cfg.spraak_niveau
    stemmen = (k.vlakheid >= cfg.zang_min_vlakheid) + (k.luid >= 1.3 * ref) + (k.zwaartepunt >= 580)
    # veel lang aangehouden tonen is typisch orgel; dan moeten alle drie 'zang' zeggen
    nodig = 3 if k.aanhoudend >= 0.4 else 2
    return "zang" if stemmen >= nodig else "orgel"


class Niveau:
    """Houdt bij hoe luid er in deze dienst gesproken wordt (mediaan van recente spraakstukken)."""

    def __init__(self):
        self.waarden: list[float] = []

    def spraak(self, k: Kenmerken):
        if k.luid > 0.003:
            self.waarden = (self.waarden + [k.luid])[-200:]

    def waarde(self) -> float | None:
        return float(np.median(self.waarden)) if len(self.waarden) >= 5 else None


def soort_in_context(k: Kenmerken, cfg, hub, start: float) -> str:
    """Als soort(), maar met het spraakniveau van deze dienst, en een twijfelachtig stukje
    midden in muziek hoort bij die muziek (bijv. het begin van een regel)."""
    niveau = getattr(hub, "niveau", None)
    if niveau is None:
        niveau = hub.niveau = Niveau()
    s = soort(k, cfg, niveau.waarde())
    if s == "spraak" and k.pauzes < 0.2 and k.vlakheid < 0.15:
        bezig = hub.muziek_bezig(start)
        if bezig:
            return bezig
    if s != "spraak" and k.duur < 6 and not hub.muziek_bezig(start, binnen=25):
        s = "spraak"    # een los kort stukje (uitgerekt woord, brom) is nog geen muziek
    if s == "spraak":
        niveau.spraak(k)
    return s


LABELS = {"zang": "♪ Samenzang", "orgel": "♪ Orgelspel"}
