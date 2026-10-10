"""When to stop arguing.

The most commonly underbuilt component in debate systems. Four distinct exits,
and conflating them is what produces either infinite loops or fake consensus:

  CONSENSUS   - positions aligned and verification clean
  STABLE_DIVERGENCE - positions unchanged across a window but still disagree.
                This is a *result*, not a failure: the question is a grey area.
  OSCILLATION - positions changing but claims repeating. Progress has stopped.
  EXHAUSTION  - token/time/call or safety round ceiling hit. Last resort only.
                Real outcomes (consensus, grey area, oscillation) win first.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum

from aijury.config import Settings
from aijury.core.blackboard import Blackboard
from aijury.core.budget import BudgetLedger


class StopReason(str, Enum):
    CONSENSUS = "consensus"
    STABLE_DIVERGENCE = "stable_divergence"
    OSCILLATION = "oscillation"
    EXHAUSTION = "exhaustion"
    CONTINUE = "continue"


@dataclass
class TerminationDecision:
    stop: bool
    reason: StopReason
    detail: str
    agreement: float = 0.0


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def agreement_score(blackboard: Blackboard) -> float:
    """Mean pairwise similarity of current position summaries, in [0, 1].

    Text similarity is a proxy, not a truth signal. It tells us whether the jury
    has stopped moving; it says nothing about whether it stopped somewhere correct.
    Verification is what supplies that, separately.
    """
    positions = blackboard.current_positions()
    if len(positions) < 2:
        return 1.0
    scores = [
        _similarity(a.summary, b.summary)
        for i, a in enumerate(positions)
        for b in positions[i + 1 :]
    ]
    return sum(scores) / len(scores)


class TerminationController:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.consensus_threshold = 0.78
        self._agreement_history: list[float] = []

    def evaluate(
        self, blackboard: Blackboard, ledger: BudgetLedger, round_index: int
    ) -> TerminationDecision:
        agreement = agreement_score(blackboard)
        self._agreement_history.append(agreement)

        unresolved = blackboard.open_cruxes()
        failed = blackboard.failed_claims()

        if agreement >= self.consensus_threshold and not unresolved and not failed:
            return TerminationDecision(
                True, StopReason.CONSENSUS, "positions aligned, no open cruxes", agreement
            )

        window = self.settings.stability_window
        if len(self._agreement_history) > window:
            recent = self._agreement_history[-(window + 1) :]
            drift = max(recent) - min(recent)
            churned = any(p.changed_from_previous for p in blackboard.positions_in_round(round_index))
            if drift < 0.05 and not churned:
                return TerminationDecision(
                    True,
                    StopReason.STABLE_DIVERGENCE,
                    f"positions stable across {window} rounds without converging",
                    agreement,
                )
            if drift < 0.05 and churned and self._claims_repeating(blackboard):
                return TerminationDecision(
                    True,
                    StopReason.OSCILLATION,
                    "positions churning while claims repeat; no new information",
                    agreement,
                )

        exhausted = ledger.exhausted()
        if exhausted:
            return TerminationDecision(
                True, StopReason.EXHAUSTION, f"{exhausted} budget exhausted", agreement
            )
        if round_index + 1 >= self.settings.budget.max_rounds:
            return TerminationDecision(
                True, StopReason.EXHAUSTION, "round cap reached", agreement
            )

        return TerminationDecision(False, StopReason.CONTINUE, "cruxes remain open", agreement)

    @staticmethod
    def _claims_repeating(blackboard: Blackboard, threshold: int = 3) -> bool:
        counts = blackboard.claim_repetition()
        return any(count >= threshold for count in counts.values())
