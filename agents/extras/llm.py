"""Minimal Azure AI Foundry (Azure OpenAI compatible) chat client with a fallback mode.

Configuration: FOUNDRY_ENDPOINT, FOUNDRY_DEPLOYMENT, and FOUNDRY_API_KEY or DefaultAzureCredential
(azure-identity, optional). With no endpoint or deployment set, `LLM.available` is False and callers
use template phrasing. Only the standard library is required.
"""
from __future__ import annotations

import json
import time
import urllib.request

from .common import foundry_config

API_VERSION = "2024-10-21"


class LLM:
    def __init__(self):
        self.cfg = foundry_config()
        self.model = self.cfg["deployment"] if self.cfg else None
        self._token: str | None = None

    @property
    def available(self) -> bool:
        return self.cfg is not None

    @property
    def mode(self) -> str:
        return "live" if self.available else "fallback"

    def _auth_header(self) -> dict:
        if self.cfg.get("api_key"):
            return {"api-key": self.cfg["api_key"]}
        if self._token is None:
            from azure.identity import DefaultAzureCredential  # optional dependency
            cred = DefaultAzureCredential()
            self._token = cred.get_token("https://cognitiveservices.azure.com/.default").token
        return {"Authorization": f"Bearer {self._token}"}

    def chat(self, system: str, user: str, max_tokens: int = 400, temperature: float = 0.2) -> dict:
        """Returns {"text", "latency_ms", "tokens_in", "tokens_out"}; raises on transport errors."""
        if not self.available:
            raise RuntimeError("no Foundry configuration")
        url = f"{self.cfg['endpoint']}/openai/deployments/{self.cfg['deployment']}/chat/completions?api-version={API_VERSION}"
        body = json.dumps({"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                           "max_tokens": max_tokens, "temperature": temperature}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **self._auth_header()})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        usage = data.get("usage") or {}
        return {"text": data["choices"][0]["message"]["content"], "latency_ms": int((time.time() - t0) * 1000),
                "tokens_in": usage.get("prompt_tokens", 0), "tokens_out": usage.get("completion_tokens", 0)}

    def chat_json(self, system: str, user: str, **kw) -> tuple[dict | None, dict]:
        res = self.chat(system, user, **kw)
        text = res["text"].strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("{"):]
        try:
            return json.loads(text[text.find("{"): text.rfind("}") + 1]), res
        except (ValueError, IndexError):
            return None, res
