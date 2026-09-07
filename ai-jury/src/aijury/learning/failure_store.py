"""Phase 6a: the failure store.

Records every verdict a ground-truth signal marked wrong, together with enough
trace to attribute the error: which agent introduced it, which round it survived,
and whether verification had a chance to catch it.

The critical design constraint: this store is only as good as the mistake signal
feeding it. Self-reported errors are near-worthless because the panel's blind
spots are exactly what it cannot see. Populate this from eval ground truth,
deterministic verifier failures, or delayed real-world outcomes.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from aijury.config import Settings
from aijury.protocol.deliberation import DeliberationResult


@dataclass
class FailureRecord:
    id: str
    question: str
    question_type: str
    expected: str
    produced: str
    confidence: float
    outcome: str
    signal: str  # "eval_ground_truth" | "verifier" | "production_feedback"
    #: Which agent first asserted the claim that carried the error, when known.
    introduced_by: str | None = None
    #: How many rounds the wrong claim survived cross-examination without challenge.
    survived_rounds: int = 0
    verification_had_method: bool = False
    open_cruxes: list[str] = field(default_factory=list)
    belief_changes: list[dict[str, str | int]] = field(default_factory=list)
    trace_id: str = ""
    case_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class FailureStore:
    """Append-only failure log. File or Postgres via LearningRepository."""

    def __init__(self, settings: Settings) -> None:
        from aijury.learning.repository import get_repository

        self.settings = settings
        self._repo = get_repository(settings)
        self.path = (
            os.path.join(settings.failure_dir, "failures.jsonl")
            if not settings.database_url
            else "postgres:failures"
        )

    def record(self, record: FailureRecord) -> None:
        self._repo.record_failure(record)

    def all(self) -> list[FailureRecord]:
        return self._repo.all_failures()

    @staticmethod
    def from_deliberation(
        result: DeliberationResult, *, expected: str, signal: str, case_id: str = ""
    ) -> FailureRecord:
        board = result.blackboard
        verdict = result.verdict

        # Attribute the error to the author of the earliest unverified or failed
        # claim: the most likely point of entry. Heuristic, but it clusters well
        # and is far better than treating the panel as a single black box.
        suspect_claims = [
            c for c in board.claims.values() if c.verified is False or c.verified is None
        ]
        suspect = min(suspect_claims, key=lambda c: c.round_index, default=None)

        return FailureRecord(
            id=uuid.uuid4().hex[:12],
            question=board.question,
            question_type=board.frame.question_type.value if board.frame else "unknown",
            expected=expected,
            produced=verdict.answer,
            confidence=verdict.confidence,
            outcome=verdict.outcome.value,
            signal=signal,
            introduced_by=suspect.author if suspect else None,
            survived_rounds=(verdict.rounds_used - suspect.round_index) if suspect else 0,
            verification_had_method=bool(suspect and suspect.checkable),
            open_cruxes=[c.description for c in board.open_cruxes()],
            belief_changes=board.belief_changes,
            trace_id=verdict.trace_id,
            case_id=case_id,
        )
