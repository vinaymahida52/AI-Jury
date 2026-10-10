import os

import pytest

from aijury.config import Budget, Settings
from aijury.contracts.messages import Claim, Position
from aijury.core.blackboard import Blackboard
from aijury.core.budget import BudgetExceeded, BudgetLedger
from aijury.core.termination import StopReason, TerminationController, agreement_score
from aijury.core.tracing import Tracer


def _pos(author, summary, round_index=0, confidence=0.7):
    return Position(
        author=author, summary=summary, round_index=round_index, confidence=confidence
    )


def test_budget_raises_on_token_exhaustion():
    ledger = BudgetLedger(Budget(max_tokens=100))
    ledger.record("a", 60, 60)
    with pytest.raises(BudgetExceeded):
        ledger.check()


def test_blackboard_logs_belief_change():
    board = Blackboard(question="q")
    board.submit(_pos("j1", "the answer is A"))
    board.submit(_pos("j1", "the answer is B", round_index=1))
    assert len(board.belief_changes) == 1
    assert board.positions[-1].changed_from_previous


def test_transcript_anonymization_hides_authors():
    board = Blackboard(question="q")
    board.submit(_pos("juror_alpha", "position one"))
    text = board.transcript(anonymized=True)
    assert "juror_alpha" not in text and "Position 1" in text


def test_transcript_can_mark_verified_claims():
    board = Blackboard(question="q")
    position = _pos("j1", "s")
    position.claims = [
        Claim(text="ok", author="j1", round_index=0, verified=True),
        Claim(text="bad", author="j1", round_index=0, verified=False, verification_note="no"),
    ]
    board.submit(position)
    text = board.transcript(with_verification=True)
    assert "[verified]" in text
    assert "[failed: no]" in text
    assert "[verified]" not in board.transcript()


def test_current_positions_takes_latest_per_author():
    board = Blackboard(question="q")
    board.submit(_pos("j1", "old"))
    board.submit(_pos("j1", "new", round_index=1))
    assert [p.summary for p in board.current_positions()] == ["new"]


def test_silenced_author_is_kept_on_record_but_left_out_of_discussion():
    board = Blackboard(question="q")
    board.submit(_pos("j1", "UNIQUE_ERROR_OUTPUT_TOKEN"))
    board.submit(_pos("j2", "a usable position"))
    board.silence("j1")
    assert "UNIQUE_ERROR_OUTPUT_TOKEN" not in board.transcript()
    assert [p.author for p in board.current_positions()] == ["j2"]
    assert any(p.author == "j1" for p in board.positions)


def test_agreement_score_high_for_identical_positions():
    board = Blackboard(question="q")
    board.submit(_pos("j1", "the answer is clearly forty two"))
    board.submit(_pos("j2", "the answer is clearly forty two"))
    assert agreement_score(board) > 0.95


def test_stable_divergence_is_detected_as_grey_area():
    settings = Settings(budget=Budget(max_rounds=10), stability_window=2)
    controller = TerminationController(settings)
    board = Blackboard(question="q")
    board.submit(_pos("j1", "strongly favour option alpha for reasons of cost"))
    board.submit(_pos("j2", "strongly oppose option alpha on grounds of risk"))
    ledger = BudgetLedger(Budget(max_rounds=10))
    for round_index in range(4):
        decision = controller.evaluate(board, ledger, round_index)
    assert decision.stop and decision.reason is StopReason.STABLE_DIVERGENCE


def test_round_cap_terminates():
    settings = Settings(budget=Budget(max_rounds=1))
    controller = TerminationController(settings)
    board = Blackboard(question="q")
    board.submit(_pos("j1", "strongly favour option alpha for reasons of cost"))
    board.submit(_pos("j2", "strongly oppose option alpha on grounds of risk"))
    decision = controller.evaluate(board, BudgetLedger(Budget(max_rounds=1)), 0)
    assert decision.stop and decision.reason is StopReason.EXHAUSTION


def test_consensus_is_preferred_to_the_round_cap():
    """Rounds continue for an outcome, not because a counter ran out."""
    settings = Settings(budget=Budget(max_rounds=1))
    controller = TerminationController(settings)
    board = Blackboard(question="q")
    board.submit(_pos("j1", "the answer is clearly forty two"))
    board.submit(_pos("j2", "the answer is clearly forty two"))
    decision = controller.evaluate(board, BudgetLedger(Budget(max_rounds=1)), 0)
    assert decision.stop and decision.reason is StopReason.CONSENSUS


def test_tracer_records_error_on_span():
    tracer = Tracer()
    with pytest.raises(ValueError), tracer.span("boom"):
        raise ValueError("x")
    assert tracer.spans[0].error and "ValueError" in tracer.spans[0].error


def test_tracer_announce_reaches_listeners_but_not_the_trace():
    tracer = Tracer()
    seen: list[str] = []
    tracer.subscribe(lambda span: seen.append(span.kind))
    tracer.announce("chamber", who="framer")
    assert seen == ["live"]
    assert tracer.spans == []


def test_unverified_claims_excludes_uncheckable():
    board = Blackboard(question="q")
    position = _pos("j1", "s")
    position.claims = [
        Claim(text="a", author="j1", round_index=0),
        Claim(text="b", author="j1", round_index=0, checkable=False),
    ]
    board.submit(position)
    assert len(board.unverified_claims()) == 1


def test_dotenv_later_lines_in_the_same_file_win(tmp_path, monkeypatch):
    from aijury.config import load_dotenv

    env = tmp_path / ".env"
    env.write_text("AIJURY_PROVIDER=mock\nAIJURY_PROVIDER=hcnsec\n")
    monkeypatch.delenv("AIJURY_PROVIDER", raising=False)
    load_dotenv(env)
    assert os.environ["AIJURY_PROVIDER"] == "hcnsec"


def test_dotenv_loads_values(tmp_path, monkeypatch):
    from aijury.config import load_dotenv

    env = tmp_path / ".env"
    env.write_text('AIJURY_MAX_ROUNDS=9\n# comment\nAIJURY_MODEL="quoted-model"\n\n')
    monkeypatch.delenv("AIJURY_MAX_ROUNDS", raising=False)
    monkeypatch.delenv("AIJURY_MODEL", raising=False)
    load_dotenv(env)
    assert os.environ["AIJURY_MAX_ROUNDS"] == "9"
    assert os.environ["AIJURY_MODEL"] == "quoted-model"


def test_real_env_wins_over_dotenv(tmp_path, monkeypatch):
    """A value exported in the shell must not be silently replaced by a file."""
    from aijury.config import load_dotenv

    env = tmp_path / ".env"
    env.write_text("AIJURY_PROVIDER=mock\n")
    monkeypatch.setenv("AIJURY_PROVIDER", "anthropic")
    load_dotenv(env)
    assert os.environ["AIJURY_PROVIDER"] == "anthropic"


def test_dotenv_missing_file_is_not_an_error(tmp_path):
    from aijury.config import load_dotenv

    assert load_dotenv(tmp_path / "nope.env") == {}


def test_settings_from_env_reads_dotenv(tmp_path, monkeypatch):
    from aijury.config import Settings

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("AIJURY_MAX_JURORS=2\n")
    monkeypatch.delenv("AIJURY_MAX_JURORS", raising=False)
    assert Settings.from_env().budget.max_jurors == 2
