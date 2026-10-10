# AI Jury

Multiple agents deliberate on a question and produce a single verified, calibrated
verdict. No human in the loop during deliberation; the user prompt supplies context
only. Output is the result — never the reasoning transcript.

## What it does

```
question
   ↓
Framer            classifies the question, names hidden assumptions, designs the panel
   ↓
Spawner           creates 2–N jurors, one per required perspective, capped
   ↓
Round 0           jurors draft blind — no juror sees another (anti-herding)
   ↓
Round 1..N        cross-examination against anonymized peers
                  → Adversary attacks whatever is leading
                  → Moderator isolates cruxes
                  → Verifier settles what tools can settle
   ↓
Termination       consensus / stable divergence / oscillation / exhaustion
   ↓
Synthesizer       Verdict: answer, calibrated confidence, dissent, what's open
```

## Install into your project

This repo is self-contained. Unpack it wherever you want it to live:

```bash
tar -xzf ai-jury.tar.gz          # creates ./ai-jury
cd ai-jury
./setup.sh                       # venv + deps + .env + test run
source .venv/bin/activate
```

`setup.sh` is idempotent, so re-running it is safe.

## Quickstart

```bash
make setup         # or: ./setup.sh
make serve         # web console at http://localhost:8000
make test          # 73 tests, fully offline
make run Q="Should a startup prioritize growth or profitability in year two?"
make eval          # jury vs single-agent baseline on the golden set
make codegraph     # regenerate docs/CODEGRAPH.md + docs/codegraph.json
```

## Web console

`make serve` opens an operator console at `http://localhost:8000`. It streams the
deliberation live over SSE rather than making you wait on a spinner: the panel
being seated, each round closing with its agreement score, claims passing or
failing verification, and finally the verdict.

The console is built around one idea — **showing where confidence came from**.
Each position's confidence bar is split: solid for the portion backed by verified
claims, hatched for the rest. A panel that agrees loudly on unverified claims
renders as a mostly-hatched bar, which is exactly what it deserves. Below the
verdict, the round spine shows who drafted what before seeing anyone else, who
changed position and why, and which cruxes were never settled.

Color carries role and nothing else: brass is the Adversary, teal is verified,
red is failed verification.

| Endpoint | Purpose |
|---|---|
| `GET /` | The console |
| `GET /api/health` | Provider, limits, active lesson count |
| `POST /api/ask` | Run a deliberation, return the full record |
| `GET /api/stream` | The same, streamed as SSE |

`POST /api/ask` accepts `max_rounds` and `max_jurors` per request, so you can
tune cost per question without restarting.

**The API binds to `127.0.0.1` and CORS is limited to localhost.** It has no
authentication and no rate limiting. Add both before exposing it anywhere.

## Configuration

All settings live in `.env`, loaded automatically by `Settings.from_env()`. Real
environment variables take precedence over the file, so anything exported in your
shell or injected by an orchestrator wins — a checked-out file never silently
overrides your deployment config.

Ships on the deterministic mock provider: no API key, no network. To use a real
model, edit `.env`:

```bash
AIJURY_PROVIDER=anthropic
AIJURY_MODEL=<model-id>
ANTHROPIC_API_KEY=<key>

# Optional: a heterogeneous panel, one model per juror.
AIJURY_MODEL_POOL=<model-a>,<model-b>,<model-c>
```

| Variable | Default | Effect |
|---|---|---|
| `AIJURY_PROVIDER` | `mock` | `mock` (offline) or `anthropic` |
| `AIJURY_MAX_ROUNDS` | `4` | Hard cap on deliberation rounds |
| `AIJURY_MAX_JURORS` | `5` | Caps the spawner; the main cost lever |
| `AIJURY_STABILITY_WINDOW` | `2` | Unchanged-but-divergent rounds before declaring a grey area |
| `AIJURY_CONFIDENCE_FLOOR` | `0.45` | Below this, report `UNRESOLVED` instead of asserting |
| `AIJURY_TOKEN_BUDGET` | `200000` | Terminates deliberation on breach |
| `AIJURY_MAX_LLM_CALLS` | `120` | Circuit breaker against runaway debate |
| `AIJURY_WALL_CLOCK_SECONDS` | `300` | Latency ceiling |
| `AIJURY_SEED` | `7` | Makes mock runs reproducible |

