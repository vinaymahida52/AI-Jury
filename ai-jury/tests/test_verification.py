from aijury.contracts.messages import Claim, Evidence, EvidenceKind
from aijury.contracts.taxonomy import VerificationMethod
from aijury.verification.consistency import ConsistencyVerifier
from aijury.verification.recomputation import RecomputationVerifier, safe_eval
from aijury.verification.registry import run_verifiers


def test_safe_eval_rejects_non_arithmetic():
    import pytest

    with pytest.raises(ValueError):
        safe_eval("__import__('os').system('ls')")


def test_recomputation_catches_wrong_arithmetic():
    claim = Claim(text="17 * 23 + 4 = 400", author="j", round_index=0)
    result = RecomputationVerifier().check(claim)
    assert result.decisive and not result.passed


def test_recomputation_passes_correct_arithmetic():
    claim = Claim(text="17 * 23 + 4 = 395", author="j", round_index=0)
    result = RecomputationVerifier().check(claim)
    assert result.decisive and result.passed


def test_consistency_rejects_evidence_free_claim():
    claim = Claim(text="X is true", author="j", round_index=0)
    result = ConsistencyVerifier().check(claim)
    assert result.decisive and not result.passed


def test_consistency_rejects_universal_claim_on_assertion_only():
    claim = Claim(
        text="This always works",
        author="j",
        round_index=0,
        evidence=[Evidence(kind=EvidenceKind.ASSERTION, content="obviously")],
    )
    result = ConsistencyVerifier().check(claim)
    assert result.decisive and not result.passed


def test_registry_respects_method_allowlist():
    claim = Claim(text="2 + 2 = 5", author="j", round_index=0)
    results = run_verifiers([claim], [VerificationMethod.RETRIEVAL])
    assert results == []


def test_verifier_defect_does_not_halt_deliberation():
    class Exploding:
        method = VerificationMethod.CONSISTENCY

        def applies(self, claim):
            return True

        def check(self, claim):
            raise RuntimeError("boom")

    claim = Claim(text="x", author="j", round_index=0)
    results = run_verifiers(
        [claim], [VerificationMethod.CONSISTENCY], verifiers=[Exploding()]
    )
    assert len(results) == 1 and not results[0].decisive
