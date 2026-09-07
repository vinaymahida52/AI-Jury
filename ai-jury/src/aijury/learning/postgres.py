"""Postgres / Neon backend for the closed learning loop."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aijury.config import Settings
from aijury.learning.failure_store import FailureRecord
from aijury.learning.injector import MAX_INJECTED_LESSONS
from aijury.learning.lesson_extractor import Lesson
from aijury.learning.repository import (
    PriorCase,
    ThreadDetail,
    ThreadMessage,
    ThreadSummary,
    _blackboard_snapshot,
    _score_overlap,
    _title_from_question,
)
from aijury.protocol.deliberation import DeliberationResult

_SCHEMA = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")


class PostgresLearningRepository:
    def __init__(self, settings: Settings) -> None:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - optional extra
            raise RuntimeError(
                "psycopg not installed. Run: pip install 'aijury[db]'"
            ) from exc
        self.settings = settings
        self._psycopg = psycopg
        self._ensured = False

    def _connect(self) -> Any:
        conn = self._psycopg.connect(self.settings.database_url)
        if not self._ensured:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA)
            conn.commit()
            self._ensured = True
        return conn

    def persist_case(
        self, result: DeliberationResult, *, provider: str, model: str
    ) -> str:
        case_id = uuid.uuid4().hex[:16]
        verdict = result.verdict
        board = _blackboard_snapshot(result)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cases (
                        id, trace_id, question, question_type, stop_reason,
                        agreement, degraded, provider, model, blackboard, budget, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb, %s
                    )
                    """,
                    (
                        case_id,
                        verdict.trace_id or result.tracer.trace_id,
                        result.blackboard.question,
                        board["question_type"],
                        result.stop_reason.value,
                        result.agreement,
                        json.dumps(list(result.degraded)),
                        provider,
                        model,
                        json.dumps(board),
                        json.dumps(result.ledger.snapshot()),
                        datetime.now(UTC),
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO verdicts (
                        case_id, outcome, answer, confidence, payload,
                        rounds_used, tokens_used, duration_seconds
                    ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    """,
                    (
                        case_id,
                        verdict.outcome.value,
                        verdict.answer,
                        verdict.confidence,
                        json.dumps(verdict.model_dump(mode="json")),
                        verdict.rounds_used,
                        verdict.tokens_used,
                        verdict.duration_seconds,
                    ),
                )
            conn.commit()
        return case_id

    def get_case(self, case_id: str) -> dict | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.id, c.trace_id, c.question, c.question_type, c.blackboard,
                           v.outcome, v.answer, v.confidence, v.payload
                    FROM cases c
                    JOIN verdicts v ON v.case_id = c.id
                    WHERE c.id = %s
                    """,
                    (case_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "trace_id": row[1],
            "question": row[2],
            "question_type": row[3],
            "blackboard": row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}"),
            "verdict": {
                "outcome": row[5],
                "answer": row[6],
                "confidence": row[7],
                "payload": row[8] if isinstance(row[8], dict) else json.loads(row[8] or "{}"),
            },
        }

    def record_failure(self, record: FailureRecord) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO failures (
                        id, case_id, question, question_type, expected, produced,
                        confidence, outcome, signal, introduced_by, survived_rounds,
                        verification_had_method, open_cruxes, belief_changes,
                        trace_id, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s, %s
                    )
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        record.id,
                        record.case_id or None,
                        record.question,
                        record.question_type,
                        record.expected,
                        record.produced,
                        record.confidence,
                        record.outcome,
                        record.signal,
                        record.introduced_by,
                        record.survived_rounds,
                        record.verification_had_method,
                        json.dumps(record.open_cruxes),
                        json.dumps(record.belief_changes),
                        record.trace_id,
                        record.created_at,
                    ),
                )
            conn.commit()

    def all_failures(self) -> list[FailureRecord]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, case_id, question, question_type, expected, produced,
                           confidence, outcome, signal, introduced_by, survived_rounds,
                           verification_had_method, open_cruxes, belief_changes,
                           trace_id, created_at
                    FROM failures
                    ORDER BY created_at ASC
                    """
                )
                rows = cur.fetchall()
        records: list[FailureRecord] = []
        for row in rows:
            open_cruxes = row[12] if isinstance(row[12], list) else json.loads(row[12] or "[]")
            belief_changes = row[13] if isinstance(row[13], list) else json.loads(row[13] or "[]")
            created = row[15]
            records.append(
                FailureRecord(
                    id=row[0],
                    case_id=row[1] or "",
                    question=row[2],
                    question_type=row[3],
                    expected=row[4],
                    produced=row[5],
                    confidence=float(row[6]),
                    outcome=row[7],
                    signal=row[8],
                    introduced_by=row[9],
                    survived_rounds=int(row[10]),
                    verification_had_method=bool(row[11]),
                    open_cruxes=open_cruxes,
                    belief_changes=belief_changes,
                    trace_id=row[14] or "",
                    created_at=created.isoformat() if hasattr(created, "isoformat") else str(created),
                )
            )
        return records

    def save_lessons(self, lessons: list[Lesson]) -> str:
        with self._connect() as conn:
            with conn.cursor() as cur:
                for lesson in lessons:
                    cur.execute(
                        """
                        INSERT INTO lessons (
                            id, pattern, instruction, applies_to, occurrences,
                            example_failure_ids, active, created_at
                        ) VALUES (
                            %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            pattern = EXCLUDED.pattern,
                            instruction = EXCLUDED.instruction,
                            applies_to = EXCLUDED.applies_to,
                            occurrences = EXCLUDED.occurrences,
                            example_failure_ids = EXCLUDED.example_failure_ids,
                            active = EXCLUDED.active
                        """,
                        (
                            lesson.id,
                            lesson.pattern,
                            lesson.instruction,
                            json.dumps(lesson.applies_to),
                            lesson.occurrences,
                            json.dumps(lesson.example_failure_ids),
                            lesson.active,
                            lesson.created_at,
                        ),
                    )
            conn.commit()
        return f"postgres:lessons:{len(lessons)}"

    def active_lesson_instructions(self, *, agent: str | None = None) -> list[str]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT instruction, applies_to, occurrences
                    FROM lessons
                    WHERE active = TRUE
                    ORDER BY occurrences DESC
                    """
                )
                rows = cur.fetchall()
        selected: list[tuple[int, str]] = []
        for instruction, applies_to, occurrences in rows:
            applies = applies_to if isinstance(applies_to, list) else json.loads(applies_to or "[]")
            if agent is None or not applies or agent in applies:
                selected.append((int(occurrences), instruction))
        return [text for _, text in selected[:MAX_INJECTED_LESSONS]]

    def similar_cases(self, question: str, *, limit: int = 3) -> list[PriorCase]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.id, c.question, v.answer, v.outcome, v.confidence, v.payload
                    FROM cases c
                    JOIN verdicts v ON v.case_id = c.id
                    ORDER BY c.created_at DESC
                    LIMIT 200
                    """
                )
                rows = cur.fetchall()
        ranked: list[tuple[float, Any]] = []
        for row in rows:
            score = _score_overlap(question, row[1])
            if score > 0:
                ranked.append((score, row))
        ranked.sort(key=lambda item: -item[0])
        priors: list[PriorCase] = []
        for _, row in ranked[:limit]:
            payload = row[5] if isinstance(row[5], dict) else json.loads(row[5] or "{}")
            conclusions = [
                c.get("statement", "")
                for c in payload.get("conclusions", [])
                if c.get("verified")
            ]
            priors.append(
                PriorCase(
                    case_id=row[0],
                    question=row[1],
                    answer=row[2],
                    outcome=row[3],
                    confidence=float(row[4]),
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
            belief_changes=list((row.get("blackboard") or {}).get("belief_changes") or []),
        )
        self.record_failure(record)
        return record

    def create_thread(self, *, title: str) -> ThreadSummary:
        thread_id = uuid.uuid4().hex[:16]
        now = datetime.now(UTC)
        clean = _title_from_question(title)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO threads (id, title, created_at, updated_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (thread_id, clean, now, now),
                )
            conn.commit()
        return ThreadSummary(
            id=thread_id, title=clean, updated_at=now.isoformat(), preview=""
        )

    def list_threads(self, *, limit: int = 50) -> list[ThreadSummary]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.id, t.title, t.updated_at,
                           (
                             SELECT m.content FROM thread_messages m
                             WHERE m.thread_id = t.id
                             ORDER BY m.created_at DESC LIMIT 1
                           ) AS preview
                    FROM threads t
                    ORDER BY t.updated_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        out: list[ThreadSummary] = []
        for row in rows:
            updated = row[2]
            out.append(
                ThreadSummary(
                    id=row[0],
                    title=row[1],
                    updated_at=updated.isoformat() if hasattr(updated, "isoformat") else str(updated),
                    preview=(row[3] or "")[:120],
                )
            )
        return out

    def get_thread(self, thread_id: str) -> ThreadDetail | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, title, created_at, updated_at FROM threads WHERE id = %s",
                    (thread_id,),
                )
                thread = cur.fetchone()
                if thread is None:
                    return None
                cur.execute(
                    """
                    SELECT id, thread_id, role, content, case_id, created_at
                    FROM thread_messages
                    WHERE thread_id = %s
                    ORDER BY created_at ASC
                    """,
                    (thread_id,),
                )
                msgs = cur.fetchall()
        messages = tuple(
            ThreadMessage(
                id=m[0],
                thread_id=m[1],
                role=m[2],
                content=m[3],
                case_id=m[4] or "",
                created_at=m[5].isoformat() if hasattr(m[5], "isoformat") else str(m[5]),
            )
            for m in msgs
        )
        return ThreadDetail(
            id=thread[0],
            title=thread[1],
            created_at=thread[2].isoformat() if hasattr(thread[2], "isoformat") else str(thread[2]),
            updated_at=thread[3].isoformat() if hasattr(thread[3], "isoformat") else str(thread[3]),
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
        msg_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM threads WHERE id = %s", (thread_id,))
                if cur.fetchone() is None:
                    raise KeyError(f"unknown thread: {thread_id}")
                cur.execute(
                    """
                    INSERT INTO thread_messages (id, thread_id, role, content, case_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (msg_id, thread_id, role, content, case_id or None, now),
                )
                cur.execute(
                    "UPDATE threads SET updated_at = %s WHERE id = %s",
                    (now, thread_id),
                )
            conn.commit()
        return ThreadMessage(
            id=msg_id,
            thread_id=thread_id,
            role=role,
            content=content,
            case_id=case_id,
            created_at=now.isoformat(),
        )

    def thread_history_lines(self, thread_id: str) -> list[str]:
        detail = self.get_thread(thread_id)
        if detail is None:
            return []
        lines: list[str] = []
        for msg in detail.messages:
            who = "User" if msg.role == "user" else "Jury"
            lines.append(f"{who}: {msg.content[:800]}")
        return lines
