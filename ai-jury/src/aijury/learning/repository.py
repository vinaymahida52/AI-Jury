"""Learning repository: cases, failures, lessons, similar-case priors.

File backend keeps tests and offline mock mode working. Postgres backend uses
Neon when Settings.database_url is set.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from aijury.config import Settings
from aijury.learning.failure_store import FailureRecord
from aijury.learning.injector import MAX_INJECTED_LESSONS
from aijury.learning.lesson_extractor import Lesson
from aijury.protocol.deliberation import DeliberationResult

_TOKEN = re.compile(r"[a-z0-9]+", re.I)


@dataclass(frozen=True)
class PriorCase:
    """A past deliberation summary safe to inject as reference data."""

    case_id: str
    question: str
    answer: str
    outcome: str
    confidence: float
    verified_conclusions: tuple[str, ...] = ()

    def as_knowledge_line(self) -> str:
        verified = "; ".join(self.verified_conclusions[:3])
        tail = f" Verified: {verified}." if verified else ""
        return (
            f"Prior case ({self.outcome}, confidence {self.confidence:.2f}): "
            f"Q: {self.question[:200]} → A: {self.answer[:300]}.{tail}"
        )


@dataclass(frozen=True)
class ThreadSummary:
    id: str
    title: str
    updated_at: str
    preview: str = ""


@dataclass(frozen=True)
class ThreadMessage:
    id: str
    thread_id: str
    role: str
    content: str
    case_id: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class ThreadDetail:
    id: str
    title: str
    created_at: str
    updated_at: str
    messages: tuple[ThreadMessage, ...] = ()


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text) if len(t) > 2}


def _score_overlap(query: str, candidate: str) -> float:
    q, c = _tokens(query), _tokens(candidate)
    if not q or not c:
        return 0.0
    return len(q & c) / len(q)


def _blackboard_snapshot(result: DeliberationResult) -> dict:
    board = result.blackboard
    return {
        "question": board.question,
        "question_type": board.frame.question_type.value if board.frame else "unknown",
        "positions": [
            {
                "author": p.author,
                "round_index": p.round_index,
                "summary": p.summary,
                "confidence": p.confidence,
                "changed": p.changed_from_previous,
                "change_reason": p.change_reason,
            }
            for p in board.positions
        ],
        "claims": [
            {
                "id": c.id,
                "text": c.text,
                "author": c.author,
                "round_index": c.round_index,
                "verified": c.verified,
                "checkable": c.checkable,
                "note": c.verification_note,
            }
            for c in board.claims.values()
        ],
        "cruxes": [
            {
                "id": c.id,
                "description": c.description,
                "resolvable_by": c.resolvable_by,
                "resolved": c.resolved,
                "resolution": c.resolution,
            }
            for c in board.cruxes
        ],
        "belief_changes": board.belief_changes,
    }


class LearningRepository(Protocol):
    def persist_case(
        self, result: DeliberationResult, *, provider: str, model: str
    ) -> str: ...

    def get_case(self, case_id: str) -> dict | None: ...

    def record_failure(self, record: FailureRecord) -> None: ...

    def all_failures(self) -> list[FailureRecord]: ...

    def save_lessons(self, lessons: list[Lesson]) -> str: ...

    def active_lesson_instructions(self, *, agent: str | None = None) -> list[str]: ...

    def similar_cases(self, question: str, *, limit: int = 3) -> list[PriorCase]: ...

    def record_feedback(
        self, case_id: str, *, expected: str, signal: str = "production_feedback"
    ) -> FailureRecord | None: ...

    def create_thread(self, *, title: str) -> ThreadSummary: ...

    def list_threads(self, *, limit: int = 50) -> list[ThreadSummary]: ...

    def get_thread(self, thread_id: str) -> ThreadDetail | None: ...

    def append_message(
        self,
        thread_id: str,
        *,
        role: str,
        content: str,
        case_id: str = "",
    ) -> ThreadMessage: ...

    def thread_history_lines(self, thread_id: str) -> list[str]: ...


def _title_from_question(question: str) -> str:
    cleaned = " ".join(question.strip().split())
    if len(cleaned) <= 72:
        return cleaned or "New chat"
    return cleaned[:69].rstrip() + "…"


@dataclass
class FileLearningRepository:
    """JSONL/JSON store under settings.failure_dir — the offline default."""

    settings: Settings
    _cases: list[dict] = field(default_factory=list, init=False)
    _loaded: bool = field(default=False, init=False)
    _threads: dict[str, dict] = field(default_factory=dict, init=False)
    _messages: list[dict] = field(default_factory=list, init=False)
    _threads_loaded: bool = field(default=False, init=False)

    def _root(self) -> str:
        os.makedirs(self.settings.failure_dir, exist_ok=True)
        return self.settings.failure_dir

    def _cases_path(self) -> str:
        return os.path.join(self._root(), "cases.jsonl")

    def _failures_path(self) -> str:
        return os.path.join(self._root(), "failures.jsonl")

    def _lessons_path(self) -> str:
        return os.path.join(self._root(), "lessons.json")

    def _threads_path(self) -> str:
        return os.path.join(self._root(), "threads.jsonl")

    def _messages_path(self) -> str:
        return os.path.join(self._root(), "thread_messages.jsonl")

    def _ensure_cases(self) -> None:
        if self._loaded:
            return
        path = self._cases_path()
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        self._cases.append(json.loads(line))
        self._loaded = True

    def _ensure_threads(self) -> None:
        if self._threads_loaded:
            return
        if os.path.exists(self._threads_path()):
            with open(self._threads_path(), encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        row = json.loads(line)
                        self._threads[row["id"]] = row
        if os.path.exists(self._messages_path()):
            with open(self._messages_path(), encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        self._messages.append(json.loads(line))
        self._threads_loaded = True

    def persist_case(
        self, result: DeliberationResult, *, provider: str, model: str
    ) -> str:
        self._ensure_cases()
        case_id = uuid.uuid4().hex[:16]
        verdict = result.verdict
        row = {
            "id": case_id,
            "trace_id": verdict.trace_id or result.tracer.trace_id,
            "question": result.blackboard.question,
            "question_type": (
                result.blackboard.frame.question_type.value
                if result.blackboard.frame
                else verdict.question_type.value
            ),
            "stop_reason": result.stop_reason.value,
            "agreement": result.agreement,
            "degraded": list(result.degraded),
            "provider": provider,
            "model": model,
            "blackboard": _blackboard_snapshot(result),
            "budget": result.ledger.snapshot(),
            "created_at": datetime.now(UTC).isoformat(),
            "verdict": {
                "outcome": verdict.outcome.value,
                "answer": verdict.answer,
                "confidence": verdict.confidence,
                "payload": verdict.model_dump(mode="json"),
                "rounds_used": verdict.rounds_used,
                "tokens_used": verdict.tokens_used,
                "duration_seconds": verdict.duration_seconds,
            },
        }
        self._cases.append(row)
        with open(self._cases_path(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        return case_id

    def get_case(self, case_id: str) -> dict | None:
        self._ensure_cases()
        for row in self._cases:
            if row["id"] == case_id:
                return row
        return None

    def record_failure(self, record: FailureRecord) -> None:
        with open(self._failures_path(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record)) + "\n")

    def all_failures(self) -> list[FailureRecord]:
        path = self._failures_path()
        if not os.path.exists(path):
            return []
        records: list[FailureRecord] = []
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    records.append(FailureRecord(**json.loads(line)))
        return records

    def save_lessons(self, lessons: list[Lesson]) -> str:
        path = self._lessons_path()
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([asdict(lesson) for lesson in lessons], handle, indent=2)
        return path

    def active_lesson_instructions(self, *, agent: str | None = None) -> list[str]:
        path = self._lessons_path()
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        lessons = [Lesson(**item) for item in raw]
        selected = [
            lesson
            for lesson in lessons
            if lesson.active and (agent is None or not lesson.applies_to or agent in lesson.applies_to)
        ]
        selected.sort(key=lambda lesson: -lesson.occurrences)
        return [lesson.instruction for lesson in selected[:MAX_INJECTED_LESSONS]]

    def similar_cases(self, question: str, *, limit: int = 3) -> list[PriorCase]:
        self._ensure_cases()
        ranked: list[tuple[float, dict]] = []
        for row in self._cases:
            score = _score_overlap(question, row["question"])
            if score <= 0:
                continue
            ranked.append((score, row))
        ranked.sort(key=lambda item: -item[0])
        priors: list[PriorCase] = []
        for _, row in ranked[:limit]:
            verdict = row.get("verdict") or {}
            payload = verdict.get("payload") or {}
            conclusions = [
                c.get("statement", "")
                for c in payload.get("conclusions", [])
                if c.get("verified")
            ]
            priors.append(
                PriorCase(
                    case_id=row["id"],
                    question=row["question"],
                    answer=verdict.get("answer", ""),
                    outcome=verdict.get("outcome", ""),
                    confidence=float(verdict.get("confidence") or 0),
                    verified_conclusions=tuple(c for c in conclusions if c),
                )
            )
        return priors

    def record_feedback(
        self, case_id: str, *, expected: str, signal: str = "production_feedback"
    ) -> FailureRecord | None:
        row = self.get_case(case_id)
        if row is None:
            return None
        verdict = row.get("verdict") or {}
        record = FailureRecord(
            id=uuid.uuid4().hex[:12],
            question=row["question"],
            question_type=row.get("question_type", "unknown"),
            expected=expected,
            produced=verdict.get("answer", ""),
            confidence=float(verdict.get("confidence") or 0),
            outcome=verdict.get("outcome", ""),
            signal=signal,
            trace_id=row.get("trace_id", ""),
            case_id=case_id,
            open_cruxes=[],
            belief_changes=list((row.get("blackboard") or {}).get("belief_changes") or []),
        )
        self.record_failure(record)
        return record

    def create_thread(self, *, title: str) -> ThreadSummary:
        self._ensure_threads()
        now = datetime.now(UTC).isoformat()
        thread_id = uuid.uuid4().hex[:16]
        row = {
            "id": thread_id,
            "title": _title_from_question(title),
            "created_at": now,
            "updated_at": now,
        }
        self._threads[thread_id] = row
        with open(self._threads_path(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        return ThreadSummary(id=thread_id, title=row["title"], updated_at=now, preview="")

    def list_threads(self, *, limit: int = 50) -> list[ThreadSummary]:
        self._ensure_threads()
        rows = sorted(self._threads.values(), key=lambda r: r.get("updated_at", ""), reverse=True)
        out: list[ThreadSummary] = []
        for row in rows[:limit]:
            msgs = [m for m in self._messages if m["thread_id"] == row["id"]]
            preview = ""
            if msgs:
                preview = msgs[-1].get("content", "")[:120]
            out.append(
                ThreadSummary(
                    id=row["id"],
                    title=row.get("title", "Chat"),
                    updated_at=row.get("updated_at", ""),
                    preview=preview,
                )
            )
        return out

    def get_thread(self, thread_id: str) -> ThreadDetail | None:
        self._ensure_threads()
        row = self._threads.get(thread_id)
        if row is None:
            return None
        messages = tuple(
            ThreadMessage(
                id=m["id"],
                thread_id=m["thread_id"],
                role=m["role"],
                content=m["content"],
                case_id=m.get("case_id") or "",
                created_at=m.get("created_at", ""),
            )
            for m in self._messages
            if m["thread_id"] == thread_id
        )
        return ThreadDetail(
            id=row["id"],
            title=row.get("title", "Chat"),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
            messages=messages,
        )

    def append_message(
        self,
        thread_id: str,
        *,
        role: str,
        content: str,
        case_id: str = "",
    ) -> ThreadMessage:
        self._ensure_threads()
        if thread_id not in self._threads:
            raise KeyError(f"unknown thread: {thread_id}")
        now = datetime.now(UTC).isoformat()
        msg = {
            "id": uuid.uuid4().hex[:12],
            "thread_id": thread_id,
            "role": role,
            "content": content,
            "case_id": case_id,
            "created_at": now,
        }
        self._messages.append(msg)
        with open(self._messages_path(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(msg) + "\n")
        thread = self._threads[thread_id]
        thread["updated_at"] = now
        # Rewrite threads file (small local store).
        with open(self._threads_path(), "w", encoding="utf-8") as handle:
            for row in self._threads.values():
                handle.write(json.dumps(row) + "\n")
        return ThreadMessage(**msg)

    def thread_history_lines(self, thread_id: str) -> list[str]:
        detail = self.get_thread(thread_id)
        if detail is None:
            return []
        lines: list[str] = []
        for msg in detail.messages:
            who = "User" if msg.role == "user" else "Jury"
            lines.append(f"{who}: {msg.content[:800]}")
        return lines


def get_repository(settings: Settings) -> LearningRepository:
    if settings.database_url:
        from aijury.learning.postgres import PostgresLearningRepository

        return PostgresLearningRepository(settings)
    return FileLearningRepository(settings)
