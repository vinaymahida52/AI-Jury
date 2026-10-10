import pytest
from pydantic import ValidationError

from aijury.contracts.messages import Claim, Evidence, EvidenceKind
from aijury.contracts.taxonomy import QuestionType
from aijury.contracts.verdict import Dissent, Outcome, Verdict


def _verdict(**kwargs):
    base = dict(
        question="q",
        question_type=QuestionType.ANALYTICAL,
        outcome=Outcome.RESOLVED,
        answer="a",
        confidence=0.8,
    )
    base.update(kwargs)
    return Verdict(**base)


def test_grey_verdict_without_dissent_is_rejected():
    """The core guardrail: a grey-area result must map the disagreement."""
    with pytest.raises(ValidationError):
        _verdict(outcome=Outcome.GREY_AREA, question_type=QuestionType.GREY_NORMATIVE)


def test_grey_verdict_with_dissent_is_accepted():
    verdict = _verdict(
        outcome=Outcome.GREY_AREA,
        dissent=[Dissent(author="j1", position="p", reason="r", confidence=0.6)],
    )
    assert verdict.outcome is Outcome.GREY_AREA


def test_unresolved_cannot_be_confident():
    with pytest.raises(ValidationError):
        _verdict(outcome=Outcome.UNRESOLVED, confidence=0.9)


def test_execution_evidence_outweighs_assertion():
    execution = Evidence(kind=EvidenceKind.EXECUTION, content="ran", verified=True)
    assertion = Evidence(kind=EvidenceKind.ASSERTION, content="trust me")
    assert execution.weight > assertion.weight * 4


def test_claim_fingerprint_is_case_insensitive():
    a = Claim(text="The Sky Is Blue", author="x", round_index=0)
    b = Claim(text="the sky is blue  ", author="y", round_index=1)
    assert a.fingerprint == b.fingerprint
