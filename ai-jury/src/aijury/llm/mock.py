"""Deterministic offline client.

Not a toy: the whole eval harness, every unit test, and CI run against this. It
produces schema-valid, seed-varied output so the orchestration layer can be
exercised without spending a token or requiring a network.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from typing import Any

from aijury.llm.base import LLMResponse


def _seeded(*parts: str) -> random.Random:
    digest = hashlib.sha256("||".join(parts).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


class MockLLMClient:
    """Synthesises schema-shaped JSON from the schema embedded in the system prompt."""

    def __init__(self, model: str = "mock-1", *, persona: str = "neutral", seed: int = 7) -> None:
        self.model = model
        self.persona = persona
        self.seed = seed
        self.calls = 0

    async def complete(
        self,
        system: str,
        prompt: str,
        *,
        max_tokens: int = 2000,
        temperature: float = 0.7,
    ) -> LLMResponse:
        started = time.perf_counter()
        self.calls += 1
        rng = _seeded(self.model, self.persona, str(self.seed), prompt[:400], str(self.calls))
        schema = _find_schema(system)
        payload = _synthesize(schema, rng, self.persona, prompt) if schema else {"text": "ok"}
        text = json.dumps(payload)
        return LLMResponse(
            text=text,
            model=self.model,
            tokens_in=len(system + prompt) // 4,
            tokens_out=len(text) // 4,
            latency_ms=(time.perf_counter() - started) * 1000,
        )


def _find_schema(system: str) -> dict[str, Any] | None:
    marker = "JSON schema:"
    if marker not in system:
        return None
    try:
        return json.loads(system.split(marker, 1)[1].strip())
    except json.JSONDecodeError:
        return None


_FORMAT_SAMPLES = {
    "date-time": "2026-01-01T00:00:00+00:00",
    "date": "2026-01-01",
    "time": "00:00:00",
    "uri": "https://example.invalid/source",
    "email": "agent@example.invalid",
    "uuid": "00000000-0000-4000-8000-000000000000",
}

_PERSONA_STANCE = {
    "optimist": 0.82,
    "skeptic": 0.44,
    "neutral": 0.63,
    "adversary": 0.35,
}


def _synthesize(
    schema: dict[str, Any], rng: random.Random, persona: str, prompt: str
) -> Any:
    defs = schema.get("$defs", {})
    return _build(schema, defs, rng, persona, prompt, depth=0)


def _build(
    node: dict[str, Any],
    defs: dict[str, Any],
    rng: random.Random,
    persona: str,
    prompt: str,
    depth: int,
) -> Any:
    if "$ref" in node:
        key = node["$ref"].rsplit("/", 1)[-1]
        return _build(defs.get(key, {}), defs, rng, persona, prompt, depth + 1)
    if "anyOf" in node:
        options = [o for o in node["anyOf"] if o.get("type") != "null"]
        if not options or rng.random() < 0.25:
            return None
        return _build(options[0], defs, rng, persona, prompt, depth)
    if "enum" in node:
        return node["enum"][0]
    node_type = node.get("type")
    if node_type == "object" or "properties" in node:
        required = set(node.get("required", []))
        out: dict[str, Any] = {}
        for name, sub in node.get("properties", {}).items():
            if name not in required and depth > 1 and rng.random() < 0.4:
                continue
            out[name] = _build(sub, defs, rng, persona, prompt, depth + 1)
        return out
    if node_type == "array":
        items = node.get("items", {"type": "string"})
        count = 0 if depth > 2 else rng.randint(1, 2)
        return [_build(items, defs, rng, persona, prompt, depth + 1) for _ in range(count)]
    if node_type == "boolean":
        return rng.random() > 0.4
    if node_type == "integer":
        return rng.randint(0, 3)
    if node_type == "number":
        lo, hi = node.get("minimum", 0.0), node.get("maximum", 1.0)
        base = _PERSONA_STANCE.get(persona, 0.6)
        return round(min(hi, max(lo, base + rng.uniform(-0.12, 0.12))), 3)
    # String formats must be honoured or the mock produces prose where the schema
    # demands a timestamp, and every structured call fails validation.
    fmt = node.get("format")
    if fmt in _FORMAT_SAMPLES:
        return _FORMAT_SAMPLES[fmt]
    return f"[{persona}] {prompt.strip()[:60]}"
