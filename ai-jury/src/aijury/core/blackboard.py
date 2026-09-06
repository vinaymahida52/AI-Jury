"""Shared, append-only case file.

Single source of truth for a deliberation. Append-only because the failure store
needs to reconstruct exactly what each agent saw when it made a claim; mutable
state makes post-hoc attribution impossible.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from aijury.contracts.messages import AgentMessage, Claim, Crux, Position
from aijury.contracts.taxonomy import Frame


@dataclass
class Blackboard:
    question: str
    frame: Frame | None = None
    messages: list[AgentMessage] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    claims: dict[str, Claim] = field(default_factory=dict)
    cruxes: list[Crux] = field(default_factory=list)
    belief_changes: list[dict[str, str | int]] = field(default_factory=list)
    round_index: int = 0
    #: Authors ejected mid-deliberation. History stays on the board for the
    #: operator; these names are omitted from anything other agents read.
    silenced: set[str] = field(default_factory=set)

    # --- writes -----------------------------------------------------------
    def post(self, message: AgentMessage) -> None:
        self.messages.append(message)

    def submit(self, position: Position) -> None:
        """Record a position and log any belief change against the author's last one."""
        previous = self.latest_position(position.author)
        if previous and previous.fingerprint != position.fingerprint:
            position.changed_from_previous = True
            self.belief_changes.append(
                {
                    "author": position.author,
                    "round": position.round_index,
                    "from": previous.summary[:200],
                    "to": position.summary[:200],
                    "reason": position.change_reason or "unstated",
                }
            )
        self.positions.append(position)
        for claim in position.claims:
            self.claims[claim.id] = claim

    def silence(self, author: str) -> None:
        """Eject an agent from the live discussion without rewriting history."""
        self.silenced.add(author)

    def add_crux(self, crux: Crux) -> None:
        self.cruxes.append(crux)

    def resolve_crux(self, crux_id: str, resolution: str) -> None:
        for crux in self.cruxes:
            if crux.id == crux_id:
                crux.resolved = True
                crux.resolution = resolution
                return

    # --- reads ------------------------------------------------------------
    def latest_position(self, author: str) -> Position | None:
        for position in reversed(self.positions):
            if position.author == author:
                return position
        return None

    def positions_in_round(self, round_index: int) -> list[Position]:
        return [p for p in self.positions if p.round_index == round_index]

    def current_positions(self) -> list[Position]:
        """One position per author still in the discussion: their most recent."""
        latest: dict[str, Position] = {}
        for position in self.positions:
            if position.author in self.silenced:
                continue
            latest[position.author] = position
        return list(latest.values())

    def open_cruxes(self) -> list[Crux]:
        return [c for c in self.cruxes if not c.resolved]

    def unverified_claims(self) -> list[Claim]:
        return [
            c
            for c in self.claims.values()
            if c.checkable and c.verified is None and c.author not in self.silenced
        ]

    def failed_claims(self) -> list[Claim]:
        return [
            c
            for c in self.claims.values()
            if c.verified is False and c.author not in self.silenced
        ]

    def authors(self) -> list[str]:
        return sorted({p.author for p in self.positions})

    def claim_repetition(self) -> dict[str, int]:
        """How often each distinct claim has been restated. High counts signal an
        oscillating debate that is generating volume rather than progress."""
        counts: dict[str, int] = defaultdict(int)
        for claim in self.claims.values():
            counts[claim.fingerprint] += 1
        return dict(counts)

    def transcript(self, *, anonymized: bool = False) -> str:
        """Render positions for agent consumption.

        Anonymized by default during cross-examination: stripping author identity
        removes the authority cue that drives jurors to herd toward whoever sounds
        most confident rather than whoever is right.
        """
        chunks = []
        for index, position in enumerate(self.current_positions(), start=1):
            label = f"Position {index}" if anonymized else position.author
            body = [f"[{label}] (confidence {position.confidence:.2f})", position.summary]
            for claim in position.claims:
                body.append(f"  claim: {claim.text}")
            if position.strongest_counterargument:
                body.append(f"  concedes: {position.strongest_counterargument}")
            chunks.append("\n".join(body))
        return "\n\n".join(chunks)
