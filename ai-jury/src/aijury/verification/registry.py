"""Verifier dispatch."""

from __future__ import annotations

from collections.abc import Sequence

from aijury.contracts.messages import Claim
from aijury.contracts.taxonomy import VerificationMethod
from aijury.core.tracing import Tracer
from aijury.verification.base import VerificationResult, Verifier
from aijury.verification.code_execution import CodeExecutionVerifier
from aijury.verification.consistency import ConsistencyVerifier
from aijury.verification.recomputation import RecomputationVerifier


def default_verifiers(*, allow_code_execution: bool = False) -> list[Verifier]:
    return [
        RecomputationVerifier(),
        ConsistencyVerifier(),
        CodeExecutionVerifier(enabled=allow_code_execution),
    ]


def run_verifiers(
    claims: Sequence[Claim],
    methods: Sequence[VerificationMethod],
    tracer: Tracer | None = None,
    *,
    verifiers: Sequence[Verifier] | None = None,
) -> list[VerificationResult]:
    """Run every applicable verifier over every claim.

    A verifier failure is a defect in the verifier, not a failed claim, so
    exceptions are caught and recorded as non-decisive rather than silently
    marking the claim unverified.
    """
    pool = list(verifiers) if verifiers is not None else default_verifiers()
    allowed = set(methods)
    results: list[VerificationResult] = []
    for claim in claims:
        for verifier in pool:
            if verifier.method not in allowed or not verifier.applies(claim):
                continue
            try:
                result = verifier.check(claim)
            except Exception as exc:  # noqa: BLE001 - verifier defects must not halt deliberation
                result = VerificationResult(
                    claim.id, verifier.method, False, f"verifier error: {exc}", decisive=False
                )
            results.append(result)
            if tracer:
                tracer.event(
                    "verifier.result",
                    claim_id=claim.id,
                    method=verifier.method.value,
                    passed=result.passed,
                    decisive=result.decisive,
                )
    return results
