"""Juror: one perspective, one position per round."""

from __future__ import annotations

from aijury.agents.base import Agent, AgentContext
from aijury.contracts.messages import Position, Role

_BASE = """You are juror "{name}", contributing the {perspective} perspective to a
structured deliberation.

Rules that bind you:
- State a position and a calibrated confidence. Confidence is a probability that
  you are correct, not a measure of how strongly you feel. If the evidence is
  thin, say so with a low number.
- Every claim you make must be individually checkable and carry its evidence. An
  unbacked assertion is the weakest kind of evidence and will be scored as such.
- You must name the strongest argument against your own position. Leaving it
  blank is treated as a defect in your reasoning.
- Argue from your assigned perspective. Do not drift toward the panel average to
  appear agreeable; the panel's value comes from you covering ground the others
  do not.
- Change your position when the evidence warrants it, and say what changed it.
  Changing without a reason, or refusing to change in the face of a resolved
  crux, are both failures."""


class Juror(Agent):
    role = Role.JUROR

    def __init__(self, name: str, perspective: str, client, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(name, client, **kwargs)
        self.perspective = perspective

    def persona(self) -> str:
        return _BASE.format(name=self.name, perspective=self.perspective)

    async def draft(self, ctx: AgentContext, question: str) -> Position:
        """Round 0: independent draft, blind to other jurors.

        Blind first-round drafting is the main defence against herding. Once a
        juror has seen a confident peer, its independent signal is gone.
        """
        frame = ctx.blackboard.frame
        criteria = "\n".join(f"- {c}" for c in (frame.success_criteria if frame else []))
        prompt = (
            f"Question:\n{question}\n\n"
            f"A correct answer must satisfy:\n{criteria or '- (none specified)'}\n\n"
            "You have not seen any other juror's view and must not speculate about "
            "them. Give your independent position."
        )
        position = await self.ask(ctx, Position, prompt)
        return self._stamp(position, ctx)

    async def cross_examine(self, ctx: AgentContext, question: str) -> Position:
        """Round 1+: react to anonymized peer positions."""
        transcript = ctx.blackboard.transcript(anonymized=True)
        cruxes = "\n".join(f"- {c.description}" for c in ctx.blackboard.open_cruxes())
        failed = "\n".join(f"- {c.text} (failed verification)" for c in ctx.blackboard.failed_claims())
        prompt = (
            f"Question:\n{question}\n\n"
            f"Positions on the table (authors withheld):\n{transcript}\n\n"
            f"Open disagreements:\n{cruxes or '- none isolated yet'}\n\n"
            f"Claims that failed verification:\n{failed or '- none'}\n\n"
            "Identify the strongest position opposing yours and either rebut it "
            "with evidence or update. If you update, set change_reason to the "
            "specific thing that changed your mind. Do not restate your prior "
            "position unchanged unless nothing on the table bears on it."
        )
        position = await self.ask(ctx, Position, prompt)
        return self._stamp(position, ctx)

    def _stamp(self, position: Position, ctx: AgentContext) -> Position:
        position.author = self.name
        position.round_index = ctx.round_index
        for claim in position.claims:
            claim.author = self.name
            claim.round_index = ctx.round_index
        return position
