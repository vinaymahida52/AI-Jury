"""Conversation threads: follow-ups and past-chat listing."""

from __future__ import annotations

from aijury.config import Budget, Settings
from aijury.contracts.taxonomy import QuestionType
from aijury.contracts.verdict import Outcome, Verdict
from aijury.core.blackboard import Blackboard
from aijury.core.budget import BudgetLedger
from aijury.core.termination import StopReason
from aijury.core.tracing import Tracer
from aijury.learning.repository import FileLearningRepository
from aijury.protocol.deliberation import DeliberationResult


def _settings(tmp_path) -> Settings:
    return Settings(
        provider="mock",
        budget=Budget(max_rounds=2, max_jurors=2, max_tokens=50_000, max_llm_calls=40),
        trace_dir=str(tmp_path / "traces"),
        failure_dir=str(tmp_path / "failures"),
        gateways_path=str(tmp_path / "gateways.json"),
        database_url="",
    )


def _result(question: str, answer: str = "yes") -> DeliberationResult:
    board = Blackboard(question=question)
    verdict = Verdict(
        question=question,
        question_type=QuestionType.FACTUAL,
        outcome=Outcome.RESOLVED,
        answer=answer,
        confidence=0.7,
        rounds_used=1,
        jurors=["juror_1"],
        tokens_used=5,
        duration_seconds=0.1,
        trace_id="tr1",
    )
    settings = Settings(provider="mock", budget=Budget(max_rounds=2, max_jurors=2))
    return DeliberationResult(
        verdict=verdict,
        blackboard=board,
        ledger=BudgetLedger(settings.budget),
        tracer=Tracer("tr1"),
        stop_reason=StopReason.CONSENSUS,
        agreement=1.0,
    )


def test_create_thread_and_append_turn(tmp_path):
    repo = FileLearningRepository(_settings(tmp_path))
    thread = repo.create_thread(title="Should we migrate?")
    assert thread.id
    case_id = repo.persist_case(_result("Should we migrate?"), provider="mock", model="mock")
    repo.append_message(thread.id, role="user", content="Should we migrate?")
    repo.append_message(
        thread.id, role="assistant", content="Yes, with caveats.", case_id=case_id
    )

    detail = repo.get_thread(thread.id)
    assert detail is not None
    assert len(detail.messages) == 2
    assert detail.messages[0].role == "user"
    assert detail.messages[1].case_id == case_id


def test_list_threads_orders_by_recent(tmp_path):
    repo = FileLearningRepository(_settings(tmp_path))
    older = repo.create_thread(title="Old topic")
    newer = repo.create_thread(title="New topic")
    repo.append_message(newer.id, role="user", content="follow up")
    listed = repo.list_threads()
    assert listed[0].id == newer.id
    assert {t.id for t in listed} >= {older.id, newer.id}


def test_thread_history_lines_for_followup_context(tmp_path):
    repo = FileLearningRepository(_settings(tmp_path))
    thread = repo.create_thread(title="Billing")
    repo.append_message(thread.id, role="user", content="Should we use event sourcing?")
    repo.append_message(thread.id, role="assistant", content="Only for the ledger.")
    lines = repo.thread_history_lines(thread.id)
    assert any("event sourcing" in line for line in lines)
    assert any("ledger" in line for line in lines)
