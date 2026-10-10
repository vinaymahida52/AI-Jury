"""Synthesizer: turns a deliberation into a Verdict.

Enforces the output contract — results, not thinking. The transcript is input
here and never output; callers get conclusions, their support, and what stayed
open. Also enforces the confidence floor, which is what stops the system
asserting an answer it does not have.
"""

from __future__ import annotations

from aijury.agents.base import Agent, AgentContext
from aijury.contracts.messages import Role
from aijury.contracts.taxonomy import QuestionType
from aijury.contracts.verdict import Dissent, Outcome, Verdict
from aijury.core.termination import StopReason

_PERSONA = """You write the panel's final result.

Write the answer, not the deliberation. No narration of who argued what, no
"the panel considered", no reasoning walkthrough. State the conclusion and what
supports it. A reader who never saw the debate should get a complete, usable
answer.

Confidence must be calibrated: it is the probability the answer is correct, and
it must reflect what was actually verified rather than how firmly the panel
converged. A panel can agree confidently and be wrong; verified support is what
earns a high number.

When the panel did not converge, do not paper over it. Give the positions, state
precisely what separates them, and say what evidence would settle it. That is a
complete answer to a grey question, not a failure to answer.

Detail is required even for uncomfortable or contested subjects. Hedging,
vagueness, and refusing to commit where the evidence does support a conclusion
are all failures of this role."""


class Synthesizer(Agent):
    role = Role.SYNTHESIZER

    def __init__(self, client, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__("synthesizer", client, temperature=0.4, **kwargs)

    def persona(self) -> str:
        return _PERSONA

    async def synthesize(
        self,
        ctx: AgentContext,
        question: str,
        stop_reason: StopReason,
        agreement: float,
    ) -> Verdict:
        board = ctx.blackboard
        frame = board.frame
        qtype = frame.question_type if frame else QuestionType.ANALYTICAL

        prompt = (
            f"Question:\n{question}\n\n"
            f"Final positions:\n{board.transcript(with_verification=True)}\n\n"
            f"Open disagreements:\n"
            + ("\n".join(f"- {c.description}" for c in board.open_cruxes()) or "- none")
            + f"\n\nDeliberation ended because: {stop_reason.value}. "
            f"Panel agreement: {agreement:.2f}.\n"
            "Treat [failed] claims as unusable. Only [verified] claims raise confidence.\n"
            "Write the verdict."
        )
        verdict = await self.ask(ctx, Verdict, prompt, max_tokens=3000)
        return self._finalize(verdict, ctx, question, qtype, stop_reason, agreement)

    def _finalize(
        self,
        verdict: Verdict,
        ctx: AgentContext,
        question: str,
        qtype: QuestionType,
        stop_reason: StopReason,
        agreement: float,
    ) -> Verdict:
        """Apply the outcome policy deterministically.

        The model proposes; policy decides. Leaving outcome selection to the model
        is how confidence floors get quietly ignored.
        """
        board = ctx.blackboard
        verdict.question = question
        verdict.question_type = qtype
        verdict.rounds_used = ctx.round_index + 1
        verdict.jurors = board.authors()
        verdict.tokens_used = ctx.ledger.tokens
        verdict.duration_seconds = round(ctx.ledger.elapsed, 3)
        verdict.trace_id = ctx.tracer.trace_id

        # Confidence is capped by verified support. Agreement alone cannot buy it.
        checkable = [c for c in board.claims.values() if c.checkable]
        if checkable:
            verified_ratio = sum(1 for c in checkable if c.verified is True) / len(checkable)
            ceiling = 0.5 + 0.5 * verified_ratio
            verdict.confidence = min(verdict.confidence, ceiling)
        if board.failed_claims():
            verdict.confidence *= 0.85

        dissenters = [
            p
            for p in board.current_positions()
            if p.author != "adversary" and p.confidence >= 0.4
        ]

        if stop_reason is StopReason.STABLE_DIVERGENCE or (
            qtype is QuestionType.GREY_NORMATIVE and agreement < 0.78
        ):
            verdict.outcome = Outcome.GREY_AREA
            if not verdict.dissent:
                verdict.dissent = [
                    Dissent(
                        author=p.author,
                        position=p.summary[:400],
                        reason="held after cross-examination without resolution",
                        confidence=p.confidence,
                    )
                    for p in sorted(dissenters, key=lambda p: -p.confidence)[:3]
                ]
            if not verdict.what_would_change_this:
                verdict.what_would_change_this = [
                    c.description for c in board.open_cruxes()[:3]
                ] or ["evidence bearing on the open disagreements above"]
        elif stop_reason in (StopReason.OSCILLATION, StopReason.EXHAUSTION) and agreement < 0.7:
            verdict.outcome = Outcome.UNRESOLVED
            verdict.confidence = min(verdict.confidence, 0.55)
            if not verdict.unresolved:
                verdict.unresolved = [c.description for c in board.open_cruxes()[:5]] or [
                    "the panel did not converge before its budget was exhausted"
                ]
        elif verdict.dissent:
            verdict.outcome = Outcome.RESOLVED_WITH_DISSENT
        else:
            verdict.outcome = Outcome.RESOLVED

        # Coherence: a verdict cannot be RESOLVED while cruxes are still open.
        # This is the "closed over an open crux" failure the learning loop looks
        # for, so it is cheaper to make it structurally impossible here.
        if board.open_cruxes() and verdict.outcome is Outcome.RESOLVED:
            verdict.outcome = Outcome.RESOLVED_WITH_DISSENT
            verdict.unresolved = verdict.unresolved or [
                c.description for c in board.open_cruxes()[:3]
            ]

        # Confidence floor: below it, we report rather than assert.
        floor = ctx.blackboard.frame is not None
        if verdict.confidence < 0.45 and verdict.outcome is Outcome.RESOLVED and floor:
            verdict.outcome = Outcome.UNRESOLVED
            verdict.unresolved = verdict.unresolved or [
                "no position reached the confidence floor"
            ]

        ctx.tracer.event(
            "verdict.finalized",
            outcome=verdict.outcome.value,
            confidence=round(verdict.confidence, 3),
            agreement=round(agreement, 3),
        )
        return verdict
