"""Eval harness. Runs jury and baseline over the golden set and compares them.

The comparison is the point. A jury that does not beat the single-agent baseline
on the same questions at defensible cost should not ship, and this harness is
what makes that call non-negotiable.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from aijury.baseline import answer_baseline
from aijury.config import Settings
from aijury.contracts.taxonomy import QuestionType
from aijury.contracts.verdict import Verdict
from aijury.evaluation.scorer import Score, expected_calibration_error, score_verdict
from aijury.pipeline import JuryPipeline


@dataclass
class EvalCase:
    id: str
    question: str
    expected_answer: str
    question_type: QuestionType
    acceptable: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class ArmSummary:
    name: str
    n: int
    accuracy: float
    type_accuracy: float
    false_consensus_rate: float
    mean_brier: float
    ece: float
    mean_tokens: float
    mean_seconds: float

    def as_row(self) -> str:
        return (
            f"{self.name:<10} n={self.n:<4} acc={self.accuracy:.3f} "
            f"type={self.type_accuracy:.3f} false_consensus={self.false_consensus_rate:.3f} "
            f"brier={self.mean_brier:.3f} ece={self.ece:.3f} "
            f"tokens={self.mean_tokens:.0f} t={self.mean_seconds:.1f}s"
        )


@dataclass
class EvalReport:
    jury: ArmSummary
    baseline: ArmSummary
    per_case: list[dict[str, object]] = field(default_factory=list)

    @property
    def jury_beats_baseline(self) -> bool:
        """The ship gate. Accuracy must improve without calibration regressing."""
        return (
            self.jury.accuracy > self.baseline.accuracy
            and self.jury.mean_brier <= self.baseline.mean_brier
            and self.jury.false_consensus_rate <= self.baseline.false_consensus_rate
        )

    def render(self) -> str:
        verdict = "PASS" if self.jury_beats_baseline else "FAIL"
        cost_ratio = self.jury.mean_tokens / max(self.baseline.mean_tokens, 1)
        return "\n".join(
            [
                self.baseline.as_row(),
                self.jury.as_row(),
                "",
                f"cost ratio (jury/baseline): {cost_ratio:.1f}x",
                f"ship gate: {verdict}",
            ]
        )


def load_dataset(path: str | Path) -> list[EvalCase]:
    cases = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            cases.append(
                EvalCase(
                    id=raw["id"],
                    question=raw["question"],
                    expected_answer=raw["expected_answer"],
                    question_type=QuestionType(raw["question_type"]),
                    acceptable=raw.get("acceptable", []),
                    tags=raw.get("tags", []),
                )
            )
    return cases


def _summarize(name: str, scored: list[tuple[Score, Verdict]]) -> ArmSummary:
    n = max(len(scored), 1)
    return ArmSummary(
        name=name,
        n=len(scored),
        accuracy=sum(1 for s, _ in scored if s.correct) / n,
        type_accuracy=sum(1 for s, _ in scored if s.type_correct) / n,
        false_consensus_rate=sum(1 for s, _ in scored if s.false_consensus) / n,
        mean_brier=sum(s.brier for s, _ in scored) / n,
        ece=expected_calibration_error([(v.confidence, s.correct) for s, v in scored]),
        mean_tokens=sum(v.tokens_used for _, v in scored) / n,
        mean_seconds=sum(v.duration_seconds for _, v in scored) / n,
    )


async def run_eval(
    cases: list[EvalCase],
    settings: Settings,
    *,
    concurrency: int = 4,
    include_baseline: bool = True,
) -> EvalReport:
    pipeline = JuryPipeline(settings)
    semaphore = asyncio.Semaphore(concurrency)
    per_case: list[dict[str, object]] = []

    async def one(case: EvalCase) -> tuple[tuple[Score, Verdict], tuple[Score, Verdict] | None]:
        async with semaphore:
            jury_verdict = (await pipeline.ask(case.question, use_lessons=False)).verdict
            base_verdict = (
                await answer_baseline(case.question, settings) if include_baseline else None
            )
        jury_score = score_verdict(
            jury_verdict,
            expected_answer=case.expected_answer,
            expected_type=case.question_type,
            acceptable=case.acceptable,
        )
        base_pair = None
        if base_verdict is not None:
            base_pair = (
                score_verdict(
                    base_verdict,
                    expected_answer=case.expected_answer,
                    expected_type=case.question_type,
                    acceptable=case.acceptable,
                ),
                base_verdict,
            )
        per_case.append(
            {
                "id": case.id,
                "jury_correct": jury_score.correct,
                "jury_confidence": jury_verdict.confidence,
                "jury_outcome": jury_verdict.outcome.value,
                "false_consensus": jury_score.false_consensus,
                "baseline_correct": base_pair[0].correct if base_pair else None,
                "notes": jury_score.notes,
                "trace_id": jury_verdict.trace_id,
            }
        )
        return (jury_score, jury_verdict), base_pair

    results = await asyncio.gather(*(one(c) for c in cases))
    jury_scored = [r[0] for r in results]
    base_scored = [r[1] for r in results if r[1] is not None]

    return EvalReport(
        jury=_summarize("jury", jury_scored),
        baseline=_summarize("baseline", base_scored),
        per_case=sorted(per_case, key=lambda row: str(row["id"])),
    )
