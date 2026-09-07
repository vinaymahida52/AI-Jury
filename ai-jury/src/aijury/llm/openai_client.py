"""OpenAI-compatible chat client (HCNSEC and similar gateways).

Uses the official OpenAI SDK against a configurable base URL. Any OpenAI-compatible
gateway (HCNSEC, Tokenera, OpenAI, custom /v1) uses this client.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from aijury.llm.base import LLMResponse

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore[misc, assignment]


def extract_assistant_text(text: str) -> str:
    """Drop Qwen-style chain-of-thought that precedes the real answer.

    HCNSEC returns thinking in `message.content` before a `</think>` marker.
    Agents parse JSON from this text, so the preamble must not reach them.
    """
    marker = "</think>"
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return text.strip()


class OpenAICompatClient:
    def __init__(
        self,
        model: str,
        *,
        api_key: str,
        base_url: str,
        max_retries: int = 4,
        timeout: float = 120.0,
        seed: int | None = None,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("API key is not set for this gateway.")
        if not model:
            raise RuntimeError("Model is not set for this gateway.")
        if client is None:
            if OpenAI is None:
                raise RuntimeError(
                    "openai package not installed. Install with: pip install 'aijury[openai]'"
                )
            client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.model = model
        self._client = client
        self._max_retries = max_retries
        self._seed = seed

    async def complete(
        self,
        system: str,
        prompt: str,
        *,
        max_tokens: int = 2000,
        temperature: float = 0.7,
    ) -> LLMResponse:
        started = time.perf_counter()
        delay = 1.0
        last_exc: Exception | None = None
        for _ in range(self._max_retries):
            try:
                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    # HCNSEC chat.completions fields we actually use.
                    "temperature": min(2.0, max(0.0, temperature)),
                    "top_p": 1,
                    "max_tokens": max(1, max_tokens, 4096),
                    "frequency_penalty": 0,
                    "presence_penalty": 0,
                    "n": 1,
                    "stream": False,
                    "response_format": {"type": "json_object"},
                }
                if self._seed is not None:
                    payload["seed"] = self._seed
                completion = await asyncio.to_thread(
                    self._client.chat.completions.create,
                    **payload,
                )
                choice = completion.choices[0].message
                text = extract_assistant_text(choice.content or "")
                usage = getattr(completion, "usage", None)
                return LLMResponse(
                    text=text,
                    model=self.model,
                    tokens_in=int(getattr(usage, "prompt_tokens", 0) or 0),
                    tokens_out=int(getattr(usage, "completion_tokens", 0) or 0),
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            except Exception as exc:  # noqa: BLE001 - retry on transport/rate errors
                last_exc = exc
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError(f"OpenAI-compatible request failed after retries: {last_exc}")
