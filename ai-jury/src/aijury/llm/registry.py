"""Client construction and juror model assignment."""

from __future__ import annotations

from aijury.config import Settings
from aijury.llm.base import LLMClient
from aijury.llm.gateways import is_openai_compat
from aijury.llm.mock import MockLLMClient


def build_client(settings: Settings, *, persona: str = "neutral", index: int = 0) -> LLMClient:
    """Return a client for one agent slot.

    When a model pool is configured, jurors are spread across it round-robin so
    that the jury's errors are not perfectly correlated.
    """
    if settings.provider == "mock":
        model = settings.model_pool[index % len(settings.model_pool)] if settings.model_pool else "mock-1"
        return MockLLMClient(model=model, persona=persona, seed=settings.seed + index)
    if settings.provider == "anthropic":
        from aijury.llm.anthropic_client import AnthropicClient

        model = (
            settings.model_pool[index % len(settings.model_pool)]
            if settings.model_pool
            else settings.model
        )
        return AnthropicClient(model=model)
    if is_openai_compat(settings.provider):
        from aijury.llm.openai_client import OpenAICompatClient

        model = (
            settings.model_pool[index % len(settings.model_pool)]
            if settings.model_pool
            else settings.model
        )
        if settings.provider == "hcnsec" and not model:
            model = "Qwen3.8-27B"
        return OpenAICompatClient(
            model,
            api_key=settings.hcnsec_api_key,
            base_url=settings.openai_base_url,
            seed=settings.seed + index,
        )
    raise ValueError(f"unknown provider: {settings.provider!r}")
