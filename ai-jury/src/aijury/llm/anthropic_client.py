"""Anthropic-backed client.

Model identifiers are never hardcoded — they come from Settings, so upgrading
models is a config change and this file does not go stale.
"""

from __future__ import annotations

import asyncio
import os
import time

from aijury.llm.base import LLMResponse


class AnthropicClient:
    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        max_retries: int = 4,
        timeout: float = 120.0,
    ) -> None:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "anthropic package not installed. Install with: pip install 'aijury[anthropic]'"
            ) from exc
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        if not model:
            raise RuntimeError("AIJURY_MODEL must be set when provider=anthropic.")
        self.model = model
        self._client = AsyncAnthropic(api_key=key, timeout=timeout)
        self._max_retries = max_retries

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
                message = await self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = "".join(
                    block.text for block in message.content if getattr(block, "type", "") == "text"
                )
                return LLMResponse(
                    text=text,
                    model=self.model,
                    tokens_in=message.usage.input_tokens,
                    tokens_out=message.usage.output_tokens,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            except Exception as exc:  # noqa: BLE001 - retry on any transport/rate error
                last_exc = exc
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError(f"Anthropic request failed after retries: {last_exc}")
