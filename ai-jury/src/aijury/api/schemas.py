"""Request and response models for the HTTP API.

Kept separate from the domain contracts: the wire format should be able to change
without dragging the deliberation schemas with it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aijury.contracts.verdict import Verdict


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=20_000)
    #: Per-request overrides. Omitted fields fall back to the server's settings.
    max_rounds: int | None = Field(default=None, ge=1, le=100)
    max_jurors: int | None = Field(default=None, ge=1, le=100)
    use_lessons: bool = True
    #: Continue an existing chat; omit to start a new thread.
    thread_id: str | None = Field(default=None, max_length=64)


class ClaimView(BaseModel):
    text: str
    author: str
    round_index: int
    verified: bool | None
    note: str | None = None


class PositionView(BaseModel):
    author: str
    round_index: int
    summary: str
    confidence: float
    changed: bool
    change_reason: str | None = None
    concedes: str | None = None
    claims: list[ClaimView] = Field(default_factory=list)


class CruxView(BaseModel):
    description: str
    resolvable_by: str
    resolved: bool
    resolution: str | None = None


class DeliberationView(BaseModel):
    """The full record. Distinct from the Verdict on purpose.

    The Verdict is the product and carries no deliberation transcript. This view
    is the operator's window into the machinery, and exists only because a human
    is debugging the panel rather than consuming its answer.
    """

    verdict: Verdict
    question_type: str
    stop_reason: str
    agreement: float
    positions: list[PositionView] = Field(default_factory=list)
    cruxes: list[CruxView] = Field(default_factory=list)
    belief_changes: list[dict[str, str | int]] = Field(default_factory=list)
    #: Fraction of checkable claims that passed verification. This is what caps
    #: the verdict's confidence, so the UI shows it beside the number.
    verified_ratio: float = 0.0
    verified_claims: int = 0
    checkable_claims: int = 0
    degraded: list[str] = Field(default_factory=list)
    budget: dict[str, float] = Field(default_factory=dict)
    case_id: str | None = None
    thread_id: str | None = None


class ThreadSummaryView(BaseModel):
    id: str
    title: str
    updated_at: str
    preview: str = ""


class ThreadMessageView(BaseModel):
    id: str
    role: str
    content: str
    case_id: str = ""
    created_at: str = ""


class ThreadDetailView(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[ThreadMessageView] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    expected: str = Field(min_length=1, max_length=20_000)
    signal: str = Field(default="production_feedback", max_length=80)


class FeedbackResponse(BaseModel):
    failure_id: str
    case_id: str
    lessons_promoted: int = 0


class HealthResponse(BaseModel):
    status: str
    version: str
    provider: str
    model: str = ""
    max_rounds: int
    max_jurors: int
    lessons_active: int


class GatewayWrite(BaseModel):
    id: str | None = None
    label: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=1, max_length=400)
    model: str = Field(default="", max_length=200)
    model_pool: list[str] = Field(default_factory=list)
    api_key: str = Field(default="", max_length=500)
    seat: bool = False
