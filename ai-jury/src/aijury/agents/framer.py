"""Intake/Framer: classifies the question and designs the jury.

Runs before any argument. Getting the type wrong routes the question to the
wrong verifiers, so this agent is worth its own eval slice.
"""

from __future__ import annotations

from aijury.agents.base import Agent, AgentContext
from aijury.contracts.messages import Role
from aijury.contracts.taxonomy import Frame

_PERSONA = """You frame questions before a panel deliberates on them.

Classify the question into exactly one type:
- factual: settled by checking sources.
- technical: settled by running code, tests, or computation.
- analytical: settled by reasoning from premises the parties can agree on.
- grey_normative: turns on values or contested tradeoffs and has no single
  correct answer. Classify here when reasonable, well-informed people disagree
  for principled reasons rather than for lack of information.

Do not force a question into a settleable type to make it easier to answer.
Misclassifying a grey question as factual is the more damaging error, because it
causes the panel to manufacture a consensus that does not exist.

Surface the assumptions hidden in the question's phrasing. List the perspectives
a panel would need in order to cover it, using short labels such as 'security',
'cost', 'legal', 'second-order effects', 'implementation feasibility'. Request
only the perspectives the question genuinely needs."""


class Framer(Agent):
    role = Role.FRAMER

    def __init__(self, client, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__("framer", client, temperature=0.3, **kwargs)

    def persona(self) -> str:
        return _PERSONA

    async def run(self, ctx: AgentContext, question: str, max_perspectives: int) -> Frame:
        prompt = (
            f"Question:\n{question}\n\n"
            "Decide how many perspectives this question actually needs — that is "
            "the jury. Do not pad the panel, and do not undersize it to be cheap. "
            f"Hard ceiling: {max_perspectives} perspectives.\n"
            "Restate the question precisely, name the hidden assumptions, and give "
            "the criteria a correct answer must satisfy."
        )
        frame = await self.ask(ctx, Frame, prompt)
        frame.question = question
        frame.required_perspectives = frame.required_perspectives[:max_perspectives]
        ctx.blackboard.frame = frame
        ctx.tracer.event(
            "frame.complete",
            question_type=frame.question_type.value,
            perspectives=frame.required_perspectives,
        )
        return frame
