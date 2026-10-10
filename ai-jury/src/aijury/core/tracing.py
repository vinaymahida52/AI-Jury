"""Structured tracing.

Every agent turn, tool call and state transition becomes a span. This is not
observability polish — the Phase 6 learning loop reads these traces to work out
which agent introduced an error and which round it survived.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from collections.abc import Callable
from typing import Any, Iterator


@dataclass
class Span:
    span_id: str
    parent_id: str | None
    name: str
    kind: str
    started_at: str
    duration_ms: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Tracer:
    """In-memory span collector with optional JSONL export.

    Deliberately not tied to a vendor. Swap `export` for an OTLP exporter and the
    rest of the system is unchanged.
    """

    def __init__(self, trace_id: str | None = None, *, trace_dir: str | None = None) -> None:
        self.trace_id = trace_id or uuid.uuid4().hex
        self.spans: list[Span] = []
        self._stack: list[str] = []
        self._trace_dir = trace_dir
        self._listeners: list[Callable[[Span], None]] = []

    def subscribe(self, listener: Callable[[Span], None]) -> Callable[[], None]:
        """Register a live span listener. Returns an unsubscribe callable.

        Lets the API stream a deliberation as it happens instead of waiting for it
        to finish. A listener that raises is dropped rather than allowed to break
        the deliberation — observability must never take down the thing it observes.
        """
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def _emit(self, span: Span) -> None:
        for listener in list(self._listeners):
            try:
                listener(span)
            except Exception:  # noqa: BLE001 - see subscribe()
                self._listeners.remove(listener)

    @contextmanager
    def span(self, name: str, kind: str = "internal", **attributes: Any) -> Iterator[Span]:
        current = Span(
            span_id=uuid.uuid4().hex[:12],
            parent_id=self._stack[-1] if self._stack else None,
            name=name,
            kind=kind,
            started_at=datetime.now(UTC).isoformat(),
            attributes=dict(attributes),
        )
        self.spans.append(current)
        self._stack.append(current.span_id)
        start = time.perf_counter()
        try:
            yield current
        except Exception as exc:
            current.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            current.duration_ms = (time.perf_counter() - start) * 1000
            self._stack.pop()
            self._emit(current)

    def announce(self, name: str, **attributes: Any) -> None:
        """Ping live listeners without writing a span to the trace.

        Used so the console can show who is thinking *during* a long model
        call. The learning loop must not see these — they are not completed work.
        """
        ping = Span(
            span_id=uuid.uuid4().hex[:12],
            parent_id=self._stack[-1] if self._stack else None,
            name=name,
            kind="live",
            started_at=datetime.now(UTC).isoformat(),
            attributes=dict(attributes),
        )
        self._emit(ping)

    def event(self, name: str, **attributes: Any) -> None:
        span = Span(
            span_id=uuid.uuid4().hex[:12],
            parent_id=self._stack[-1] if self._stack else None,
            name=name,
            kind="event",
            started_at=datetime.now(UTC).isoformat(),
            attributes=dict(attributes),
        )
        self.spans.append(span)
        self._emit(span)

    def export(self) -> str | None:
        """Write the trace to disk. Returns the path, or None if tracing to memory only."""
        if not self._trace_dir:
            return None
        os.makedirs(self._trace_dir, exist_ok=True)
        path = os.path.join(self._trace_dir, f"{self.trace_id}.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            for span in self.spans:
                handle.write(json.dumps({"trace_id": self.trace_id, **asdict(span)}) + "\n")
        return path

    def to_dict(self) -> dict[str, Any]:
        return {"trace_id": self.trace_id, "spans": [asdict(s) for s in self.spans]}
