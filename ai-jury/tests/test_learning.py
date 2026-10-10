from aijury.learning.failure_store import FailureRecord, FailureStore
from aijury.learning.injector import load_lessons
from aijury.learning.lesson_extractor import extract_lessons, failure_summary, save_lessons


def _failure(idx, **kwargs):
    base = dict(
        id=f"f{idx}",
        question="q",
        question_type="analytical",
        expected="right",
        produced="wrong",
        confidence=0.9,
        outcome="resolved",
        signal="eval_ground_truth",
        introduced_by="juror_1",
        survived_rounds=3,
    )
    base.update(kwargs)
    return FailureRecord(**base)


def test_single_failure_does_not_become_a_lesson():
    """Promotion threshold: one failure is noise, not a pattern."""
    assert extract_lessons([_failure(0)]) == []


def test_recurring_pattern_is_promoted():
    lessons = extract_lessons([_failure(i) for i in range(5)])
    patterns = {lesson.pattern for lesson in lessons}
    assert "overconfidence" in patterns
    assert "survived_cross_examination" in patterns


def test_failure_summary_attributes_errors_to_agents():
    failures = [_failure(0), _failure(1, introduced_by="adversary")]
    assert failure_summary(failures) == {"juror_1": 1, "adversary": 1}


def test_store_roundtrip(settings):
    store = FailureStore(settings)
    store.record(_failure(0))
    store.record(_failure(1))
    assert len(store.all()) == 2


def test_only_active_lessons_are_injected(settings):
    lessons = extract_lessons([_failure(i) for i in range(5)])
    for lesson in lessons:
        lesson.active = False
    save_lessons(lessons, settings)
    assert load_lessons(settings) == []


def test_injection_is_capped(settings):
    from aijury.learning.injector import MAX_INJECTED_LESSONS

    save_lessons(extract_lessons([_failure(i) for i in range(10)]), settings)
    assert len(load_lessons(settings)) <= MAX_INJECTED_LESSONS


def test_agent_scoped_lessons(settings):
    save_lessons(extract_lessons([_failure(i) for i in range(5)]), settings)
    adversary_lessons = load_lessons(settings, agent="adversary")
    assert all(isinstance(lesson, str) for lesson in adversary_lessons)
