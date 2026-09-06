"""Verifier plugin interface.

Deterministic checks live behind this protocol. They outrank model judgement
wherever they apply, which is the whole point: a checker that is structurally
stronger than the debaters is the only reliable source of a mistake signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from aijury.contracts.messages import Claim
from aijury.contracts.taxonomy import VerificationMethod


@dataclass
class VerificationResult:
    claim_id: str
    method: VerificationMethod
    passed: bool
    note: str = ""
    #: True when this check actually applied and its answer is authoritative.
    #: A non-decisive result means "this tool had nothing to say", not "pass".
    decisive: bool = False


@runtime_checkable
class Verifier(Protocol):
    method: VerificationMethod

    def applies(self, claim: Claim) -> bool: ...

    def check(self, claim: Claim) -> VerificationResult: ...
