# CLAUDE.md

Context for Claude Code working in this repo. See `AGENTS.md` for the full
invariant list and `docs/CODEGRAPH.md` for the symbol map.

## Commands

```bash
./setup.sh              # venv + deps + .env + test run (idempotent)
source .venv/bin/activate
make test               # 73 tests, fully offline via the mock provider
make serve              # web console at http://localhost:8000
make lint               # ruff
make typecheck          # mypy --strict
make codegraph          # regenerate docs/CODEGRAPH.md + docs/codegraph.json
make eval               # jury vs baseline; the ship gate
make run Q="..."        # single deliberation
```

## Before you finish any change

1. `make test` passes.
2. `make codegraph` re-run **if you added, moved, or deleted a module**. A new
   package also needs an entry in `tools/codegraph/build.py::PHASE_MAP`, or
   `test_codegraph_builds_and_maps_phases` fails on the unclassified module.
3. Changes to deliberation mechanics (`protocol/`, `agents/`, `core/termination.py`)
   need `make eval` on a real provider, not just the mock. The mock validates
   plumbing, never reasoning quality.

## Architecture in one line

`Framer` classifies → `spawn_jury` builds the panel → round 0 blind drafts →
rounds 1..N anonymized cross-examination + `Adversary` + `Moderator` cruxes +
`Verifier` → `TerminationController` picks the exit → `Synthesizer` emits a
`Verdict`.

Three interfaces, all thin wrappers over `protocol/deliberation.py`: the CLI
(`cli.py`), the HTTP API (`api/server.py`), and the console (`web/index.html`,
plain HTML/JS with no build step — edit and reload).

`DeliberationView` in `api/schemas.py` is deliberately *not* the `Verdict`. The
Verdict is the product and carries no transcript; the view is the operator's
debugging window. Do not merge them.

## Invariants that are easy to break by accident

- **Round 0 must stay blind.** Jurors cannot see peers before drafting. This is
  the primary anti-herding measure and nothing will fail loudly if you remove it.
- **Cross-examination reads `transcript(anonymized=True)`.** Author names are an
  authority cue that drives convergence on fluency over correctness.
- **Confidence is capped by verified-claim ratio**, not agreement
  (`Synthesizer._finalize`). Do not let the model set it freely.
- **`GREY_AREA` verdicts must carry dissent or `what_would_change_this`** —
  enforced in `contracts/verdict.py`. Do not relax this validator to make a test
  pass; it is the guard against manufacturing false consensus.
- **Agents never call other agents.** All sequencing lives in `protocol/`.
- **Only `config.py` reads `os.environ`.**
- **Never return nothing.** Every failure path degrades to an honest verdict.

Full list with rationale: `AGENTS.md`. Design rationale: `docs/DECISIONS.md`.

## Highest-value work, in order

1. **Retrieval verifier** (`verification/`) — the largest correctness gap. Factual
   claims currently fall through to model judgement, so `QuestionType.FACTUAL`
   has no independent mistake signal.
2. **Regression gate** for the learning loop — lessons can currently be promoted
   without re-running eval. They routinely fix one failure mode and open another.
3. **Production sandbox** for `verification/code_execution.py` — subprocess plus
   timeout is development-grade only.
4. **Caching** of sub-answers between deliberations.
5. **Auth and rate limiting** on the API before it leaves localhost.

## Style

Type hints everywhere; `mypy --strict` is clean and should stay that way.
Docstrings explain *why*, not what. Comments earn their place by capturing a
non-obvious decision — this codebase has several, and they are load-bearing.
