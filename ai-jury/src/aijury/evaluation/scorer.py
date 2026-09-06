"""Scoring. Built before the system, per Phase 0.

Four metrics, and the last two matter more than people expect:

  accuracy       - did it get it right
  calibration    - does confidence 0.8 mean right 80% of the time (Brier + ECE)
  cost           - tokens per verdict; a jury that wins on accuracy at 40x cost
                   has not necessarily won
  false_consensus - the failure mode specific to this architecture: the panel
                   converging confidently on a wrong answer, or reporting a clean
                   verdict on a question that is genuinely contested
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from aijury.contracts.taxonomy import QuestionType
from aijury.contracts.verdict import Outcome, Verdict


@dataclass
class Score:
    correct: bool
    similarity: float
    type_correct: bool
    false_consensus: bool
    brier: float
    notes: list[str] = field(default_factory=list)


def score_verdict(
    verdict: Verdict,
    *,
    expected_answer: str,
    expected_type: QuestionType | None = None,
    acceptable: list[str] | None = None,
    threshold: float = 0.55,
) -> Score:
    candidates = [expected_answer, *(acceptable or [])]
    haystack = " ".join(
        [verdict.answer, *(c.statement for c in verdict.conclusions)]
    ).lower()
    similarity = max(
        SequenceMatcher(None, haystack, c.lower()).ratio() for c in candidates
    )
    keyword_hit = any(
        c.lower().strip() and c.lower().strip() in haystack for c in candidates
    )
    correct = keyword_hit or similarity >= threshold

    type_correct = expected_type is None or verdict.question_type is expected_type

    notes: list[str] = []
    # False consensus: asserting a clean answer on a grey question, or being
    # confidently wrong. Both are worse than an honest UNRESOLVED.
    false_consensus = False
    if expected_type is QuestionType.GREY_NORMATIVE and verdict.outcome is Outcome.RESOLVED:
        false_consensus = True
        notes.append("asserted consensus on a grey-area question")
    if not correct and verdict.confidence >= 0.75:
        false_consensus = True
        notes.append(f"confidently wrong at {verdict.confidence:.2f}")

    brier = (verdict.confidence - (1.0 if correct else 0.0)) ** 2
    return Score(
        correct=correct,
        similarity=similarity,
        type_correct=type_correct,
        false_consensus=false_consensus,
        brier=brier,
        notes=notes,
    )


def expected_calibration_error(
    pairs: list[tuple[float, bool]], *, bins: int = 10
) -> float:
    """ECE: mean gap between stated confidence and observed accuracy, per bin.

    Accuracy alone cannot tell you whether a confidence number means anything.
    A system that is 70% accurate and says 0.7 is far more useful than one that
    is 75% accurate and always says 0.95.
    """
    if not pairs:
        return 0.0
    total = len(pairs)
    error = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        bucket = [
            (conf, ok) for conf, ok in pairs if low < conf <= high or (index == 0 and conf == 0)
        ]
        if not bucket:
            continue
        avg_conf = sum(c for c, _ in bucket) / len(bucket)
        accuracy = sum(1 for _, ok in bucket if ok) / len(bucket)
        error += (len(bucket) / total) * abs(avg_conf - accuracy)
    return error
