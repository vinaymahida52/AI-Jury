# Closed Learning Loop Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox syntax.

**Goal:** Persist deliberations and close the failure→lesson→inject loop (with similar-case prior knowledge) via Neon when `DATABASE_URL` is set, file backend otherwise.

**Architecture:** Learning repository behind a single interface (`FileLearningRepository` | `PostgresLearningRepository`). Persist at API/pipeline boundaries after deliberation; load active lessons + similar past cases before ask; record production feedback as failures; `aijury lessons` promotes patterns.

**Tech Stack:** Python 3.11+, existing learning package, optional `psycopg`, Neon `DATABASE_URL`.

## Global Constraints

- No module outside `config.py` reads `os.environ`
- Agents never own control flow; persistence is a side effect at boundaries
- Prior cases injected as data, lessons as constraints
- Offline tests must pass without Postgres (file/memory backend)
- Keep `FailureStore` / `load_lessons` / `save_lessons` call sites working

---

### Task 1: Repository interface + file backend + tests

- [ ] Failing tests for case persist, failure roundtrip, lessons, similar cases
- [ ] Implement `LearningRepository` + `FileLearningRepository`
- [ ] Wire factory from `Settings.database_url`

### Task 2: Postgres backend + schema

- [ ] `schema.sql` + `PostgresLearningRepository`
- [ ] Optional `db` extra (`psycopg`)
- [ ] Load `.env.local` for `DATABASE_URL`

### Task 3: Close the loop at boundaries

- [ ] `build_deliberation_context` (lessons + priors)
- [ ] Persist after pipeline/API deliberation
- [ ] Feedback endpoint + CLI migrate/lessons path
- [ ] Prior knowledge channel on `AgentContext`

### Task 4: Verify

- [ ] `make test`
- [ ] Apply schema to linked Neon project when URL present
