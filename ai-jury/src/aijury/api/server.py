"""HTTP API and static UI host.

Two endpoints matter:

  POST /api/ask     run a deliberation, return the full record
  GET  /api/stream  the same, as Server-Sent Events, so the operator watches the
                    panel argue instead of staring at a spinner for 30 seconds

SSE rather than WebSockets: the stream is one-directional and short-lived, so
duplex framing buys nothing and costs reconnect logic.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from aijury import __version__
from aijury.api.schemas import (
    AskRequest,
    ClaimView,
    CruxView,
    DeliberationView,
    FeedbackRequest,
    FeedbackResponse,
    GatewayWrite,
    HealthResponse,
    PositionView,
    ThreadDetailView,
    ThreadMessageView,
    ThreadSummaryView,
)
from aijury.config import Budget, Settings
from aijury.core.errors import UnsafeInputError
from aijury.core.tracing import Span
from aijury.security.casual import casual_reply
from aijury.learning.injector import load_lessons
from aijury.learning.lesson_extractor import extract_lessons
from aijury.learning.loop import (
    build_deliberation_context,
    ensure_thread,
    persist_deliberation,
    record_turn,
)
from aijury.learning.repository import get_repository
from aijury.llm.gateways import (
    GatewayBook,
    apply_gateway,
    apply_mock,
    list_remote_models,
)
from aijury.protocol.deliberation import Deliberation, DeliberationResult

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

#: Spans that mean something to a human watching. Everything else is noise at
#: this level and stays in the trace file for post-hoc debugging.
_STREAMED = {
    "frame.complete",
    "jury.spawned",
    "round.complete",
    "moderator.cruxes",
    "verification.complete",
    "juror.failed",
    "agent.failed",
    "verdict.finalized",
    "phase.round",
}


def _settings_for(request: AskRequest, base: Settings) -> Settings:
    budget = base.budget
    if request.max_rounds is not None or request.max_jurors is not None:
        budget = replace(
            budget,
            max_rounds=request.max_rounds or budget.max_rounds,
            max_jurors=request.max_jurors or budget.max_jurors,
        )
    return replace(base, budget=budget)


def _to_view(
    result: DeliberationResult,
    *,
    case_id: str | None = None,
    thread_id: str | None = None,
) -> DeliberationView:
    board = result.blackboard
    checkable = [c for c in board.claims.values() if c.checkable]
    verified = [c for c in checkable if c.verified is True]

    return DeliberationView(
        verdict=result.verdict,
        question_type=board.frame.question_type.value if board.frame else "unknown",
        stop_reason=result.stop_reason.value,
        agreement=round(result.agreement, 3),
        positions=[
            PositionView(
                author=p.author,
                round_index=p.round_index,
                summary=p.summary,
                confidence=p.confidence,
                changed=p.changed_from_previous,
                change_reason=p.change_reason,
                concedes=p.strongest_counterargument,
                claims=[
                    ClaimView(
                        text=c.text,
                        author=c.author,
                        round_index=c.round_index,
                        verified=c.verified,
                        note=c.verification_note,
                    )
                    for c in p.claims
                ],
            )
            for p in board.positions
        ],
        cruxes=[
            CruxView(
                description=c.description,
                resolvable_by=c.resolvable_by,
                resolved=c.resolved,
                resolution=c.resolution,
            )
            for c in board.cruxes
        ],
        belief_changes=board.belief_changes,
        verified_ratio=round(len(verified) / len(checkable), 3) if checkable else 0.0,
        verified_claims=len(verified),
        checkable_claims=len(checkable),
        degraded=result.degraded,
        budget=result.ledger.snapshot(),
        case_id=case_id,
        thread_id=thread_id,
    )


class _Runtime:
    """Mutable seated gateway. The console switches brains without a restart."""

    def __init__(self, settings: Settings, book: GatewayBook) -> None:
        self.settings = settings
        self.book = book

    def seat(self, gateway_id: str) -> Settings:
        self.book.seat(gateway_id)
        if gateway_id == "mock":
            self.settings = apply_mock(self.settings)
        else:
            self.settings = apply_gateway(self.settings, self.book.get(gateway_id))
        return self.settings


def create_app(settings: Settings | None = None) -> FastAPI:
    base_settings = settings or Settings.from_env()
    book = GatewayBook(base_settings.gateways_path)
    book.hydrate_from_settings(base_settings)
    if book.active != "mock" and book.active in book.gateways:
        base_settings = apply_gateway(base_settings, book.get(book.active))
    runtime = _Runtime(base_settings, book)
    app = FastAPI(title="AI Jury", version=__version__)

    # Local operator tool. Lock this down before exposing it beyond localhost.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        current = runtime.settings
        return HealthResponse(
            status="ok",
            version=__version__,
            provider=current.provider,
            model=current.model,
            max_rounds=current.budget.max_rounds,
            max_jurors=current.budget.max_jurors,
            lessons_active=len(load_lessons(current)),
        )

    @app.get("/api/gateways")
    async def list_gateways() -> dict[str, Any]:
        body = runtime.book.catalog()
        body["active"] = runtime.book.active
        body["provider"] = runtime.settings.provider
        body["model"] = runtime.settings.model
        return body

    @app.put("/api/gateways")
    async def save_gateway(request: GatewayWrite) -> dict[str, Any]:
        try:
            gw = runtime.book.upsert(
                label=request.label,
                base_url=request.base_url,
                model=request.model,
                model_pool=request.model_pool,
                api_key=request.api_key,
                gateway_id=request.id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if request.seat:
            runtime.seat(gw.id)
        return {"gateway": gw.public(), "active": runtime.book.active}

    @app.post("/api/gateways/{gateway_id}/seat")
    async def seat_gateway(gateway_id: str) -> dict[str, Any]:
        try:
            runtime.seat(gateway_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="unknown gateway") from None
        return {
            "active": runtime.book.active,
            "provider": runtime.settings.provider,
            "model": runtime.settings.model,
        }

    @app.post("/api/gateways/{gateway_id}/probe")
    async def probe_gateway(gateway_id: str) -> dict[str, Any]:
        try:
            gw = runtime.book.get(gateway_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="unknown gateway") from None
        if not gw.api_key:
            raise HTTPException(status_code=400, detail="save an API key before probing")
        try:
            models = await asyncio.to_thread(list_remote_models, gw.base_url, gw.api_key)
        except Exception as exc:  # noqa: BLE001 - surface the gateway's error
            raise HTTPException(status_code=502, detail=str(exc)[:400]) from exc
        return {"models": models}

    @app.delete("/api/gateways/{gateway_id}")
    async def delete_gateway(gateway_id: str) -> dict[str, Any]:
        was_active = runtime.book.active == gateway_id
        runtime.book.drop(gateway_id)
        if was_active:
            runtime.seat("mock")
        return {"active": runtime.book.active}

    @app.post("/api/ask", response_model=DeliberationView)
    async def ask(request: AskRequest) -> DeliberationView:
        try:
            thread_id = ensure_thread(
                runtime.settings, thread_id=request.thread_id, question=request.question
            )
            settings = _settings_for(request, runtime.settings)
            ctx = build_deliberation_context(
                runtime.settings,
                request.question,
                use_lessons=request.use_lessons,
                thread_id=thread_id,
            )
            result = await Deliberation(
                settings,
                lessons=ctx.lessons,
                prior_knowledge=ctx.prior_knowledge,
            ).run(request.question)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except UnsafeInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        case_id = persist_deliberation(runtime.settings, result)
        try:
            record_turn(
                runtime.settings,
                thread_id=thread_id,
                question=request.question,
                answer=result.verdict.answer,
                case_id=case_id,
            )
        except Exception:  # noqa: BLE001 - chat history must not break the verdict
            pass
        return _to_view(result, case_id=case_id, thread_id=thread_id)

    @app.get("/api/threads", response_model=list[ThreadSummaryView])
    async def list_threads() -> list[ThreadSummaryView]:
        repo = get_repository(runtime.settings)
        return [
            ThreadSummaryView(
                id=t.id, title=t.title, updated_at=t.updated_at, preview=t.preview
            )
            for t in repo.list_threads()
        ]

    @app.get("/api/threads/{thread_id}", response_model=ThreadDetailView)
    async def get_thread(thread_id: str) -> ThreadDetailView:
        detail = get_repository(runtime.settings).get_thread(thread_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown thread")
        return ThreadDetailView(
            id=detail.id,
            title=detail.title,
            created_at=detail.created_at,
            updated_at=detail.updated_at,
            messages=[
                ThreadMessageView(
                    id=m.id,
                    role=m.role,
                    content=m.content,
                    case_id=m.case_id,
                    created_at=m.created_at,
                )
                for m in detail.messages
            ],
        )

    @app.post("/api/threads")
    async def new_thread() -> ThreadSummaryView:
        thread = get_repository(runtime.settings).create_thread(title="New chat")
        return ThreadSummaryView(
            id=thread.id, title=thread.title, updated_at=thread.updated_at, preview=""
        )

    @app.post("/api/cases/{case_id}/feedback", response_model=FeedbackResponse)
    async def case_feedback(case_id: str, request: FeedbackRequest) -> FeedbackResponse:
        repo = get_repository(runtime.settings)
        record = repo.record_feedback(
            case_id, expected=request.expected, signal=request.signal
        )
        if record is None:
            raise HTTPException(status_code=404, detail="unknown case")
        lessons = extract_lessons(repo.all_failures())
        promoted = 0
        if lessons:
            repo.save_lessons(lessons)
            promoted = len(lessons)
        return FeedbackResponse(
            failure_id=record.id, case_id=case_id, lessons_promoted=promoted
        )

    @app.get("/api/stream")
    async def stream(
        question: str = Query(min_length=1, max_length=20_000),
        max_rounds: int | None = Query(default=None, ge=1, le=100),
        max_jurors: int | None = Query(default=None, ge=1, le=100),
        thread_id: str | None = Query(default=None, max_length=64),
    ) -> StreamingResponse:
        request = AskRequest(
            question=question,
            max_rounds=max_rounds,
            max_jurors=max_jurors,
            thread_id=thread_id,
        )
        return StreamingResponse(
            _run_streaming(request, runtime.settings),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    return app


def _sse(event: str, payload: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


async def _run_streaming(request: AskRequest, base: Settings) -> AsyncIterator[str]:
    """Bridge tracer spans into an SSE stream.

    The tracer calls listeners synchronously from inside the deliberation, so
    spans land on a queue and are drained here rather than awaited in place —
    otherwise a slow client would throttle the panel.
    """
    try:
        thread_id = ensure_thread(base, thread_id=request.thread_id, question=request.question)
    except KeyError as exc:
        yield _sse("error", {"detail": str(exc), "kind": "unknown_thread"})
        yield _sse("done", {})
        return

    yield _sse("session", {"question": request.question, "thread_id": thread_id})
    greeting = casual_reply(request.question)
    if greeting is not None:
        try:
            record_turn(
                base,
                thread_id=thread_id,
                question=request.question,
                answer=greeting,
                case_id=None,
            )
        except Exception:  # noqa: BLE001
            pass
        yield _sse("chat", {"reply": greeting, "casual": True, "thread_id": thread_id})
        yield _sse("done", {})
        return

    queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_span(span: Span) -> None:
        payload = {
            "name": span.name,
            "kind": span.kind,
            "attributes": span.attributes,
            "duration_ms": round(span.duration_ms, 1),
        }
        if span.kind == "live":
            event = "live"
        elif span.name in _STREAMED or span.name.startswith("agent."):
            event = "span"
        else:
            return
        loop.call_soon_threadsafe(queue.put_nowait, (event, payload))

    ctx = build_deliberation_context(
        base, request.question, use_lessons=True, thread_id=thread_id
    )
    deliberation = Deliberation(
        _settings_for(request, base),
        lessons=ctx.lessons,
        prior_knowledge=ctx.prior_knowledge,
    )

    async def run() -> None:
        try:
            result = await deliberation.run(request.question, on_span=on_span)
            case_id = persist_deliberation(base, result)
            try:
                record_turn(
                    base,
                    thread_id=thread_id,
                    question=request.question,
                    answer=result.verdict.answer,
                    case_id=case_id,
                )
            except Exception:  # noqa: BLE001
                pass
            queue.put_nowait(
                (
                    "verdict",
                    _to_view(result, case_id=case_id, thread_id=thread_id).model_dump(
                        mode="json"
                    ),
                )
            )
        except UnsafeInputError as exc:
            queue.put_nowait(("error", {"detail": str(exc), "kind": "invalid_input"}))
        except Exception as exc:  # noqa: BLE001 - surface it, never hang the client
            queue.put_nowait(("error", {"detail": str(exc), "kind": type(exc).__name__}))
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(run())
    started = time.perf_counter()
    yield _sse(
        "live",
        {
            "name": "chamber",
            "kind": "live",
            "attributes": {"who": "clerk", "action": "convening the panel"},
            "duration_ms": 0,
        },
    )
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                yield _sse(
                    "pulse",
                    {"elapsed_s": round(time.perf_counter() - started, 1)},
                )
                continue
            if item is None:
                break
            event, payload = item
            yield _sse(event, payload)
    finally:
        if not task.done():
            task.cancel()
    yield _sse("done", {})
