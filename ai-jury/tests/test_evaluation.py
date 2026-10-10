from aijury.contracts.taxonomy import QuestionType
from aijury.contracts.verdict import Dissent, Outcome, Verdict
from aijury.evaluation.harness import load_dataset, run_eval
from aijury.evaluation.scorer import expected_calibration_error, score_verdict

GOLDEN = "src/aijury/evaluation/datasets/golden.jsonl"


def _verdict(answer, outcome=Outcome.RESOLVED, confidence=0.8, qtype=QuestionType.FACTUAL):
    kwargs = dict(
        question="q", question_type=qtype, outcome=outcome, answer=answer, confidence=confidence
    )
    if outcome is Outcome.GREY_AREA:
        kwargs["dissent"] = [Dissent(author="a", position="p", reason="r", confidence=0.5)]
    return Verdict(**kwargs)


def test_asserting_consensus_on_grey_question_is_false_consensus():
    score = score_verdict(
        _verdict("Definitely yes.", qtype=QuestionType.GREY_NORMATIVE),
        expected_answer="contested, no consensus",
        expected_type=QuestionType.GREY_NORMATIVE,
    )
    assert score.false_consensus


def test_grey_verdict_on_grey_question_is_not_false_consensus():
    score = score_verdict(
        _verdict("contested, no consensus", Outcome.GREY_AREA, qtype=QuestionType.GREY_NORMATIVE),
        expected_answer="contested, no consensus",
        expected_type=QuestionType.GREY_NORMATIVE,
    )
    assert not score.false_consensus and score.correct


def test_confidently_wrong_is_flagged():
    score = score_verdict(
        _verdict("completely unrelated text", confidence=0.95),
        expected_answer="the actual answer",
    )
    assert score.false_consensus and score.brier > 0.8


def test_ece_is_zero_for_perfect_calibration():
    pairs = [(1.0, True)] * 10 + [(0.0, False)] * 10
    assert expected_calibration_error(pairs) < 1e-9


def test_ece_penalizes_overconfidence():
    assert expected_calibration_error([(0.95, False)] * 10) > 0.9


def test_golden_dataset_loads_and_covers_all_types():
    cases = load_dataset(GOLDEN)
    assert len(cases) >= 10
    assert {c.question_type for c in cases} == set(QuestionType)


async def test_eval_harness_runs_both_arms(settings):
    cases = load_dataset(GOLDEN)[:3]
    report = await run_eval(cases, settings, concurrency=3)
    assert report.jury.n == 3 and report.baseline.n == 3
    assert isinstance(report.jury_beats_baseline, bool)
    assert "ship gate" in report.render()
