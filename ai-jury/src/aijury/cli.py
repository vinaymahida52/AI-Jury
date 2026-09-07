"""Command line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from aijury.config import Settings
from aijury.evaluation.harness import load_dataset, run_eval
from aijury.learning.failure_store import FailureStore
from aijury.learning.lesson_extractor import extract_lessons, failure_summary, save_lessons
from aijury.pipeline import JuryPipeline


async def _ask(question: str, *, show_trace: bool, as_json: bool) -> int:
    settings = Settings.from_env()
    result = await JuryPipeline(settings).ask(question)

    if as_json:
        print(result.verdict.model_dump_json(indent=2))
    else:
        print(result.verdict.render())

    if result.used_fallback:
        print(f"\n[degraded: fell back to baseline — {result.fallback_reason}]", file=sys.stderr)
    if result.deliberation and result.deliberation.degraded:
        for note in result.deliberation.degraded:
            print(f"[degraded: {note}]", file=sys.stderr)
    if show_trace and result.deliberation:
        print(json.dumps(result.deliberation.tracer.to_dict(), indent=2), file=sys.stderr)
    return 0


async def _eval(dataset: str, concurrency: int) -> int:
    settings = Settings.from_env()
    report = await run_eval(load_dataset(dataset), settings, concurrency=concurrency)
    print(report.render())
    return 0 if report.jury_beats_baseline else 1


def _lessons() -> int:
    settings = Settings.from_env()
    store = FailureStore(settings)
    failures = store.all()
    if not failures:
        print("no failures recorded yet")
        return 0
    lessons = extract_lessons(failures)
    path = save_lessons(lessons, settings)
    print(f"{len(failures)} failures -> {len(lessons)} promoted lessons ({path})")
    for agent, count in sorted(failure_summary(failures).items(), key=lambda kv: -kv[1]):
        print(f"  errors introduced by {agent}: {count}")
    for lesson in lessons:
        print(f"  [{lesson.occurrences}x] {lesson.pattern}: {lesson.instruction}")
    return 0


def _db_migrate() -> int:
    settings = Settings.from_env()
    if not settings.database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    from aijury.learning.postgres import PostgresLearningRepository

    repo = PostgresLearningRepository(settings)
    with repo._connect() as conn:
        pass
    print("learning-loop schema applied")
    return 0


def _serve(host: str, port: int, reload: bool) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "web extras not installed. Run: pip install -e '.[web]'",
            file=sys.stderr,
        )
        return 1
    settings = Settings.from_env()
    print(f"AI Jury console -> http://{host}:{port}  (provider: {settings.provider})")
    uvicorn.run("aijury.api.server:create_app", host=host, port=port,
                reload=reload, factory=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aijury", description="Multi-agent deliberation.")
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="Deliberate on a question.")
    ask.add_argument("question")
    ask.add_argument("--trace", action="store_true", help="Dump the full trace to stderr.")
    ask.add_argument("--json", action="store_true", help="Emit the raw Verdict object.")

    ev = sub.add_parser("eval", help="Run the golden set; compares jury against baseline.")
    ev.add_argument("--dataset", default="src/aijury/evaluation/datasets/golden.jsonl")
    ev.add_argument("--concurrency", type=int, default=4)

    sub.add_parser("lessons", help="Extract lessons from the failure store.")

    migrate = sub.add_parser("db-migrate", help="Apply learning-loop schema to DATABASE_URL.")

    serve = sub.add_parser("serve", help="Run the web console.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "ask":
        return asyncio.run(_ask(args.question, show_trace=args.trace, as_json=args.json))
    if args.command == "eval":
        return asyncio.run(_eval(args.dataset, args.concurrency))
    if args.command == "lessons":
        return _lessons()
    if args.command == "db-migrate":
        return _db_migrate()
    if args.command == "serve":
        return _serve(args.host, args.port, args.reload)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
