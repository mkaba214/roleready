"""NVIDIA API client (OpenAI-compatible chat completions on build.nvidia.com).

Plain httpx, so tests can swap in a mock transport. Retries with backoff on
HTTP 429 and 5xx. The API key travels only in the Authorization header and is
never logged or returned in errors.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

import httpx

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"


class LLMError(Exception):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    attempts: int = 1


class LLMClient(Protocol):
    def complete(self, system: str, user: str, *, max_tokens: int = 1024, temperature: float = 0.2) -> LLMResult: ...


class NvidiaClient:
    RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 15.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        disable_thinking: bool = True,
    ) -> None:
        if not api_key:
            raise ValueError("NVIDIA_API_KEY is not set")
        self.model = model
        self.max_retries = max_retries
        # Reasoning models (e.g. Nemotron) otherwise spend the whole max_tokens budget on hidden
        # reasoning and return empty content. If a model rejects the field, set NVIDIA_DISABLE_THINKING=false.
        self.disable_thinking = disable_thinking
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), 20.0)
            except ValueError:
                pass
        return float(min(2 ** (attempt - 1), 8))

    def complete(self, system: str, user: str, *, max_tokens: int = 1024, temperature: float = 0.2) -> LLMResult:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if self.disable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        started = time.monotonic()
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                resp = self._http.post("/chat/completions", json=payload)
            except httpx.TransportError as exc:  # includes timeouts
                if attempt < attempts:
                    self._sleep(self._backoff(attempt, None))
                    continue
                raise LLMError(f"NVIDIA API unreachable ({type(exc).__name__})") from None
            if resp.status_code in self.RETRY_STATUSES and attempt < attempts:
                self._sleep(self._backoff(attempt, resp.headers.get("retry-after")))
                continue
            if resp.status_code >= 400:
                raise LLMError(f"NVIDIA API returned HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                data = resp.json()
                message = data["choices"][0]["message"]
            except (ValueError, KeyError, IndexError, TypeError):
                raise LLMError("NVIDIA API returned an unexpected response shape") from None
            return LLMResult(
                text=message.get("content") or "",
                model=str(data.get("model") or self.model),
                usage=data.get("usage") or {},
                latency_ms=int((time.monotonic() - started) * 1000),
                attempts=attempt,
            )
        raise LLMError("NVIDIA API retries exhausted")  # pragma: no cover
