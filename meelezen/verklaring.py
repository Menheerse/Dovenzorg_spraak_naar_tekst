"""Bijbelverklaring van Matthew Henry (Nederlandse uitgave) uit data/henry.db."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import unicodedata
from pathlib import Path

log = logging.getLogger("meelezen.verklaring")

ALIAS = {"korinthiers": "korinthe", "corinthiers": "korinthe", "corinthe": "korinthe", "colossenzen": "kolossenzen",
         "matteus": "mattheus", "timoteus": "timotheus", "hebreers": "hebreeen", "efeziers": "efeze",
         "filippiers": "filippenzen", "openbaringen": "openbaring", "psalm": "psalmen"}


def sleutel(naam: str) -> str:
    s = unicodedata.normalize("NFKD", naam).encode("ascii", "ignore").decode().lower()
    m = re.match(r"^\s*([1-3])?\s*(.+)$", s)
    nr, rest = (m.group(1) or ""), re.sub(r"[^a-z]", "", m.group(2))
    return nr + ALIAS.get(rest, rest)


class Verklaring:
    def __init__(self, pad: Path):
        self.pad = pad
        self.boeken: dict[str, str] = {}   # sleutel -> naam in de database
        self._mtime = None
        self.ververs()

    @property
    def aan(self) -> bool:
        return bool(self.boeken)

    def ververs(self):
        try:
            mtime = self.pad.stat().st_mtime
        except OSError:
            self.boeken = {}
            return
        if mtime == self._mtime:
            return
        try:
            with sqlite3.connect(f"file:{self.pad}?mode=ro", uri=True) as db:
                self.boeken = {sleutel(n): n for (n,) in db.execute("SELECT naam FROM boek")}
            self._mtime = mtime
            log.info("bijbelverklaring geladen: %d boeken", len(self.boeken))
        except sqlite3.Error as e:
            log.error("bijbelverklaring kon niet worden gelezen: %s", e)
            self.boeken = {}

    def _naam(self, boek: str) -> str | None:
        k = sleutel(boek)
        if k in self.boeken:
            return self.boeken[k]
        kandidaten = [n for s, n in self.boeken.items() if s.startswith(k[:5]) and s[:1] == k[:1]]
        return kandidaten[0] if len(kandidaten) == 1 else None

    def hoofdstuk(self, boek: str, h: int) -> dict | None:
        self.ververs()
        naam = self._naam(boek)
        if not naam:
            return None
        with sqlite3.connect(f"file:{self.pad}?mode=ro", uri=True) as db:
            rijen = db.execute("SELECT van, tot, kop, tekst FROM deel WHERE boek=? AND h=? ORDER BY volgorde",
                               (naam, h)).fetchall()
            inleiding = None
            if h == 1:
                r = db.execute("SELECT inleiding FROM boek WHERE naam=?", (naam,)).fetchone()
                inleiding = json.loads(r[0]) if r and r[0] else None
        if not rijen and not inleiding:
            return None
        return {"boek": boek, "h": h, "boekinleiding": inleiding,
                "delen": [{"van": v, "tot": t, "kop": k, "tekst": json.loads(x)} for v, t, k, x in rijen]}
