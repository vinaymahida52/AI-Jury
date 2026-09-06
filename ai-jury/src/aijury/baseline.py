"""Phase 1: single-agent baseline.

The control condition. If the full jury does not beat this on the same eval set
at comparable cost, the jury is an expensive complication and should not ship.
Keep this permanently — it is also the fallback path when deliberation times out.
"""

from __future__ import annotations

from aijury.config import Settings
from aijury.contracts.taxonomy import QuestionType
from aijury.contracts.verdict import Outcome, Verdict
from aijury.core.budget import BudgetLedger
from aijury.core.tracing import Tracer
from aijury.llm.base import complete_structured
from aijury.llm.registry import build_client
from aijury.security.injection import screen_input

_SYSTEM = """Answer the question directly and completely.

Give a calibrated confidence: the probability your answer is correct, not how
firmly you believe it. State your assumptions. If the question has no single
correct answer, say so and give the competing positions rather than picking one
arbitrarily."""


async def answer_baseline(question: str, settings: Settings) -> Verdict:
    question = screen_input(question)
    tracer = Tracer(trace_dir=settings.trace_dir)
    ledger = BudgetLedger(settings.budget)
    client = build_client(settings, persona="neutral", index=0)

    with tracer.span("baseline", kind="llm", model=client.model):
        verdict, response = await complete_structured(
            client, Verdict, _SYSTEM, f"Question:\n{question}", max_tokens=2500, temperature=0.4
        )
        ledger.record("baseline", response.tokens_in, response.tokens_out)

    verdict.question = question
    verdict.tokens_used = ledger.tokens
    verdict.duration_seconds = round(ledger.elapsed, 3)
    verdict.trace_id = tracer.trace_id
    verdict.jurors = ["baseline"]
    verdict.rounds_used = 1
    if verdict.outcome is Outcome.GREY_AREA and not verdict.what_would_change_this:
        verdict.what_would_change_this = ["unspecified by baseline model"]
    if verdict.question_type is None:  # type: ignore[comparison-overlap]
        verdict.question_type = QuestionType.ANALYTICAL
    tracer.export()
    return verdict
