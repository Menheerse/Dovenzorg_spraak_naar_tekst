"""Het geluid van de dienst doorgeven aan de telefoons (luisteren én meelezen).

De ffmpeg die het geluid voor de spraakherkenning ophaalt, maakt er tegelijk een mp3 van
(geen tweede verbinding met de zender). Die mp3 komt hier binnen en gaat naar iedereen die
luistert. Wie begint met luisteren, krijgt het geluid van een paar seconden geleden: zo loopt het
geluid ongeveer gelijk op met de tekst, die pas verschijnt als een zin is uitgesproken.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque

BEWAAR = 60.0   # seconden geluid in het geheugen


def _frame_begin(data: bytes) -> int:
    """Positie van het eerste mp3-frame (synchronisatiewoord), zodat de speler netjes kan beginnen."""
    for i in range(len(data) - 1):
        if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0 and (data[i + 1] & 0x06) != 0:
            return i
    return 0


class Uitzending:
    def __init__(self):
        self.buffer: deque[tuple[float, bytes]] = deque()
        self.luisteraars: set[asyncio.Queue] = set()
        self.laatst = 0.0

    @property
    def actief(self) -> bool:
        """Komt er op dit moment geluid binnen?"""
        return time.monotonic() - self.laatst < 5

    def voed(self, stuk: bytes):
        nu = time.monotonic()
        self.laatst = nu
        self.buffer.append((nu, stuk))
        while self.buffer and nu - self.buffer[0][0] > BEWAAR:
            self.buffer.popleft()
        for q in list(self.luisteraars):
            try:
                q.put_nowait(stuk)
            except asyncio.QueueFull:
                pass   # trage verbinding: dit stukje overslaan, de speler herstelt zich

    async def luister(self, vertraging: float):
        """Geeft mp3-bytes: eerst het geluid van `vertraging` seconden geleden, daarna live."""
        q: asyncio.Queue = asyncio.Queue(maxsize=400)
        grens = time.monotonic() - max(0.0, vertraging)
        oud = [s for t, s in self.buffer if t >= grens]
        self.luisteraars.add(q)
        try:
            begonnen = False
            if oud:
                yield oud[0][_frame_begin(oud[0]):] + b"".join(oud[1:])
                begonnen = True
            while True:
                stuk = await q.get()
                if not begonnen:
                    stuk, begonnen = stuk[_frame_begin(stuk):], True
                yield stuk
        finally:
            self.luisteraars.discard(q)

    @property
    def aantal(self) -> int:
        return len(self.luisteraars)
