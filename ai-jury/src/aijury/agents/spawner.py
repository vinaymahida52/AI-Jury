"""Dynamic jury construction.

Jurors are spawned from the Framer's requested perspectives, capped hard. An
uncapped spawner is the standard way these systems become unshippable: cost and
latency scale with the model's enthusiasm rather than with the task.
"""

from __future__ import annotations

from aijury.agents.juror import Juror
from aijury.config import Settings
from aijury.contracts.taxonomy import Frame, QuestionType
from aijury.llm.registry import build_client

#: Fallback perspectives when the Framer requests none, by question type.
_DEFAULT_PERSPECTIVES: dict[QuestionType, tuple[str, ...]] = {
    QuestionType.FACTUAL: ("source reliability", "contradicting evidence"),
    QuestionType.VERIFIABLE_TECHNICAL: ("correctness", "edge cases", "operational cost"),
    QuestionType.ANALYTICAL: ("first principles", "empirical precedent", "second-order effects"),
    QuestionType.GREY_NORMATIVE: (
        "the strongest case for",
        "the strongest case against",
        "affected parties",
    ),
}

#: Personas map onto mock-client behaviour and onto real temperature/stance shaping.
_PERSONA_CYCLE = ("neutral", "skeptic", "optimist", "neutral", "skeptic")


def spawn_jury(frame: Frame, settings: Settings) -> list[Juror]:
    """Build the juror panel for one question.

    Perspectives are deduplicated and capped; each juror is assigned a distinct
    model from the pool where one is configured, so that jurors do not share a
    single model's blind spots.
    """
    requested = [p.strip() for p in frame.required_perspectives if p.strip()]
    if not requested:
        requested = list(_DEFAULT_PERSPECTIVES[frame.question_type])

    seen: set[str] = set()
    perspectives: list[str] = []
    for perspective in requested:
        key = perspective.lower()
        if key not in seen:
            seen.add(key)
            perspectives.append(perspective)
    cap = max(settings.budget.max_jurors, 1)
    perspectives = perspectives[:cap]
    if not perspectives:
        perspectives = ["general"]

    jurors = []
    for index, perspective in enumerate(perspectives):
        persona = _PERSONA_CYCLE[index % len(_PERSONA_CYCLE)]
        client = build_client(settings, persona=persona, index=index)
        jurors.append(
            Juror(
                name=f"juror_{index + 1}_{_slug(perspective)}",
                perspective=perspective,
                client=client,
                temperature=0.6 + 0.1 * (index % 3),
            )
        )
    return jurors


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in text.lower()).strip("_")[:24]
