from aijury.agents.spawner import spawn_jury
from aijury.contracts.taxonomy import Frame, QuestionType
from aijury.contracts.verdict import Outcome
from aijury.pipeline import JuryPipeline
from aijury.protocol.deliberation import Deliberation


def _frame(perspectives, qtype=QuestionType.ANALYTICAL):
    return Frame(
        question="q",
        question_type=qtype,
        restated_question="q",
        required_perspectives=perspectives,
    )


def test_spawner_caps_jury_size(settings):
    frame = _frame([f"perspective {i}" for i in range(20)])
    assert len(spawn_jury(frame, settings)) <= settings.budget.max_jurors


def test_spawner_deduplicates_perspectives(settings):
    jurors = spawn_jury(_frame(["cost", "Cost", "COST", "risk"]), settings)
    assert len(jurors) == 2


def test_spawner_follows_required_perspectives(settings):
    """Panel size is the framed requirement, capped by max_jurors, at least one."""
    assert len(spawn_jury(_frame(["only one"]), settings)) == 1


def test_spawner_allows_a_single_juror_when_capped_at_one(settings):
    from dataclasses import replace

    from aijury.config import Budget

    tight = replace(settings, budget=Budget(max_rounds=2, max_jurors=1, max_llm_calls=50))
    assert len(spawn_jury(_frame(["cost", "risk", "legal"]), tight)) == 1


def test_spawner_falls_back_when_no_perspectives(settings):
    assert len(spawn_jury(_frame([]), settings)) >= 1


async def test_deliberation_produces_a_verdict(settings):
    result = await Deliberation(settings).run("Should we adopt microservices?")
    verdict = result.verdict
    assert verdict.answer
    assert 0.0 <= verdict.confidence <= 1.0
    assert verdict.rounds_used >= 1
    assert verdict.trace_id


async def test_deliberation_respects_round_cap(settings):
    result = await Deliberation(settings).run("A hard question with no easy answer.")
    assert result.verdict.rounds_used <= settings.budget.max_rounds


async def test_verdict_does_not_leak_deliberation_transcript(settings):
    """Output contract: results, not thinking."""
    result = await Deliberation(settings).run("What should we do about X?")
    rendered = result.verdict.render().lower()
    for leak in ("juror_1", "adversary said", "round 0", "the panel debated"):
        assert leak not in rendered


async def test_pipeline_rejects_invalid_input_without_spending_a_call(settings):
    """Bad input fails fast at the boundary rather than falling back."""
    import pytest

    from aijury.core.errors import UnsafeInputError

    with pytest.raises(UnsafeInputError):
        await JuryPipeline(settings).ask("   ")


async def test_pipeline_falls_back_when_deliberation_raises(settings, monkeypatch):
    async def boom(self, question, **kwargs):
        raise RuntimeError("orchestrator exploded")

    monkeypatch.setattr(Deliberation, "run", boom)
    result = await JuryPipeline(settings).ask("A real question?")
    assert result.used_fallback and result.verdict.answer


async def test_trace_is_exported_to_disk(settings):
    import os

    result = await Deliberation(settings).run("Is this traced?")
    assert os.path.exists(os.path.join(settings.trace_dir, f"{result.tracer.trace_id}.jsonl"))


async def test_budget_exhaustion_still_returns_a_verdict(settings):
    from dataclasses import replace

    from aijury.config import Budget

    tight = replace(settings, budget=Budget(max_rounds=3, max_jurors=3, max_llm_calls=3))
    result = await Deliberation(tight).run("Anything")
    assert result.verdict.outcome in set(Outcome)


async def test_open_cruxes_prevent_a_clean_resolved_verdict(settings):
    """Structural guard against reporting consensus over an unresolved crux."""
    from aijury.contracts.verdict import Outcome

    result = await Deliberation(settings).run("A contested question with real tradeoffs?")
    if result.blackboard.open_cruxes():
        assert result.verdict.outcome is not Outcome.RESOLVED


async def test_failed_juror_is_ejected_and_error_is_not_discussed(settings, monkeypatch):
    """A crashing agent leaves the panel; its error text never becomes debate material."""
    from aijury.agents.spawner import spawn_jury as real_spawn
    from aijury.core.termination import StopReason, TerminationController, TerminationDecision

    error = "UNIQUE_AGENT_CRASH_TOKEN_9f3a"

    def run_all_rounds(self, blackboard, ledger, round_index):
        stop = round_index + 1 >= settings.budget.max_rounds
        return TerminationDecision(
            stop,
            StopReason.EXHAUSTION if stop else StopReason.CONTINUE,
            "test-forced",
            0.0,
        )

    monkeypatch.setattr(TerminationController, "evaluate", run_all_rounds)

    class Boom:
        model = "boom"

        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, system, prompt, *, max_tokens=2000, temperature=0.7):
            self.calls += 1
            raise RuntimeError(error)

    boom = Boom()

    def spawn(frame, spawned_settings):
        jurors = real_spawn(frame, spawned_settings)
        jurors[0].client = boom
        return jurors

    monkeypatch.setattr("aijury.protocol.deliberation.spawn_jury", spawn)
    result = await Deliberation(settings).run("Should we ship the migration?")

    assert boom.calls == 1, "retries are not the issue; the juror must be gone after one crash"
    assert any("failed" in note for note in result.degraded)
    assert error not in result.blackboard.transcript()
    assert error not in result.verdict.answer
    assert all(error not in m.content for m in result.blackboard.messages)
    assert all(error not in p.summary for p in result.blackboard.positions)


async def test_failed_adversary_is_skipped_in_later_rounds(settings, monkeypatch):
    from aijury.agents.adversary import Adversary
    from aijury.core.termination import StopReason, TerminationController, TerminationDecision

    def run_all_rounds(self, blackboard, ledger, round_index):
        stop = round_index + 1 >= settings.budget.max_rounds
        return TerminationDecision(
            stop,
            StopReason.EXHAUSTION if stop else StopReason.CONTINUE,
            "test-forced",
            0.0,
        )

    monkeypatch.setattr(TerminationController, "evaluate", run_all_rounds)

    error = "UNIQUE_ADVERSARY_CRASH_TOKEN_b7c1"
    calls = {"n": 0}

    async def boom(self, ctx, question):
        calls["n"] += 1
        raise RuntimeError(error)

    monkeypatch.setattr(Adversary, "attack", boom)
    result = await Deliberation(settings).run("A question the adversary will fail on?")
    assert calls["n"] == 1, "a crashed adversary must not be invited back"
    assert any("adversary" in note for note in result.degraded)
    assert error not in result.blackboard.transcript()
    assert not any(p.author == "adversary" for p in result.blackboard.positions)
