"""The Verdict: the only object the outside world sees.

Deliberately excludes raw reasoning transcripts. Callers get conclusions, what
supports them, what remains open, and a calibrated confidence. Full traces stay
behind a debug flag.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from aijury.contracts.taxonomy import QuestionType


class Outcome(str, Enum):
    RESOLVED = "resolved"                  # jury converged and verification passed
    RESOLVED_WITH_DISSENT = "resolved_with_dissent"  # majority, recorded objection
    GREY_AREA = "grey_area"                # stable, principled disagreement
    UNRESOLVED = "unresolved"              # below confidence floor / budget exhausted
    ESCALATE = "escalate"                  # needs a human or a capability we lack


class Dissent(BaseModel):
    author: str
    position: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)


class SupportedConclusion(BaseModel):
    statement: str
    support: list[str] = Field(default_factory=list, description="What backs this, in brief.")
    verified: bool = False


class Verdict(BaseModel):
    question: str
    question_type: QuestionType
    outcome: Outcome
    answer: str = Field(description="The result. No deliberation transcript, no thinking.")
    confidence: float = Field(ge=0.0, le=1.0)

    conclusions: list[SupportedConclusion] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    dissent: list[Dissent] = Field(default_factory=list)
    unresolved: list[str] = Field(
        default_factory=list, description="Open questions the jury could not settle."
    )
    what_would_change_this: list[str] = Field(
        default_factory=list,
        description="For grey areas: the evidence that would move the answer.",
    )

    rounds_used: int = 0
    jurors: list[str] = Field(default_factory=list)
    tokens_used: int = 0
    duration_seconds: float = 0.0
    trace_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _grey_areas_must_map_the_disagreement(self) -> Verdict:
        """A grey-area verdict that asserts a clean answer is a bug, not a result.

        This is the guardrail against the system manufacturing false consensus
        on questions that genuinely do not have one.
        """
        if self.outcome is Outcome.GREY_AREA:
            if not self.dissent and not self.what_would_change_this:
                raise ValueError(
                    "GREY_AREA verdict must carry dissent or what_would_change_this; "
                    "otherwise it is asserting consensus that does not exist."
                )
        if self.outcome is Outcome.UNRESOLVED and self.confidence > 0.6:
            raise ValueError("UNRESOLVED verdict cannot carry high confidence.")
        return self

    def render(self) -> str:
        """Human-facing text. Results only."""
        lines = [self.answer.strip(), ""]
        if self.conclusions:
            lines.append("Key points:")
            lines += [
                f"  - {c.statement}" + (" [verified]" if c.verified else "")
                for c in self.conclusions
            ]
            lines.append("")
        if self.assumptions:
            lines.append("Assumed: " + "; ".join(self.assumptions))
        if self.dissent:
            lines.append("")
            lines.append("Dissenting positions:")
            lines += [f"  - {d.position} ({d.reason})" for d in self.dissent]
        if self.unresolved:
            lines.append("")
            lines.append("Unresolved: " + "; ".join(self.unresolved))
        if self.what_would_change_this:
            lines.append("")
            lines.append("Would change this: " + "; ".join(self.what_would_change_this))
        lines.append("")
        lines.append(f"[{self.outcome.value} | confidence {self.confidence:.2f} "
                     f"| {self.rounds_used} rounds | {len(self.jurors)} jurors]")
        return "\n".join(lines)
