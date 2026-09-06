"""Top-level entry point.

Deliberate, and fall back to the baseline if deliberation cannot complete. The
caller always gets a Verdict.
"""

from __future__ import annotations

from dataclasses import dataclass

from aijury.baseline import answer_baseline
from aijury.config import Settings
from aijury.contracts.verdict import Verdict
from aijury.learning.injector import load_lessons
from aijury.protocol.deliberation import Deliberation, DeliberationResult
from aijury.security.injection import screen_input


@dataclass
class PipelineResult:
    verdict: Verdict
    deliberation: DeliberationResult | None
    used_fallback: bool = False
    fallback_reason: str = ""


class JuryPipeline:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()

    async def ask(self, question: str, *, use_lessons: bool = True) -> PipelineResult:
        # Validate at the boundary. Bad input is a caller error and must fail fast
        # rather than burn a fallback model call on a question we already rejected.
        question = screen_input(question)
        lessons = load_lessons(self.settings) if use_lessons else []
        deliberation = Deliberation(self.settings, lessons=lessons)
        try:
            result = await deliberation.run(question)
            return PipelineResult(verdict=result.verdict, deliberation=result)
        except Exception as exc:  # noqa: BLE001 - last line of defence before the caller
            verdict = await answer_baseline(question, self.settings)
            return PipelineResult(
                verdict=verdict,
                deliberation=None,
                used_fallback=True,
                fallback_reason=f"{type(exc).__name__}: {exc}",
            )
