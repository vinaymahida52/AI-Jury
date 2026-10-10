"""Top-level entry point.

Deliberate, and fall back to the baseline if deliberation cannot complete. The
caller always gets a Verdict.
"""

from __future__ import annotations

from dataclasses import dataclass

from aijury.baseline import answer_baseline
from aijury.config import Settings
from aijury.contracts.verdict import Verdict
from aijury.learning.loop import (
    build_deliberation_context,
    ensure_thread,
    persist_deliberation,
    record_turn,
)
from aijury.protocol.deliberation import Deliberation, DeliberationResult
from aijury.security.injection import screen_input


@dataclass
class PipelineResult:
    verdict: Verdict
    deliberation: DeliberationResult | None
    used_fallback: bool = False
    fallback_reason: str = ""
    case_id: str | None = None
    thread_id: str | None = None


class JuryPipeline:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()

    async def ask(
        self,
        question: str,
        *,
        use_lessons: bool = True,
        thread_id: str | None = None,
    ) -> PipelineResult:
        # Validate at the boundary. Bad input is a caller error and must fail fast
        # rather than burn a fallback model call on a question we already rejected.
        question = screen_input(question)
        tid = ensure_thread(self.settings, thread_id=thread_id, question=question)
        ctx = build_deliberation_context(
            self.settings, question, use_lessons=use_lessons, thread_id=tid
        )
        deliberation = Deliberation(
            self.settings,
            lessons=ctx.lessons,
            prior_knowledge=ctx.prior_knowledge,
        )
        try:
            result = await deliberation.run(question)
            case_id = persist_deliberation(self.settings, result)
            try:
                record_turn(
                    self.settings,
                    thread_id=tid,
                    question=question,
                    answer=result.verdict.answer,
                    case_id=case_id,
                )
            except Exception:  # noqa: BLE001
                pass
            return PipelineResult(
                verdict=result.verdict,
                deliberation=result,
                case_id=case_id,
                thread_id=tid,
            )
        except Exception as exc:  # noqa: BLE001 - last line of defence before the caller
            verdict = await answer_baseline(question, self.settings)
            return PipelineResult(
                verdict=verdict,
                deliberation=None,
                used_fallback=True,
                fallback_reason=f"{type(exc).__name__}: {exc}",
                thread_id=tid,
            )
