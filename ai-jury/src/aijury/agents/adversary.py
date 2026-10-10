"""Adversary: structurally required opposition to whatever is winning.

Not a juror with a contrarian personality. Its job is to attack the leading
position every round regardless of whether it privately agrees, because a jury
with no standing opposition converges on the most fluent argument rather than
the best one.
"""

from __future__ import annotations

from aijury.agents.base import Agent, AgentContext
from aijury.contracts.messages import Position, Role

_PERSONA = """You attack the panel's leading position. That is your only function.

Attack the reasoning, not the wording. Target, in order of value:
1. Load-bearing assumptions that were never argued for.
2. Claims presented as verified that were only asserted.
3. Cases where the position fails that nobody has raised.
4. Confidence unsupported by the evidence actually on the table.

You are not required to hold a better alternative position, and you must not
invent objections when the leading position is sound. If it survives your
strongest attack, say so plainly and state what specifically survived — a false
objection is worse than none, because it wastes a round and can flip a correct
panel to a wrong answer."""


class Adversary(Agent):
    role = Role.ADVERSARY

    def __init__(self, client, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__("adversary", client, temperature=0.85, **kwargs)

    def persona(self) -> str:
        return _PERSONA

    async def attack(self, ctx: AgentContext, question: str) -> Position:
        leading = max(
            ctx.blackboard.current_positions(),
            key=lambda p: p.confidence,
            default=None,
        )
        prompt = (
            f"Question:\n{question}\n\n"
            f"All positions:\n{ctx.blackboard.transcript(anonymized=True)}\n\n"
            f"Leading position (highest confidence, {leading.confidence:.2f}):\n"
            f"{leading.summary if leading else '(none yet)'}\n\n"
            "Attack it. Set summary to your strongest objection and confidence to "
            "how likely you think that objection is to be decisive."
        )
        position = await self.ask(ctx, Position, prompt)
        position.author = self.name
        position.round_index = ctx.round_index
        for claim in position.claims:
            claim.author = self.name
            claim.round_index = ctx.round_index
        return position
