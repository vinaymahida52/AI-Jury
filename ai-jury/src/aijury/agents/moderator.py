"""Moderator: isolates cruxes and routes the debate.

Without this the panel restates positions at each other indefinitely. The
moderator's output is the list of specific disagreements that, if resolved,
would settle the question — which is what converts round count into progress.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aijury.agents.base import Agent, AgentContext
from aijury.contracts.messages import Crux, Role
from aijury.contracts.taxonomy import VERIFICATION_MATRIX, QuestionType


class ModeratorReport(BaseModel):
    cruxes: list[Crux] = Field(default_factory=list)
    talking_past_each_other: bool = False
    note: str = ""
    next_speaker: str | None = Field(
        default=None, description="Agent name that should speak next, if one matters more."
    )


_PERSONA = """You moderate a deliberation. You do not hold a position.

Extract cruxes: specific points of disagreement where the parties would change
their conclusion if the point were settled. A crux is not a summary of the
argument — it is the load-bearing fact or judgement the disagreement rests on.

For each crux state what could settle it: retrieval, code_execution,
recomputation, consistency, or argument (meaning nothing external can settle it,
which usually indicates the question is normative).

Flag when parties are talking past each other — using the same word for
different things, or answering different questions. That is the single most
common reason panels fail to converge, and it is invisible from inside the
argument."""


class Moderator(Agent):
    role = Role.MODERATOR

    def __init__(self, client, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__("moderator", client, temperature=0.3, **kwargs)

    def persona(self) -> str:
        return _PERSONA

    async def isolate_cruxes(self, ctx: AgentContext, question: str) -> ModeratorReport:
        frame = ctx.blackboard.frame
        qtype = frame.question_type if frame else QuestionType.ANALYTICAL
        allowed = ", ".join(m.value for m in VERIFICATION_MATRIX[qtype])
        prompt = (
            f"Question:\n{question}\n\n"
            f"Positions:\n{ctx.blackboard.transcript(anonymized=True)}\n\n"
            f"Question type is {qtype.value}; available settlement methods: {allowed}, argument.\n"
            "List only cruxes that are still open. If the parties agree on "
            "substance and differ only in emphasis, return no cruxes."
        )
        report = await self.ask(ctx, ModeratorReport, prompt)
        existing = {c.description.strip().lower() for c in ctx.blackboard.cruxes}
        for crux in report.cruxes:
            if crux.description.strip().lower() not in existing:
                ctx.blackboard.add_crux(crux)
        ctx.tracer.event(
            "moderator.cruxes",
            new=len(report.cruxes),
            open=len(ctx.blackboard.open_cruxes()),
            talking_past=report.talking_past_each_other,
        )
        return report
