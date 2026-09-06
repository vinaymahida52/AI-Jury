"""The deliberation protocol — Phase 4.

Round structure, in order:

  Round 0  Independent blind drafts. Jurors do not see each other. This is the
           single most important anti-herding measure; once a juror reads a
           confident peer, its independent signal is unrecoverable.
  Round 1+ Cross-examination against *anonymized* peer positions, so jurors
           respond to arguments rather than to authority.
           Then: adversary attacks the leading position, moderator isolates
           cruxes, verifier settles what tools can settle.
  Exit     Termination controller decides between consensus, stable divergence
           (a grey-area result), oscillation, and exhaustion.

Jurors within a round run concurrently — they are independent by design, and
sequencing them would only add latency and let ordering bias creep in.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from aijury.agents.adversary import Adversary
from aijury.agents.base import AgentContext
from aijury.agents.framer import Framer
from aijury.agents.juror import Juror
from aijury.agents.moderator import Moderator
from aijury.agents.spawner import spawn_jury
from aijury.agents.synthesizer import Synthesizer
from aijury.agents.verifier import Verifier
from aijury.config import Settings
from aijury.contracts.messages import Position
from aijury.contracts.verdict import Outcome, Verdict
from aijury.core.blackboard import Blackboard
from aijury.core.budget import BudgetExceeded, BudgetLedger
from aijury.core.termination import StopReason, TerminationController, TerminationDecision
from aijury.core.tracing import Span, Tracer
from aijury.llm.base import StructuredParseError
from aijury.llm.registry import build_client
from aijury.security.injection import screen_input


@dataclass
class DeliberationResult:
    verdict: Verdict
    blackboard: Blackboard
    ledger: BudgetLedger
    tracer: Tracer
    stop_reason: StopReason
    agreement: float
    degraded: list[str] = field(default_factory=list)


class Deliberation:
    """One question, one panel, one verdict."""

    def __init__(self, settings: Settings, *, lessons: list[str] | None = None) -> None:
        self.settings = settings
        self.lessons = lessons or []

    async def run(
        self,
        question: str,
        *,
        trace_id: str | None = None,
        on_span: Callable[[Span], None] | None = None,
    ) -> DeliberationResult:
        question = screen_input(question)
        tracer = Tracer(trace_id, trace_dir=self.settings.trace_dir)
        if on_span is not None:
            tracer.subscribe(on_span)
        ledger = BudgetLedger(self.settings.budget)
        blackboard = Blackboard(question=question)
        ctx = AgentContext(blackboard, ledger, tracer, lessons=self.lessons)
        degraded: list[str] = []

        with tracer.span("deliberation", kind="root", question=question[:200]):
            framer = Framer(build_client(self.settings, persona="neutral", index=0))
            tracer.announce("chamber", who="framer", action="framing the question")
            with tracer.span("phase.frame"):
                frame = await framer.run(ctx, question, self.settings.budget.max_jurors)

            jurors = spawn_jury(frame, self.settings)
            adversary = Adversary(build_client(self.settings, persona="adversary", index=90))
            moderator = Moderator(build_client(self.settings, persona="neutral", index=91))
            verifier = Verifier(build_client(self.settings, persona="skeptic", index=92))
            synthesizer = Synthesizer(build_client(self.settings, persona="neutral", index=93))
            controller = TerminationController(self.settings)

            tracer.event(
                "jury.spawned",
                count=len(jurors),
                perspectives=[j.perspective for j in jurors],
                models=sorted({j.client.model for j in jurors}),
            )

            decision = TerminationDecision(False, StopReason.CONTINUE, "not started")
            round_index = 0
            try:
                for round_index in range(self.settings.budget.max_rounds):
                    ctx.round_index = round_index
                    blackboard.round_index = round_index
                    tracer.announce(
                        "chamber",
                        who="panel",
                        action=(
                            "independent drafts"
                            if round_index == 0
                            else "cross-examination"
                        ),
                        round=round_index,
                    )
                    with tracer.span("phase.round", round=round_index):
                        await self._run_round(
                            ctx, jurors, adversary, moderator, verifier, question,
                            round_index, degraded,
                        )
                    decision = controller.evaluate(blackboard, ledger, round_index)
                    tracer.event(
                        "round.complete",
                        round=round_index,
                        stop=decision.stop,
                        reason=decision.reason.value,
                        agreement=round(decision.agreement, 3),
                    )
                    if decision.stop:
                        break
            except BudgetExceeded as exc:
                degraded.append(f"budget: {exc}")
                decision = TerminationDecision(
                    True, StopReason.EXHAUSTION, str(exc), decision.agreement
                )

            tracer.announce("chamber", who="synthesizer", action="writing the verdict")
            with tracer.span("phase.synthesis"):
                try:
                    verdict = await synthesizer.synthesize(
                        ctx, question, decision.reason, decision.agreement
                    )
                except (StructuredParseError, BudgetExceeded) as exc:
                    degraded.append(f"synthesis failed: {exc}")
                    verdict = self._fallback_verdict(ctx, question, decision)

        tracer.export()
        return DeliberationResult(
            verdict=verdict,
            blackboard=blackboard,
            ledger=ledger,
            tracer=tracer,
            stop_reason=decision.reason,
            agreement=decision.agreement,
            degraded=degraded,
        )

    # --- round mechanics --------------------------------------------------
    def _eject(
        self,
        name: str,
        ctx: AgentContext,
        degraded: list[str],
        round_index: int,
        exc: BaseException,
        *,
        roster: list[Juror] | None = None,
    ) -> None:
        degraded.append(f"{name} failed round {round_index}: {exc}")
        ctx.blackboard.silence(name)
        ctx.tracer.event("agent.failed", agent=name, error=str(exc)[:400])
        if roster is not None:
            roster[:] = [agent for agent in roster if agent.name != name]

    async def _run_round(
        self,
        ctx: AgentContext,
        jurors: list[Juror],
        adversary: Adversary,
        moderator: Moderator,
        verifier: Verifier,
        question: str,
        round_index: int,
        degraded: list[str],
    ) -> None:
        jurors[:] = [j for j in jurors if j.name not in ctx.blackboard.silenced]
        blind = round_index == 0
        tasks = [
            (j.draft(ctx, question) if blind else j.cross_examine(ctx, question)) for j in jurors
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for juror, result in zip(jurors[:], results, strict=True):
            if isinstance(result, Position):
                ctx.blackboard.submit(result)
            elif isinstance(result, BudgetExceeded):
                raise result
            else:
                # One agent failing must not void the panel, and its error output
                # must not become material for anyone still in the discussion.
                self._eject(juror.name, ctx, degraded, round_index, result, roster=jurors)

        if not ctx.blackboard.current_positions():
            raise BudgetExceeded("jurors", 0, 1)

        if not blind and adversary.name not in ctx.blackboard.silenced:
            ctx.tracer.announce("chamber", who="adversary", action="attacking the lead")
            try:
                ctx.blackboard.submit(await adversary.attack(ctx, question))
            except BudgetExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 - eject, do not feed the error to peers
                self._eject(adversary.name, ctx, degraded, round_index, exc)

        if moderator.name not in ctx.blackboard.silenced:
            ctx.tracer.announce("chamber", who="moderator", action="isolating disagreements")
            try:
                await moderator.isolate_cruxes(ctx, question)
            except BudgetExceeded:
                raise
            except Exception as exc:  # noqa: BLE001
                self._eject(moderator.name, ctx, degraded, round_index, exc)

        if verifier.name not in ctx.blackboard.silenced:
            ctx.tracer.announce("chamber", who="verifier", action="checking claims")
            try:
                await verifier.verify(ctx)
            except BudgetExceeded:
                raise
            except Exception as exc:  # noqa: BLE001
                self._eject(verifier.name, ctx, degraded, round_index, exc)

    @staticmethod
    def _fallback_verdict(
        ctx: AgentContext, question: str, decision: TerminationDecision
    ) -> Verdict:
        """Never return nothing. A degraded, honest verdict beats an exception."""
        board = ctx.blackboard
        leading = max(board.current_positions(), key=lambda p: p.confidence, default=None)
        return Verdict(
            question=question,
            question_type=board.frame.question_type if board.frame else None,  # type: ignore[arg-type]
            outcome=Outcome.UNRESOLVED,
            answer=(
                leading.summary
                if leading
                else "The panel produced no usable position before failing."
            ),
            confidence=0.3,
            unresolved=[c.description for c in board.open_cruxes()[:5]]
            or ["synthesis failed; this is the leading position only, unsynthesized"],
            rounds_used=ctx.round_index + 1,
            jurors=board.authors(),
            tokens_used=ctx.ledger.tokens,
            trace_id=ctx.tracer.trace_id,
        )
