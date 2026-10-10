"""Verifier: checks claims with tools, not with opinion.

Structurally separated from the proposers. A verifier that is the same instance
as the author will ratify its own reasoning, which is how these systems produce
confident wrong answers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aijury.agents.base import Agent, AgentContext
from aijury.contracts.messages import Role
from aijury.contracts.taxonomy import VERIFICATION_MATRIX, QuestionType
from aijury.verification.registry import run_verifiers


class ClaimJudgement(BaseModel):
    claim_id: str
    verified: bool
    note: str = ""


class VerificationReport(BaseModel):
    judgements: list[ClaimJudgement] = Field(default_factory=list)
    unverifiable: list[str] = Field(
        default_factory=list, description="Claim ids no available tool can settle."
    )


_PERSONA = """You verify claims. You do not argue and you do not hold a position.

Mark a claim verified only when the evidence attached to it actually establishes
it. A claim that is plausible, well-phrased, or consistent with your priors is
not verified — those are the exact claims that slip through.

When no available tool can settle a claim, list it as unverifiable rather than
guessing. Reporting a limit is correct behaviour; a false verification is the
most expensive error this system can make, because everything downstream then
treats the claim as settled."""


class Verifier(Agent):
    role = Role.VERIFIER

    def __init__(self, client, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__("verifier", client, temperature=0.1, **kwargs)

    def persona(self) -> str:
        return _PERSONA

    async def verify(self, ctx: AgentContext) -> VerificationReport:
        pending = ctx.blackboard.unverified_claims()
        if not pending:
            return VerificationReport()

        frame = ctx.blackboard.frame
        qtype = frame.question_type if frame else QuestionType.ANALYTICAL
        methods = VERIFICATION_MATRIX[qtype]

        # Deterministic tool-based checks run first and are authoritative where
        # they apply; the model is only consulted for what tools cannot settle.
        tool_results = run_verifiers(pending, methods, ctx.tracer)
        settled = {r.claim_id: r for r in tool_results if r.decisive}

        remaining = [c for c in pending if c.id not in settled]
        report = VerificationReport(
            judgements=[
                ClaimJudgement(claim_id=r.claim_id, verified=r.passed, note=r.note)
                for r in settled.values()
            ]
        )

        if remaining:
            listing = "\n".join(
                f"- id={c.id} | {c.text} | evidence: "
                + ("; ".join(f"{e.kind.value}:{e.content[:120]}" for e in c.evidence) or "none")
                for c in remaining
            )
            prompt = (
                f"Available verification methods for this question type: "
                f"{', '.join(m.value for m in methods)}.\n\n"
                f"Claims awaiting judgement:\n{listing}\n\n"
                "Judge each by id. Anything you cannot settle with the evidence "
                "shown goes in unverifiable."
            )
            model_report = await self.ask(ctx, VerificationReport, prompt)
            known = {c.id for c in remaining}
            report.judgements.extend(
                j for j in model_report.judgements if j.claim_id in known
            )
            report.unverifiable.extend(u for u in model_report.unverifiable if u in known)

        for judgement in report.judgements:
            claim = ctx.blackboard.claims.get(judgement.claim_id)
            if claim:
                claim.verified = judgement.verified
                claim.verification_note = judgement.note
        for claim_id in report.unverifiable:
            claim = ctx.blackboard.claims.get(claim_id)
            if claim:
                claim.checkable = False
                claim.verification_note = "no available method could settle this"

        ctx.tracer.event(
            "verification.complete",
            judged=len(report.judgements),
            failed=sum(1 for j in report.judgements if not j.verified),
            unverifiable=len(report.unverifiable),
        )
        return report
