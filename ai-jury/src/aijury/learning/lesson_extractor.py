"""Phase 6b: clustering failures into lessons.

Runs offline over the failure store, not inside a deliberation. Deliberately
requires a pattern to recur before it becomes a lesson: single failures are
usually noise, and promoting them fills every future prompt with contradictory
instructions that degrade the panel.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from aijury.config import Settings
from aijury.learning.failure_store import FailureRecord

#: A pattern must appear this many times before it earns a place in agent prompts.
PROMOTION_THRESHOLD = 3


@dataclass
class Lesson:
    id: str
    pattern: str
    instruction: str
    #: Which agents this constrains. Empty means all.
    applies_to: list[str] = field(default_factory=list)
    occurrences: int = 0
    example_failure_ids: list[str] = field(default_factory=list)
    #: Set to False by the regression gate when a lesson makes eval scores worse.
    active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def extract_lessons(
    failures: list[FailureRecord], *, threshold: int = PROMOTION_THRESHOLD
) -> list[Lesson]:
    """Derive lessons from recurring, structurally-identified failure patterns.

    These are deterministic rules over trace metadata rather than model-generated
    prose. A model asked to summarise its own failures produces plausible,
    generic advice; trace structure produces specific, checkable constraints.
    """
    buckets: dict[str, list[FailureRecord]] = defaultdict(list)

    for failure in failures:
        if failure.confidence >= 0.75:
            buckets["overconfidence"].append(failure)
        if failure.survived_rounds >= 2:
            buckets["survived_cross_examination"].append(failure)
        if not failure.verification_had_method:
            buckets["unverifiable_load_bearing_claim"].append(failure)
        if failure.outcome == "resolved" and failure.open_cruxes:
            buckets["closed_over_open_crux"].append(failure)
        if not failure.belief_changes:
            buckets["no_belief_updates"].append(failure)

    templates = {
        "overconfidence": (
            "Confidence above 0.75 has been wrong repeatedly on this class of "
            "question. Do not exceed 0.75 unless the load-bearing claims are "
            "verified by a tool, not by agreement.",
            ["synthesizer", "juror"],
        ),
        "survived_cross_examination": (
            "Wrong claims have survived multiple rounds unchallenged. In cross-"
            "examination, attack the claim the panel is treating as settled "
            "background, not only the claims still in dispute.",
            ["adversary", "juror"],
        ),
        "unverifiable_load_bearing_claim": (
            "Answers have rested on claims no tool could check. When a conclusion "
            "depends on an unverifiable claim, say so explicitly and lower "
            "confidence rather than treating it as established.",
            ["verifier", "synthesizer"],
        ),
        "closed_over_open_crux": (
            "Verdicts have been marked resolved while cruxes were still open. Do "
            "not report consensus while a crux remains unresolved.",
            ["synthesizer", "moderator"],
        ),
        "no_belief_updates": (
            "Panels that never update have produced wrong answers. If no juror "
            "changed position across rounds, treat that as evidence the panel is "
            "anchored, not as evidence it is right.",
            ["moderator", "juror"],
        ),
    }

    lessons = []
    for pattern, records in buckets.items():
        if len(records) < threshold:
            continue
        instruction, applies_to = templates[pattern]
        lessons.append(
            Lesson(
                id=pattern,
                pattern=pattern,
                instruction=instruction,
                applies_to=applies_to,
                occurrences=len(records),
                example_failure_ids=[r.id for r in records[:5]],
            )
        )
    return lessons


def failure_summary(failures: list[FailureRecord]) -> dict[str, int]:
    """Where errors enter. Read this before tuning anything."""
    return dict(Counter(f.introduced_by or "unknown" for f in failures))


def save_lessons(lessons: list[Lesson], settings: Settings) -> str:
    from aijury.learning.repository import get_repository

    return get_repository(settings).save_lessons(lessons)
