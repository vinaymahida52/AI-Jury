"""Provider-agnostic LLM interface.

Agents depend on this protocol, never on a vendor SDK. That is what lets a jury
run heterogeneous models, and what lets the whole test suite run offline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class StructuredParseError(RuntimeError):
    """Raised when a model's output cannot be coerced into the requested schema."""


@dataclass
class LLMResponse:
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMClient(Protocol):
    """Minimal surface. Anything satisfying this can be a juror."""

    model: str

    async def complete(
        self,
        system: str,
        prompt: str,
        *,
        max_tokens: int = 2000,
        temperature: float = 0.7,
    ) -> LLMResponse: ...


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def compact_json_schema(schema: type[BaseModel]) -> str:
    """Schema text for the model: same contract, no pretty-print tax.

    This string is prepended to every agent call. Indentation and Pydantic's
    `$schema`/`title` metadata are not part of the contract and would otherwise
    be billed on every juror, every round.
    """
    raw = schema.model_json_schema()
    return json.dumps(_strip_schema_noise(raw), separators=(",", ":"), ensure_ascii=False)


def _strip_schema_noise(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: _strip_schema_noise(value)
            for key, value in node.items()
            if key not in {"$schema", "title"}
        }
    if isinstance(node, list):
        return [_strip_schema_noise(item) for item in node]
    return node


def extract_json(text: str) -> Any:
    """Pull a JSON object out of model output, tolerating fences and preamble."""
    candidate = text.strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost brace-balanced span.
    start = candidate.find("{")
    if start == -1:
        raise StructuredParseError(f"no JSON object found in output: {text[:200]!r}")
    depth = 0
    in_str = False
    escape = False
    for i, ch in enumerate(candidate[start:], start):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(candidate[start : i + 1])
                except json.JSONDecodeError as exc:
                    raise StructuredParseError(str(exc)) from exc
    raise StructuredParseError(f"unbalanced JSON in output: {text[:200]!r}")


async def complete_structured(
    client: LLMClient,
    schema: type[T],
    system: str,
    prompt: str,
    *,
    max_tokens: int = 2000,
    temperature: float = 0.7,
    retries: int = 2,
) -> tuple[T, LLMResponse]:
    """Ask for JSON matching `schema`, repairing on failure.

    Repair loop rather than a single shot: a malformed response is far more often
    a formatting slip than a reasoning failure, and re-prompting with the
    validation error recovers most of them cheaply.
    """
    contract = compact_json_schema(schema)
    sys_prompt = (
        f"{system}\n\n"
        "Respond with a single JSON object and nothing else. No prose, no code "
        f"fences, no explanation before or after it.\n\nJSON schema:\n{contract}"
    )
    last_error = ""
    attempt_prompt = prompt
    for attempt in range(retries + 1):
        response = await client.complete(
            sys_prompt, attempt_prompt, max_tokens=max_tokens, temperature=temperature
        )
        try:
            return schema.model_validate(extract_json(response.text)), response
        except (StructuredParseError, ValidationError) as exc:
            last_error = str(exc)
            attempt_prompt = (
                f"{prompt}\n\nYour previous reply failed validation:\n{last_error}\n"
                "Return only a valid JSON object conforming to the schema."
            )
            if attempt == retries:
                raise StructuredParseError(
                    f"{schema.__name__} unparseable after {retries + 1} attempts: {last_error}"
                ) from exc
    raise StructuredParseError("unreachable")
