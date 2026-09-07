"""Boundary helpers that close the learning loop around a deliberation."""

from __future__ import annotations

from dataclasses import dataclass

from aijury.config import Settings
from aijury.learning.repository import get_repository
from aijury.protocol.deliberation import DeliberationResult
from aijury.security.injection import sanitize_untrusted


@dataclass(frozen=True)
class DeliberationContext:
    lessons: list[str]
    prior_knowledge: list[str]
    thread_id: str | None = None


def build_deliberation_context(
    settings: Settings,
    question: str,
    *,
    use_lessons: bool = True,
    thread_id: str | None = None,
) -> DeliberationContext:
    """Load active lessons, similar past cases, and this thread's history."""
    if not use_lessons and not thread_id:
        return DeliberationContext(lessons=[], prior_knowledge=[], thread_id=thread_id)
    repo = get_repository(settings)
    lessons = repo.active_lesson_instructions() if use_lessons else []
    knowledge: list[str] = []
    if use_lessons:
        priors = repo.similar_cases(question, limit=settings.prior_case_limit)
        knowledge.extend(
            sanitize_untrusted(prior.as_knowledge_line(), source="prior_case")
            for prior in priors
        )
    if thread_id:
        history = repo.thread_history_lines(thread_id)
        if history:
            knowledge.append(
                sanitize_untrusted(
                    "Earlier turns in this conversation:\n" + "\n".join(history),
                    source="thread_history",
                )
            )
    return DeliberationContext(
        lessons=lessons, prior_knowledge=knowledge, thread_id=thread_id
    )


def ensure_thread(settings: Settings, *, thread_id: str | None, question: str) -> str:
    """Return an existing thread id or create one titled from the question."""
    repo = get_repository(settings)
    if thread_id:
        if repo.get_thread(thread_id) is None:
            raise KeyError(f"unknown thread: {thread_id}")
        return thread_id
    return repo.create_thread(title=question).id


def record_turn(
    settings: Settings,
    *,
    thread_id: str,
    question: str,
    answer: str,
    case_id: str | None,
) -> None:
    """Append user + assistant messages for a finished turn."""
    repo = get_repository(settings)
    repo.append_message(thread_id, role="user", content=question)
    repo.append_message(
        thread_id, role="assistant", content=answer, case_id=case_id or ""
    )


def persist_deliberation(
    settings: Settings, result: DeliberationResult
) -> str | None:
    """Archive a finished deliberation. Never raises into the caller path."""
    try:
        repo = get_repository(settings)
        return repo.persist_case(
            result, provider=settings.provider, model=settings.model
        )
    except Exception:  # noqa: BLE001 - persistence must not take down deliberation
        return None
