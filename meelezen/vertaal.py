"""Vertalen van zinnen: OpenAI-compatibel (OpenAI of Ollama) of DeepL."""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request

from .config import TAALNAMEN

log = logging.getLogger("meelezen.vertaling")

DEEPL_CODES = {"en": "EN-GB", "de": "DE", "fr": "FR", "es": "ES", "pt": "PT-PT", "it": "IT",
               "pl": "PL", "ro": "RO", "hu": "HU", "uk": "UK", "ru": "RU", "tr": "TR", "ar": "AR",
               "zh": "ZH-HANS", "id": "ID", "ko": "KO", "ja": "JA"}


def _post(url: str, data: bytes, headers: dict, timeout=30) -> dict:
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class OpenAIVertaler:
    def __init__(self, sleutel: str, model: str, api_url: str):
        self.sleutel, self.model, self.url = sleutel, model, api_url + "/chat/completions"

    def _run(self, zin: str, taal: str, context: list[str]) -> str:
        naam = TAALNAMEN[taal][1]
        systeem = (
            f"You translate a Dutch church sermon, spoken live, into {naam}. "
            "Translate ONLY the sentence after 'TRANSLATE:'. The earlier sentences are context. "
            f"Use the established wording of common {naam} Bible translations for Bible books, "
            "names and quotations. Keep the tone reverent and natural. Output only the translation.")
        gebruiker = ""
        if context:
            gebruiker += "CONTEXT:\n" + "\n".join(context[-3:]) + "\n\n"
        gebruiker += "TRANSLATE:\n" + zin
        headers = {"Content-Type": "application/json"}
        if self.sleutel:
            headers["Authorization"] = f"Bearer {self.sleutel}"
        body = json.dumps({"model": self.model, "temperature": 0, "messages": [
            {"role": "system", "content": systeem}, {"role": "user", "content": gebruiker}]}).encode()
        r = _post(self.url, body, headers)
        return r["choices"][0]["message"]["content"].strip()

    def kan(self, taal: str) -> bool:
        return True

    async def vertaal(self, zin, taal, context):
        return await asyncio.to_thread(self._run, zin, taal, context)


class DeepLVertaler:
    def __init__(self, sleutel: str):
        self.sleutel = sleutel
        host = "api-free.deepl.com" if sleutel.endswith(":fx") else "api.deepl.com"
        self.url = f"https://{host}/v2/translate"

    def kan(self, taal: str) -> bool:
        return taal in DEEPL_CODES

    def _run(self, zin, taal, context):
        data = urllib.parse.urlencode({"text": zin, "source_lang": "NL", "target_lang": DEEPL_CODES[taal],
                                       "context": " ".join(context[-3:])}).encode()
        r = _post(self.url, data, {"Authorization": f"DeepL-Auth-Key {self.sleutel}",
                                   "Content-Type": "application/x-www-form-urlencoded"})
        return r["translations"][0]["text"]

    async def vertaal(self, zin, taal, context):
        return await asyncio.to_thread(self._run, zin, taal, context)


class Vertaler:
    """Kiest per taal de juiste dienst; DeepL valt terug op OpenAI voor talen die DeepL niet kent."""

    def __init__(self, cfg):
        self.diensten = []
        if cfg.vertaal_engine == "deepl" and cfg.deepl_key:
            self.diensten.append(DeepLVertaler(cfg.deepl_key))
        lokaal = not cfg.vertaal_api_url.startswith("https://api.openai.com")
        if cfg.vertaal_engine in ("openai", "deepl") and (cfg.openai_key or lokaal):
            self.diensten.append(OpenAIVertaler(cfg.openai_key, cfg.openai_vertaal_model, cfg.vertaal_api_url))
        self.talen = [t for t in cfg.talen if any(d.kan(t) for d in self.diensten)]
        self.sem = asyncio.Semaphore(4)

    @property
    def aan(self) -> bool:
        return bool(self.diensten and self.talen)

    async def vertaal(self, zin: str, taal: str, context: list[str]) -> str | None:
        for d in self.diensten:
            if not d.kan(taal):
                continue
            for poging in range(2):
                try:
                    async with self.sem:
                        return await d.vertaal(zin, taal, context)
                except Exception as e:
                    log.warning("vertalen naar %s mislukt: %s", taal, e)
                    await asyncio.sleep(1)
        return None
