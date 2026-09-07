"""Closed learning loop: persist cases, failures, lessons, similar priors."""

from __future__ import annotations

from aijury.config import Budget, Settings
from aijury.contracts.taxonomy import QuestionType
from aijury.contracts.verdict import Outcome, SupportedConclusion, Verdict
from aijury.core.blackboard import Blackboard
from aijury.core.budget import BudgetLedger
from aijury.core.termination import StopReason
from aijury.core.tracing import Tracer
from aijury.learning.failure_store import FailureRecord
from aijury.learning.lesson_extractor import extract_lessons
from aijury.learning.repository import FileLearningRepository, get_repository
from aijury.protocol.deliberation import DeliberationResult


def _settings(tmp_path) -> Settings:
    return Settings(
        provider="mock",
        budget=Budget(max_rounds=3, max_jurors=3, max_tokens=50_000, max_llm_calls=50),
        trace_dir=str(tmp_path / "traces"),
        failure_dir=str(tmp_path / "failures"),
        gateways_path=str(tmp_path / "gateways.json"),
        database_url="",
    )


def _failure(idx: int, **kwargs: object) -> FailureRecord:
    base: dict = dict(
        id=f"f{idx}",
        question="What is 2+2?",
        question_type="factual",
        expected="4",
        produced="5",
        confidence=0.9,
        outcome="resolved",
        signal="eval_ground_truth",
        introduced_by="juror_1",
        survived_rounds=3,
        trace_id=f"t{idx}",
    )
    base.update(kwargs)
    return FailureRecord(**base)


def _result(question: str = "What is 2+2?") -> DeliberationResult:
    board = Blackboard(question=question)
    verdict = Verdict(
        question=question,
        question_type=QuestionType.FACTUAL,
        outcome=Outcome.RESOLVED,
        answer="4",
        confidence=0.8,
        conclusions=[
            SupportedConclusion(statement="2+2=4", support=["arithmetic"], verified=True)
        ],
        rounds_used=1,
        jurors=["juror_1"],
        tokens_used=10,
        duration_seconds=0.1,
        trace_id="trace-abc",
    )
    settings = Settings(provider="mock", budget=Budget(max_rounds=3, max_jurors=3))
    return DeliberationResult(
        verdict=verdict,
        blackboard=board,
        ledger=BudgetLedger(settings.budget),
        tracer=Tracer("trace-abc"),
        stop_reason=StopReason.CONSENSUS,
        agreement=1.0,
        degraded=[],
    )


def test_file_repo_persists_case_and_finds_similar(tmp_path):
    repo = FileLearningRepository(_settings(tmp_path))
    case_id = repo.persist_case(_result("Capital of France?"), provider="mock", model="mock")
    assert case_id
    repo.persist_case(_result("What is 2+2?"), provider="mock", model="mock")

    priors = repo.similar_cases("What is the capital of France?", limit=3)
    assert priors
    assert any("France" in p.question or "France" in p.answer for p in priors)


def test_file_repo_failure_and_lesson_roundtrip(tmp_path):
    repo = FileLearningRepository(_settings(tmp_path))
    for i in range(5):
        repo.record_failure(_failure(i))
    lessons = extract_lessons(repo.all_failures())
    assert lessons
    repo.save_lessons(lessons)
    loaded = repo.active_lesson_instructions()
    assert loaded
    assert all(isinstance(s, str) for s in loaded)


def test_factory_defaults_to_file_without_database_url(tmp_path):
    repo = get_repository(_settings(tmp_path))
    assert isinstance(repo, FileLearningRepository)


def test_feedback_links_failure_to_case(tmp_path):
    repo = FileLearningRepository(_settings(tmp_path))
    case_id = repo.persist_case(_result(), provider="mock", model="mock")
    record = repo.record_feedback(
        case_id,
        expected="4",
        signal="production_feedback",
    )
    assert record is not None
    assert record.case_id == case_id or record.trace_id == "trace-abc"
    assert len(repo.all_failures()) == 1