`.env` is gitignored. `.env.example` is the committed template.

## Design decisions worth knowing

**Herding is the default failure of multi-agent debate.** Agents converge on the
most confidently-stated position rather than the correct one. Three structural
defences: jurors draft blind in round 0; peer positions are anonymized during
cross-examination; an Adversary is required to attack the leading position every
round whether or not it agrees.

**Confidence is capped by verification, not by agreement.** A panel can agree
confidently and be wrong. `Synthesizer._finalize` ceilings confidence at
`0.5 + 0.5 × verified_claim_ratio`. Consensus alone cannot buy a high number.

**Grey areas are results, not failures.** `Verdict` refuses at the schema level to
be `GREY_AREA` without carrying dissent or `what_would_change_this`. Stable
divergence across rounds terminates deliberation as a mapped disagreement rather
than forcing a fake consensus.

**"Learn from mistakes" needs a mistake signal.** Self-identified errors are
near-worthless — the panel's blind spots are what it cannot see. `learning/`
consumes eval ground truth, deterministic verifier failures, or production
feedback. Lessons require 3 recurrences before promotion, are capped at 6 in any
prompt, and are deactivated by the regression gate if they hurt eval scores.

**Retrieved content is data, never instruction.** `security/injection.py` fences
untrusted text and flags instruction-like patterns. A jury that retrieves is a
large attack surface: hostile text read by one juror is read by every agent
downstream.

## Ship gate

`make eval` runs the jury and a single-agent baseline over the same questions and
fails unless the jury wins on accuracy without regressing calibration or false
consensus. **A jury that does not beat the baseline is an expensive complication.**
Keep this gate.

Note: on the mock provider the arms score near-zero accuracy by construction — the
mock produces schema-shaped placeholder text, not reasoning. That run is a plumbing
check. Real accuracy numbers require a real provider.

## Metrics that matter

| Metric | Why |
|---|---|
| accuracy | did it get it right |
| ECE / Brier | does 0.8 confidence mean right 80% of the time |
| false_consensus_rate | the failure mode specific to this architecture |
| cost ratio vs baseline | a 40× cost win on 2% accuracy is not a win |

## Status by phase

| Phase | State |
|---|---|
| 0 — contracts, taxonomy, eval harness, scorer | complete |
| 1 — single-agent baseline | complete |
| 2 — blackboard, budget, tracing, termination | complete |
| 3 — agent roles, dynamic spawning | complete |
| 4 — deliberation protocol | complete |
| 5 — verification layer | recomputation, consistency, code-exec (opt-in); **retrieval is a stub** |
| 6 — learning loop | store + extractor + injector complete; **regression gate is manual** |
| 7 — output layer | complete — CLI, HTTP API, streaming web console |
| 8 — hardening | injection defence, budgets, circuit breakers, graceful degradation; **no caching, no persistence beyond JSONL** |

## Known gaps

- **Retrieval verifier is not implemented.** Factual claims currently fall through
  to model judgement. This is the largest correctness gap.
- **Code execution sandbox is development-grade** (subprocess + timeout). Production
  needs a container or microVM with seccomp, read-only FS, and no egress.
- **Failure store is JSONL.** Swap for Postgres; the interface holds.
- **No caching** of sub-answers between deliberations.
- **The web API has no auth, rate limiting, or request queueing.** It is a local
  operator tool as shipped.
- **Contradiction detection is crude** (direct negation only). Real contradiction
  detection is a research problem; this catches blatant cases and defers the rest.
