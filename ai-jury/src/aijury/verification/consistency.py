"""Structural consistency checks.

Cheap, deterministic, and catch a surprising share of real defects: claims with
no evidence, claims contradicting an already-verified claim, and confidence that
outruns support.
"""

from __future__ import annotations

import re

from aijury.contracts.messages import Claim, EvidenceKind
from aijury.contracts.taxonomy import VerificationMethod
from aijury.verification.base import VerificationResult

_HEDGE = re.compile(
    r"\b(always|never|all|none|every|guaranteed|impossible|certainly|definitely)\b",
    re.IGNORECASE,
)


class ConsistencyVerifier:
    """Flags claims whose support cannot carry their strength."""

    method = VerificationMethod.CONSISTENCY

    def applies(self, claim: Claim) -> bool:
        return True

    def check(self, claim: Claim) -> VerificationResult:
        if not claim.evidence:
            return VerificationResult(
                claim.id,
                self.method,
                False,
                "claim carries no evidence of any kind",
                decisive=True,
            )
        only_assertion = all(e.kind is EvidenceKind.ASSERTION for e in claim.evidence)
        absolute = bool(_HEDGE.search(claim.text))
        if absolute and only_assertion:
            return VerificationResult(
                claim.id,
                self.method,
                False,
                "universal claim backed only by assertion",
                decisive=True,
            )
        if only_assertion:
            return VerificationResult(
                claim.id,
                self.method,
                False,
                "backed only by assertion; needs a source, computation, or execution",
                decisive=False,
            )
        return VerificationResult(
            claim.id, self.method, True, f"support weight {claim.support:.2f}", decisive=False
        )


def contradiction_pairs(claims: list[Claim]) -> list[tuple[str, str]]:
    """Detect crude direct negations among claims.

    Intentionally simple. Real contradiction detection is a research problem; this
    catches the blatant cases cheaply and hands the rest to the model verifier.
    """
    pairs: list[tuple[str, str]] = []
    normalized = {c.id: re.sub(r"\s+", " ", c.text.strip().lower()) for c in claims}
    for i, (id_a, text_a) in enumerate(normalized.items()):
        for id_b, text_b in list(normalized.items())[i + 1 :]:
            negated = text_a.replace(" not ", " ").replace(" no ", " ")
            other = text_b.replace(" not ", " ").replace(" no ", " ")
            differs_by_negation = (" not " in text_a) != (" not " in text_b)
            if differs_by_negation and negated == other:
                pairs.append((id_a, id_b))
    return pairs
