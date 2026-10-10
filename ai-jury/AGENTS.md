# Project context for AI agents

Read this first, then `docs/CODEGRAPH.md` for the full symbol map.
`docs/codegraph.json` is the same graph, machine-readable. Regenerate both with
`make codegraph` after any structural change.

## What this is

`aijury` runs a panel of LLM agents through a structured deliberation and emits a
single `Verdict`. Fully autonomous: the user prompt is context, not control flow.

## Orientation in 60 seconds

| You want to change | Go to |
|---|---|
| the shape of the output | `contracts/verdict.py` |
| how questions are classified | `contracts/taxonomy.py` |
| when the debate stops | `core/termination.py` |
| the round structure | `protocol/deliberation.py` |
| what an agent is told to do | `agents/*.py` (`persona()` on each) |
| how claims get checked | `verification/` + `agents/verifier.py` |
| how outcome and confidence are decided | `agents/synthesizer.py::_finalize` |
| how the panel is sized | `agents/spawner.py` |
| how failures become lessons | `learning/lesson_extractor.py` |
| cost and time ceilings | `config.py::Budget`, `core/budget.py` |
| HTTP endpoints | `api/server.py` |
| the web console | `web/index.html` (no build step) |

Read order for full context: `contracts/` → `core/blackboard.py` →
`core/termination.py` → `protocol/deliberation.py` → `agents/synthesizer.py`.

## Invariants — do not break these

1. **Agents never own control flow.** All sequencing lives in `protocol/`. An
   agent that calls another agent has broken the audit trail.
2. **The blackboard is append-only.** Post-hoc error attribution depends on being
   able to reconstruct exactly what each agent saw. Mutating history destroys it.
3. **Round 0 is blind.** Jurors must not see peer positions before drafting. This
   is the primary anti-herding measure; removing it silently degrades the panel.
4. **Cross-examination is anonymized.** `transcript(anonymized=True)` — author
   names are an authority cue that drives convergence on fluency over correctness.
5. **The Verifier is never the same instance as the proposer.** Self-verification
   ratifies its own reasoning.
6. **Confidence is capped by verified support, not agreement.** See
   `Synthesizer._finalize`.
7. **`GREY_AREA` verdicts must carry dissent or `what_would_change_this`.**
   Enforced at the schema level in `contracts/verdict.py`.
8. **Deterministic verifiers outrank model judgement** wherever they apply
   (`VerificationResult.decisive`).
9. **Retrieved content is data, never instruction.** Route it through
   `security/injection.py::sanitize_untrusted`.
10. **Never return nothing.** Every failure path degrades to an honest verdict —
    see `Deliberation._fallback_verdict` and `JuryPipeline.ask`.
11. **No module outside `config.py` reads `os.environ`.**
12. **`DeliberationView` is not `Verdict`.** The Verdict is the product and
    carries no transcript; the view is the operator's debugging window. Merging
    them leaks deliberation into the output contract.
13. **Every module maps to a plan phase** in `tools/codegraph/build.py::PHASE_MAP`.
    Adding a package means adding its phase, or `make codegraph` will fail the test.

## Adding things

**A new agent role:** subclass `agents/base.py::Agent`, define `persona()` and a
Pydantic output schema, then wire it into `protocol/deliberation.py::_run_round`.
Never call it from another agent.

**A new verifier:** implement `verification/base.py::Verifier`
(`method`, `applies`, `check`), register it in `verification/registry.py`, and add
its method to `VERIFICATION_MATRIX` for the question types it can settle. Set
`decisive=True` only when the check genuinely applied and its answer is
authoritative — non-decisive means "this tool had nothing to say", not "pass".

**A new question type:** add to `QuestionType`, add a `VERIFICATION_MATRIX` entry,
add `_DEFAULT_PERSPECTIVES` in `spawner.py`, add golden cases, update the Framer
persona.

## Testing

`make test` — 60 tests, entirely offline via `llm/mock.py`. The mock synthesizes
schema-valid JSON from the schema embedded in the system prompt, so orchestration
is fully exercised without a network call. It does **not** test reasoning quality;
that is what `make eval` against a real provider is for.

Any change to deliberation mechanics must be validated with `make eval` on a real
provider before shipping. Structural changes routinely fix one failure mode and
open another.

## Where the risk is

- `agents/synthesizer.py::_finalize` — outcome and confidence policy. Highest blast
  radius in the codebase.
- `core/termination.py` — get this wrong and you get infinite loops or fake consensus.
- `verification/registry.py` — a verifier wrongly marked `decisive` silently
  launders a false claim into a verified one.
