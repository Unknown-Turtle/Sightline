"""Microsoft Foundry access through the official `openai` Azure client.

Configuration comes from environment variables:
- FOUNDRY_ENDPOINT    the Azure OpenAI / Foundry project endpoint
- FOUNDRY_DEPLOYMENT  the chat deployment name
- FOUNDRY_API_KEY     optional; without it DefaultAzureCredential is used (managed identity in
                      Azure, `az login` locally)

With nothing set, `Foundry.configured` is False and the pipeline runs in fallback mode:
the same steps, template phrasing, no model calls. Every call has a 20 s timeout,
temperature 0.3 and at most 400 output tokens.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

TIMEOUT_S = 20.0
TEMPERATURE = 0.3
MAX_OUTPUT_TOKENS = 400
API_VERSION = "2024-10-21"
TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"


@dataclass
class LLMReply:
    text: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    model: str


class Foundry:
    def __init__(self, endpoint: str | None = None, deployment: str | None = None, api_key: str | None = None):
        self.endpoint = endpoint or os.environ.get("FOUNDRY_ENDPOINT")
        self.deployment = deployment or os.environ.get("FOUNDRY_DEPLOYMENT")
        self.api_key = api_key or os.environ.get("FOUNDRY_API_KEY")
        self._client = None
        self.error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.deployment)

    def _get_client(self):
        if self._client is not None:
            return self._client
        from openai import AzureOpenAI
        kwargs = {"azure_endpoint": self.endpoint, "api_version": API_VERSION, "timeout": TIMEOUT_S, "max_retries": 6}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            kwargs["azure_ad_token_provider"] = get_bearer_token_provider(DefaultAzureCredential(), TOKEN_SCOPE)
        self._client = AzureOpenAI(**kwargs)
        return self._client

    def chat(self, system: str, user: str) -> LLMReply | None:
        """One chat completion. Returns None on any failure (the caller falls back)."""
        if not self.configured:
            return None
        started = time.perf_counter()
        try:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=self.deployment,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=TEMPERATURE, max_tokens=MAX_OUTPUT_TOKENS, timeout=TIMEOUT_S,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001 - any SDK or network failure means fallback
            self.error = f"{type(exc).__name__}: {exc}"
            return None
        latency = int((time.perf_counter() - started) * 1000)
        usage = getattr(resp, "usage", None)
        text = (resp.choices[0].message.content or "") if resp.choices else ""
        return LLMReply(text=text, latency_ms=latency,
                        tokens_in=int(getattr(usage, "prompt_tokens", 0) or 0),
                        tokens_out=int(getattr(usage, "completion_tokens", 0) or 0),
                        model=getattr(resp, "model", None) or self.deployment)


def parse_json_object(text: str) -> dict | None:
    """Parse a JSON object from a model reply, tolerating code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            obj = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, dict) else None
