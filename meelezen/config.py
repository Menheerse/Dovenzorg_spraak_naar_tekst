"""Instellingen inlezen uit config.toml."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

BASIS = Path(__file__).resolve().parent.parent

TAALNAMEN = {
    "nl": ("Nederlands", "Dutch"),
    "en": ("English", "English"),
    "de": ("Deutsch", "German"),
    "fr": ("Français", "French"),
    "es": ("Español", "Spanish"),
    "pt": ("Português", "Portuguese"),
    "it": ("Italiano", "Italian"),
    "pl": ("Polski", "Polish"),
    "ro": ("Română", "Romanian"),
    "hu": ("Magyar", "Hungarian"),
    "uk": ("Українська", "Ukrainian"),
    "ru": ("Русский", "Russian"),
    "tr": ("Türkçe", "Turkish"),
    "ar": ("العربية", "Arabic"),
    "fa": ("فارسی", "Persian (Farsi)"),
    "ti": ("ትግርኛ", "Tigrinya"),
    "am": ("አማርኛ", "Amharic"),
    "so": ("Soomaali", "Somali"),
    "zh": ("中文", "Simplified Chinese"),
    "id": ("Bahasa Indonesia", "Indonesian"),
    "ko": ("한국어", "Korean"),
    "ja": ("日本語", "Japanese"),
}
RTL = {"ar", "fa"}


@dataclass
class Kerk:
    id: str
    naam: str
    stream_url: str
    plaats: str = ""


@dataclass
class Config:
    kerknaam: str = "Meelezen"
    poort: int = 8080
    stream_url: str = ""
    opnieuw_proberen: float = 20
    nieuwe_dienst_na: float = 5 * 60   # dienst afsluiten zoveel seconden na het laatste geluid
    min_fragment: float = 4.0
    max_fragment: float = 14.0
    pauze: float = 0.6
    stilte_drempel: float = 0.01
    opslag_map: str = ""
    opslag_opname: bool = True
    opslag_tekst: bool = True
    bewaar_dagen: int = 0
    spraak_engine: str = "auto"
    spraak_gekozen: str = ""
    model: str = "medium"
    apparaat: str = "auto"
    rekentype: str = "auto"
    luisteren: bool = True
    luister_kbps: int = 128
    luister_vertraging: float = 6.0
    openai_stt_model: str = "gpt-4o-transcribe"
    woordenlijst: str = ""
    vaste_teksten: bool = True     # voorgelezen Bijbel/psalmen/formulieren in de officiële tekst zetten
    muziek_aan: bool = True
    muziek_min_aanhoudend: float = 0.3
    zang_min_vlakheid: float = 0.025
    spraak_niveau: float = 0.045
    vertaal_engine: str = "openai"
    openai_vertaal_model: str = "gpt-4o-mini"
    vertaal_api_url: str = "https://api.openai.com/v1"
    talen: list[str] = field(default_factory=list)
    openai_key: str = ""
    deepl_key: str = ""
    kerken: list[Kerk] = field(default_factory=list)

    @property
    def opslag(self) -> Path | None:
        return Path(self.opslag_map) if self.opslag_map.strip() else None


OUDE_WOORDENLIJST = "Heere, Jezus Christus, Heilige Geest, genade, verbond, gemeente, Psalm, Schriftlezing"
NIEUWE_WOORDENLIJST = ("Heere, Jezus Christus, Heilige Geest, gemeente, Schriftlezing, Psalm, gedachtenis, gedachtenismaaltijd, Heilig Avondmaal, avondmaalgangers, belijden, goedertierenheid, ijdellijk, toorn, zondaar, heirscharen, desgelijks, een iegelijk, noch, krachtiglijk, Middelharnis")


def _woordenlijst(w: str) -> str:
    """De oude standaardlijst automatisch vervangen door de uitgebreide; een eigen lijst blijft."""
    return NIEUWE_WOORDENLIJST if w.strip() in ("", OUDE_WOORDENLIJST) else w


def laad(pad: str | os.PathLike | None = None) -> Config:
    pad = Path(pad or os.environ.get("MEELEZEN_CONFIG") or BASIS / "config.toml")
    voorbeeld = BASIS / "config.voorbeeld.toml"
    if not pad.exists() and voorbeeld.exists():
        import shutil
        shutil.copy(voorbeeld, pad)   # eerste keer: eigen config.toml maken (updates overschrijven die niet)
    with open(pad, "rb") as f:
        d = tomllib.load(f)
    a, au, op, sp, vt, sl, mu = (d.get(k, {}) for k in
                                 ("algemeen", "audio", "opslag", "spraak", "vertaling", "sleutels", "muziek"))
    c = Config(
        kerknaam=a.get("kerknaam", "Meelezen"),
        poort=int(a.get("poort", 8080)),
        stream_url=au.get("stream_url", ""),
        opnieuw_proberen=float(au.get("opnieuw_proberen", 20)),
        nieuwe_dienst_na=float(au.get("afsluiten_na_minuten", 5)) * 60,
        min_fragment=float(au.get("min_fragment", 4.0)),
        max_fragment=float(au.get("max_fragment", 14.0)),
        pauze=float(au.get("pauze", 0.6)),
        stilte_drempel=float(au.get("stilte_drempel", 0.01)),
        opslag_map=str(op.get("map", "")),
        opslag_opname=bool(op.get("opname", True)),
        opslag_tekst=bool(op.get("tekst", True)),
        bewaar_dagen=int(op.get("bewaar_dagen", 0)),
        spraak_engine=sp.get("engine", "auto"),
        model=sp.get("model", "auto"),
        apparaat=sp.get("apparaat", "auto"),
        rekentype=sp.get("rekentype", "auto"),
        luisteren=bool(d.get("luisteren", {}).get("aan", True)),
        luister_kbps=int(d.get("luisteren", {}).get("kbps", 128)),
        luister_vertraging=float(d.get("luisteren", {}).get("vertraging", 6)),
        openai_stt_model=sp.get("openai_model", "gpt-4o-transcribe"),
        woordenlijst=_woordenlijst(sp.get("woordenlijst", "")),
        vaste_teksten=bool(sp.get("vaste_teksten", True)),
        muziek_aan=bool(mu.get("herkennen", True)),
        muziek_min_aanhoudend=float(mu.get("min_aanhoudend", 0.3)),
        zang_min_vlakheid=float(mu.get("zang_min_vlakheid", 0.025)),
        spraak_niveau=float(mu.get("spraak_niveau", 0.045)),
        vertaal_engine=vt.get("engine", "openai"),
        openai_vertaal_model=vt.get("openai_model", "gpt-4o-mini"),
        vertaal_api_url=vt.get("api_url", "https://api.openai.com/v1").rstrip("/"),
        talen=[t for t in vt.get("talen", []) if t in TAALNAMEN and t != "nl"],
        openai_key=sl.get("openai") or os.environ.get("OPENAI_API_KEY", ""),
        deepl_key=sl.get("deepl") or os.environ.get("DEEPL_API_KEY", ""),
    )
    for k in d.get("kerk", []):
        if k.get("id") and k.get("naam"):
            c.kerken.append(Kerk(str(k["id"]), k["naam"], k.get("stream_url", ""), k.get("plaats", "")))
    if not c.kerken:  # oude instelling met één stream
        c.kerken = [Kerk("kerk", c.kerknaam, c.stream_url)]
    if c.vertaal_engine == "uit":
        c.talen = []
    return c
