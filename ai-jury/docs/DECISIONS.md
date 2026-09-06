# Decision log

Each entry: the decision, the alternative rejected, and the reason.

## D1 — Blind first round
Jurors draft independently before seeing peers. Rejected: everyone sees the shared
board from round 0 (simpler, one fewer round). Once a juror reads a confident peer,
its independent signal is unrecoverable, and independent signal is the entire
justification for running a panel instead of one model.

## D2 — Anonymized cross-examination
Author identity is stripped from the transcript jurors read. Rejected: named
positions (better traceability). Names are an authority cue; jurors converge on
whoever sounds most certain rather than on the better argument.

## D3 — Adversary as a structural role, not a personality
A dedicated agent attacks the leading position every round regardless of private
agreement. Rejected: one juror assigned a contrarian persona. A contrarian juror
still wants to be right and will defect toward consensus; a role with no position
to defend will not.

## D4 — Confidence ceiled by verified-claim ratio
Rejected: let the synthesizer state confidence freely. Models report convergence
as confidence. The whole calibration story collapses if agreement can buy a number.

## D5 — Grey areas terminate as results
`STABLE_DIVERGENCE` is a successful exit, and the schema rejects a `GREY_AREA`
verdict with no mapped disagreement. Rejected: keep debating until convergence.
Forcing consensus on genuinely contested questions is the most damaging thing this
architecture can do, and it does it fluently.

## D6 — Deterministic verifiers outrank the model verifier
Rejected: single model-based verifier for everything. A verifier no stronger than
the debaters supplies no independent mistake signal, and without a mistake signal
the Phase 6 learning loop has nothing to learn from.

## D7 — Lessons require 3 recurrences and cap at 6 per prompt
Rejected: inject every recorded lesson. Single failures are noise; prompts stuffed
with accumulated corrections perform worse than clean ones. Past a handful, lessons
should be promoted into code — new verifiers, new termination rules — not more prose.

## D8 — Baseline arm is permanent
Rejected: delete the single-agent path once the jury works. It is the control that
justifies the architecture's cost and the fallback when deliberation times out.

## D9 — Mock provider is a first-class component
Rejected: mock only in tests. The full eval harness and CI run against it, which
keeps orchestration bugs separable from reasoning quality. Debugging both at once
is where these projects stall.

## D10 — Codegraph is generated, never hand-maintained
Pure AST analysis, no imports of target code, so it works on a repo that does not
currently run and cannot execute anything. Hand-maintained architecture docs go
stale within weeks and then actively mislead.

## D11 — SSE, not WebSockets, for live deliberation
The stream is one-directional and lives for one deliberation. Duplex framing buys
nothing and costs reconnect handling. Tracer spans land on a queue and are drained
by the response generator, so a slow client cannot throttle the panel.

## D12 — The console shows where confidence came from
Confidence renders as a split bar: solid for the portion backed by verified
claims, hatched for the remainder. A number alone is unfalsifiable at a glance,
and the failure mode this system is most prone to — a panel agreeing loudly on
unverified claims — is invisible until you make the verified fraction visual.

## D13 — `DeliberationView` is separate from `Verdict`
Rejected: return the blackboard on the Verdict. The Verdict is the product and
must carry no transcript (that is the output contract). The view exists only
because a human is debugging the panel rather than consuming its answer.
