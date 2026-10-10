"""Message and claim contracts written to the blackboard.

Every assertion in the system is attributed: which agent, which round, backed by
what. Unattributed text cannot enter the record, which is what makes the failure
store in Phase 6 usable later.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    return datetime.now(UTC)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class Role(str, Enum):
    FRAMER = "framer"
    JUROR = "juror"
    ADVERSARY = "adversary"
    MODERATOR = "moderator"
    VERIFIER = "verifier"
    SYNTHESIZER = "synthesizer"
    SYSTEM = "system"


class Stance(str, Enum):
    SUPPORT = "support"
    OPPOSE = "oppose"
    ABSTAIN = "abstain"


class EvidenceKind(str, Enum):
    SOURCE = "source"
    COMPUTATION = "computation"
    EXECUTION = "execution"
    DEFINITION = "definition"
    ASSERTION = "assertion"  # unbacked; treated as the weakest kind on purpose


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: EvidenceKind
    content: str
    locator: str | None = Field(
        default=None, description="URL, file path, or tool invocation id."
    )
    verified: bool = False
    verifier_note: str | None = None

    @property
    def weight(self) -> float:
        """Crude evidential weight. Unverified assertions must not outrank execution."""
        base = {
            EvidenceKind.EXECUTION: 1.0,
            EvidenceKind.COMPUTATION: 0.9,
            EvidenceKind.SOURCE: 0.7,
            EvidenceKind.DEFINITION: 0.5,
            EvidenceKind.ASSERTION: 0.15,
        }[self.kind]
        return base if self.verified else base * 0.5


class Claim(BaseModel):
    """An atomic, individually checkable assertion."""

    id: str = Field(default_factory=_uid)
    text: str
    author: str
    round_index: int
    evidence: list[Evidence] = Field(default_factory=list)
    checkable: bool = True
    verified: bool | None = None  # None = not yet checked
    verification_note: str | None = None

    @property
    def fingerprint(self) -> str:
        """Stable hash of claim text, used to detect repetition across rounds."""
        return hashlib.sha256(self.text.strip().lower().encode()).hexdigest()[:16]

    @property
    def support(self) -> float:
        return sum(e.weight for e in self.evidence)


class Position(BaseModel):
    """One agent's stance on the question at one point in the deliberation."""

    id: str = Field(default_factory=_uid)
    author: str
    round_index: int
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    claims: list[Claim] = Field(default_factory=list)
    strongest_counterargument: str | None = Field(
        default=None,
        description="Each juror must name the best case against itself. Blank is a smell.",
    )
    changed_from_previous: bool = False
    change_reason: str | None = None
    created_at: datetime = Field(default_factory=_now)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.summary.strip().lower().encode()).hexdigest()[:16]


class AgentMessage(BaseModel):
    """Anything an agent says. Append-only record on the blackboard."""

    id: str = Field(default_factory=_uid)
    round_index: int
    author: str
    role: Role
    content: str
    references: list[str] = Field(default_factory=list, description="Claim or position ids.")
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    created_at: datetime = Field(default_factory=_now)


class Crux(BaseModel):
    """A specific disagreement isolated by the Moderator.

    Deliberation converges by resolving cruxes, not by repeating positions louder.
    """

    id: str = Field(default_factory=_uid)
    description: str
    parties: list[str] = Field(default_factory=list)
    resolvable_by: str = Field(
        default="argument", description="Which verification method could settle it."
    )
    resolved: bool = False
    resolution: str | None = None
