"""Cost, call, and time ceilings.

A multi-agent debate has no natural stopping point, so cost control is a
first-class component rather than an afterthought. Every LLM call is metered
here and the ledger is what the termination controller consults.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from aijury.config import Budget
from aijury.core.errors import AIJuryError


class BudgetExceeded(AIJuryError):
    def __init__(self, resource: str, used: float, limit: float) -> None:
        super().__init__(f"budget exceeded: {resource} used={used:g} limit={limit:g}")
        self.resource = resource
        self.used = used
        self.limit = limit


@dataclass
class BudgetLedger:
    budget: Budget
    tokens_in: int = 0
    tokens_out: int = 0
    llm_calls: int = 0
    started_at: float = field(default_factory=time.perf_counter)
    per_agent_tokens: dict[str, int] = field(default_factory=dict)

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at

    def record(self, agent: str, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.llm_calls += 1
        self.per_agent_tokens[agent] = self.per_agent_tokens.get(agent, 0) + tokens_in + tokens_out

    def exhausted(self) -> str | None:
        """Return the name of the exhausted resource, or None."""
        if self.tokens >= self.budget.max_tokens:
            return "tokens"
        if self.llm_calls >= self.budget.max_llm_calls:
            return "llm_calls"
        if self.elapsed >= self.budget.max_wall_clock_seconds:
            return "wall_clock"
        return None

    def check(self) -> None:
        resource = self.exhausted()
        if resource == "tokens":
            raise BudgetExceeded("tokens", self.tokens, self.budget.max_tokens)
        if resource == "llm_calls":
            raise BudgetExceeded("llm_calls", self.llm_calls, self.budget.max_llm_calls)
        if resource == "wall_clock":
            raise BudgetExceeded(
                "wall_clock", self.elapsed, self.budget.max_wall_clock_seconds
            )

    def snapshot(self) -> dict[str, float]:
        return {
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "llm_calls": self.llm_calls,
            "elapsed_seconds": round(self.elapsed, 3),
        }
