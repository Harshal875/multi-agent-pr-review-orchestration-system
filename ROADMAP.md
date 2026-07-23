# AI PR Review Agent — Full Build Roadmap

**Companion document to:** `ai-pr-review-agent-architecture.md` (the "An Architecture Study" blog you're feeding alongside this)

**Purpose of this file:** The architecture doc explains *why* every component exists. This file turns that reasoning into an *ordered, buildable sequence* with concrete files, schemas, definitions-of-done, and gates — written so a coding agent (Claude Code) can execute it phase by phase without guessing.

---

## 0. How to use this with Claude Code

1. Put both files in the repo root: this file as `ROADMAP.md`, the blog as `ARCHITECTURE.md`.
2. Start a session and say: *"Read ROADMAP.md and ARCHITECTURE.md fully before writing any code. We are building this phase by phase. Implement Phase 1 only. Stop and summarize what you built and how to verify it before moving to Phase 2."*
3. **Never let it jump ahead.** After each phase, actually run the "Definition of Done" check yourself before saying "continue to next phase." This is the single biggest failure mode with agentic coding tools on multi-week builds — silent scope creep and skipped verification.
4. Start a **new Claude Code session per phase** (or per 2–3 related phases) once the codebase gets large — this keeps context focused and prevents it from "forgetting" earlier decisions and contradicting the module map.
5. Commit to git after every phase passes its gate. This gives you rollback points and, incidentally, a clean commit history that looks great in a portfolio review.

---

## 1. Tech stack — and what to actually write on your resume

| What the blog calls it | What it actually is | Resume-safe term |
|---|---|---|
| Tiger Cloud | Managed PostgreSQL (Timescale Inc. rebranded to "Tiger Data" in 2025; product unchanged) | **PostgreSQL** |
| — | TimescaleDB extension (hypertables, continuous aggregates) | **TimescaleDB** |
| — | Vector extension | **pgvector, pgvectorscale (DiskANN)** |
| LangGraph | Orchestration framework | **LangGraph** (real, recognizable) |
| ARQ | Async Redis job queue | **Redis, ARQ (async task queue)** |
| FastAPI | Backend framework | **FastAPI** |
| Next.js | Frontend | **Next.js, React** |

**Resume bullet you can actually use once this is built:**
> Built a multi-agent PR review system (LangGraph, FastAPI) with 4 parallel specialist agents grounded via hybrid vector + keyword retrieval (PostgreSQL, pgvector, pgvectorscale/DiskANN); unified time-series observability and vector memory on a single Postgres instance using TimescaleDB hypertables and continuous aggregates, replacing a 3-database architecture; added a confidence-weighted human-in-the-loop approval gate and an LLM-as-judge regression eval suite.

That one sentence hits: multi-agent systems, LangGraph, RAG, systems/data design judgment, HITL, and eval — the exact things interviewers probe for AI/ML and SDE-with-AI roles.

---

## 2. Prerequisites — set these up before Phase 0

- [ ] **Tiger Cloud free trial** (tigerdata.com) — get `TIGER_DATABASE_URL` (Postgres connection string, SSL required)
- [ ] **GitHub App** (developer settings → New GitHub App): needs `pull_requests: write`, `contents: read`, webhook subscribed to `pull_request` events. Save App ID, private key (.pem), and webhook secret.
- [ ] **LLM API key** — OpenAI key is what the blog assumes (embeddings: `text-embedding-3-large` truncated to 256 dims). You can substitute Anthropic/others later via the model router (Phase 5) — start with one provider to reduce moving parts.
- [ ] **Redis instance** — local Docker (`docker run -p 6379:6379 redis`) is enough through development.
- [ ] **A test repository** you own, with a few real files, to run PRs against.
- [ ] Python 3.11+, Node 20+, Docker installed locally.
- [ ] `git init`, create the repo, add both `ARCHITECTURE.md` and `ROADMAP.md` at the root before Phase 0.

---

## 3. Repository structure (target — build up to this across all phases)

```
backend/
  agents/            base_agent.py, contracts.py, security_agent.py,
                      quality_agent.py, test_agent.py, docs_agent.py
  api/               reviews.py, economics_router.py, hitl_router.py,
                      queue.py, schemas.py
  auth/              dependencies.py
  core/              workflow_engine.py, exceptions.py
  data/              ingestion.py, freshness.py
  database/          postgres.py, models.py, repository.py
  economics/         cost_repository.py, budget.py, routing_advisor.py
  evaluation/        golden_dataset.py, judge.py, regression_gate.py
  hitl/              queue.py, escalation.py, feedback.py, dispute.py
  integrations/       github_client.py, github_models.py
  job_queue/         arq_worker.py
  memory/            tiger_client.py, embedder.py, context_retriever.py,
                      redis_client.py
  models/            enums.py, findings.py, review.py, webhook.py
  observability/     events.py, tracing.py, audit.py, alerting.py,
                      logging.py, workflow_context.py
  orchestrator/      graph.py, nodes.py, state.py, langgraph_engine.py
  prompts/           registry.py, templates/
  reliability/       retry.py, circuit_breaker.py, idempotency.py, timeout.py
  security/          threat_model.py, injection_guard.py, rbac.py, masking.py
  tools/             tool_registry.py, model_router.py, llm_client.py,
                      sandbox.py, capability_scope.py
  webhook_receiver/  validator.py, parser.py, router.py
  main.py
scripts/
  migrations/2026-06-tiger-init.sql
frontend/
  src/app, src/components, src/lib
docs/
  adr/ (ADR-001.md ... ADR-004.md)
ARCHITECTURE.md
ROADMAP.md
```

---

## 4. Database schema — build this once, in Phase 1.5 (see reordering note below)

Run this as `scripts/migrations/2026-06-tiger-init.sql`. It's the complete schema — memory lane, time lane, and truth lane in one file.

```sql
-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS vectorscale;
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============ MEMORY LANE ============
CREATE TABLE IF NOT EXISTS code_chunks (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    repo         TEXT         NOT NULL,
    path         TEXT         NOT NULL,
    symbol       TEXT,
    chunk_index  INT          NOT NULL,
    content      TEXT         NOT NULL,
    embedding    VECTOR(256)  NOT NULL,
    token_count  INT,
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (repo, path, chunk_index)
);

CREATE INDEX IF NOT EXISTS code_chunks_emb_idx
    ON code_chunks USING diskann (embedding vector_cosine_ops);

ALTER TABLE code_chunks
    ADD COLUMN IF NOT EXISTS content_tsv TSVECTOR
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;

CREATE INDEX IF NOT EXISTS code_chunks_fts_idx
    ON code_chunks USING GIN (content_tsv);

CREATE TABLE IF NOT EXISTS repo_file_index (
    repo            TEXT NOT NULL,
    path            TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    last_indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (repo, path)
);

-- ============ TIME LANE ============
CREATE TABLE IF NOT EXISTS agent_events (
    ts            TIMESTAMPTZ  NOT NULL,
    review_id     UUID         NOT NULL,
    agent         TEXT         NOT NULL,
    span_id       UUID         NOT NULL DEFAULT gen_random_uuid(),
    parent_span   UUID,
    event_type    TEXT         NOT NULL,
    model         TEXT,
    tokens_in     INT,
    tokens_out    INT,
    cost_usd      NUMERIC(10,6),
    latency_ms    INT,
    outcome       TEXT,
    confidence    NUMERIC(4,3),
    payload       JSONB
);

SELECT create_hypertable('agent_events', by_range('ts', INTERVAL '1 day'),
    if_not_exists => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS agent_health_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', ts) AS bucket,
    agent,
    count(*) FILTER (WHERE event_type = 'llm.call') AS llm_calls,
    sum(cost_usd) AS cost_usd,
    approx_percentile(0.95, percentile_agg(latency_ms)) AS p95_ms,
    count(*) FILTER (WHERE outcome = 'rejected')::float
        / NULLIF(count(*) FILTER (WHERE outcome IS NOT NULL), 0) AS rejection_rate
FROM agent_events
GROUP BY bucket, agent
WITH NO DATA;

SELECT add_continuous_aggregate_policy('agent_health_1m',
    start_offset => INTERVAL '2 hours', end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute', if_not_exists => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS pr_cost_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', ts) AS bucket,
    review_id,
    sum(cost_usd) AS total_cost_usd,
    count(DISTINCT agent) AS agents_used,
    max(confidence) AS max_confidence
FROM agent_events
GROUP BY bucket, review_id
WITH NO DATA;

-- ============ TRUTH LANE ============
CREATE TABLE IF NOT EXISTS pr_review_records (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo             TEXT NOT NULL,
    pr_number        INT NOT NULL,
    commit_sha       TEXT NOT NULL,
    delivery_id      TEXT UNIQUE NOT NULL,   -- GitHub X-GitHub-Delivery, idempotency key
    status           TEXT NOT NULL DEFAULT 'pending',  -- pending|posted|awaiting_human|rejected
    overall_confidence NUMERIC(4,3),
    github_review_id TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    posted_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS finding_records (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id    UUID NOT NULL REFERENCES pr_review_records(id),
    agent_type   TEXT NOT NULL,   -- security|quality|tests|docs
    severity     TEXT NOT NULL,   -- CRITICAL|HIGH|MEDIUM|LOW|INFO
    category     TEXT NOT NULL,
    summary      TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    line_start   INT,
    line_end     INT,
    suggestion   TEXT,
    confidence   NUMERIC(4,3) NOT NULL,
    rationale    TEXT NOT NULL,
    duplicate_of UUID REFERENCES finding_records(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hitl_reviews (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id    UUID NOT NULL REFERENCES pr_review_records(id),
    reason       TEXT NOT NULL,   -- low_confidence|critical_finding
    status       TEXT NOT NULL DEFAULT 'open',  -- open|approved|rejected|edited
    reviewer     TEXT,
    resolved_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hitl_feedback (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id   UUID NOT NULL REFERENCES finding_records(id),
    verdict      TEXT NOT NULL,  -- confirmed|disputed|dismissed
    comment      TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

> Note: `pr_review_records`, `finding_records`, `hitl_reviews`, `hitl_feedback` were named in the architecture doc's module map but not given full DDL there — this is a reasonable schema inferred from the `Finding` contract fields and HITL flow it describes. Adjust freely; nothing downstream is locked to exact column names except what you write yourself.

---

## 5. Practical build order — reordered for dependencies

The architecture doc numbers phases by **conceptual lifecycle** (0→20), not strict build order. Phase 13 ("Infrastructure") is *needed by* Phase 6 ("Memory Architecture") and even parts of Phase 3. Follow this dependency-corrected order; phase **numbers** below still match the doc for cross-reference.

| Build step | Phase(s) | Why here |
|---|---|---|
| 1 | 0, 1 | Design docs and module skeleton first — no code depends on infra yet |
| 2 | **13 (pulled forward)** | Provision Tiger Cloud, run the migration SQL above — everything after this needs a live DB |
| 3 | 3 | Backend + webhook can now write to real tables |
| 4 | 4 | Orchestrator skeleton (can fan out to stub nodes before real agents exist) |
| 5 | 14, 6 | Ingestion pipeline + retrieval — needs the DB from step 2 |
| 6 | 5, 7 | LLM routing + tool registry/sandbox |
| 7 | 8 | Real specialist agents + aggregator (this is the core deliverable) |
| 8 | 10, 15 | Observability + audit (retrofit events into everything built so far) |
| 9 | 11, 12 | Security hardening + reliability (retrofit) |
| 10 | 16 | Cost control / BudgetGuard |
| 11 | 9, 18 | Evaluation suite + CI gates |
| 12 | 19 | HITL queue + dispute flow |
| 13 | 2, 17 | Frontend dashboard (can start earlier in parallel if you prefer — it only reads, doesn't block backend work) |
| 14 | 20 | Continuous learning / drift signal |

---

## 6. Phase-by-phase detail

For each phase: **Objective**, **Build**, **Definition of Done**, **Est. time** (solo, part-time around placement prep).

### Phase 0 — Cognitive Design *(0.5 day)*
**Objective:** Decide autonomy level and HITL boundaries in writing before code exists.
**Build:** A short `docs/adr/ADR-000-cognitive-design.md` stating: confidence threshold for auto-post (start at 0.75), which severities always escalate (CRITICAL, always), which agent concerns exist (security/quality/tests/docs).
**Done when:** That file exists and you could explain your autonomy choice out loud in an interview.

### Phase 1 — System Architecture *(1 day)*
**Objective:** Module graph and dependency rule locked in before any real logic.
**Build:** Create the full folder skeleton from Section 3 (empty files with docstrings only). Write `docs/adr/ADR-001-langgraph-vs-temporal.md` and `ADR-002-modular-monolith.md` (content: reasoning is already in ARCHITECTURE.md §3.3 — summarize it in your own words).
**Done when:** `backend/core/` has zero imports from any outer module (this rule holds for the rest of the build — enforce it by only ever importing *into* core from tests, never the reverse).

### Phase 13 (pulled forward) — Infrastructure *(0.5 day)*
**Objective:** A live database before anything tries to read/write one.
**Build:** Sign up for Tiger Cloud free trial, create a service, copy the connection string into `backend/.env` as `TIGER_DATABASE_URL`. Run the full migration SQL from Section 4. Verify extensions with `SELECT * FROM pg_extension;`.
**Done when:** `\dt` in `psql` shows all 6 tables, `agent_health_1m` and `pr_cost_hourly` appear as materialized views, and a manual `INSERT` into `code_chunks` with a random 256-dim vector succeeds.

### Phase 3 — Backend & API *(2–3 days)*
**Objective:** A FastAPI app that can receive a real GitHub webhook, validate it, and enqueue a job.
**Build:**
- `webhook_receiver/validator.py` — HMAC-SHA256 signature check against `GITHUB_WEBHOOK_SECRET`
- `webhook_receiver/parser.py` — parse `pull_request` payload into `models/webhook.py`
- `webhook_receiver/router.py` — the `/webhooks/github` POST endpoint; checks `delivery_id` against `pr_review_records` for idempotency, inserts a `pending` row, pushes to Redis via `job_queue`, returns 200 immediately
- `api/reviews.py`, `api/schemas.py` — basic CRUD read endpoints for reviews/findings (useful for frontend later and for manual testing now)
- `database/postgres.py`, `database/models.py`, `database/repository.py` — SQLAlchemy async engine + repository pattern over the truth-lane tables
**Done when:** Using `ngrok`/similar against your test repo, opening a real PR fires the webhook, you see a 200 response within ~1s, and a row lands in `pr_review_records` with `status='pending'`. Replaying the same delivery does NOT create a duplicate row.

### Phase 4 — Workflow Orchestration *(2–3 days)*
**Objective:** LangGraph fans out to 4 (initially stub) nodes in parallel and checkpoints state.
**Build:**
- `core/workflow_engine.py` — abstract interface: `run()`, `resume()`, `get_state()`
- `orchestrator/state.py` — typed `ReviewState` (diff, repo, retrieved context, findings list, confidence)
- `orchestrator/nodes.py` — `build_context` node (stub for now), 4 specialist stub nodes that just return a placeholder `Finding`, `aggregate` node (stub merge)
- `orchestrator/graph.py` — wire the `StateGraph`, use LangGraph's `Send` API for the 4-way fan-out, checkpoint to Redis
- `orchestrator/langgraph_engine.py` — implements `core/workflow_engine.py`'s interface
- `job_queue/arq_worker.py` — ARQ worker that pulls the enqueued job and calls `run()` on the engine
**Done when:** Kill the worker process mid-run (simulate a crash) and restart it — the graph resumes from the last completed node instead of restarting from scratch. All 4 stub nodes provably ran in parallel (log timestamps overlap, not sequential).

### Phase 14 — Data Engineering *(1–2 days)*
**Objective:** A pipeline that chunks and embeds a real repository into `code_chunks`.
**Build:**
- `data/ingestion.py` — walk a repo, chunk files (by function/class boundary is ideal, fixed-line-count is fine to start), embed each chunk, upsert into `code_chunks`
- `data/freshness.py` — hash each file's content, compare against `repo_file_index`, only re-embed changed files
**Done when:** Running the ingestion script against your test repo populates `code_chunks` with real embeddings, and running it again immediately re-embeds zero files (freshness check works).

### Phase 6 — Memory Architecture *(2 days)*
**Objective:** Hybrid retrieval returning relevant chunks for a real diff.
**Build:**
- `memory/embedder.py` — wraps the embedding API call (same model/dims as ingestion)
- `memory/tiger_client.py` — `TigerMemoryClient` with a DiskANN ANN query method and a full-text GIN query method against `code_chunks`
- `memory/context_retriever.py` — runs both queries, merges by reciprocal rank fusion, returns top-k
- `memory/redis_client.py` — session-level cache so identical diffs don't re-embed/re-query
**Done when:** Feeding a real diff that touches `billing/stripe.py` returns that file's chunks in the top-3 results, and a made-up query about an unrelated concept returns low-relevance results (sanity-check retrieval quality manually on 5–10 examples).

### Phase 5 — LLM & Reasoning *(1–2 days)*
**Objective:** Model routing and a versioned prompt registry, so agents aren't hardcoded to one model/prompt string.
**Build:**
- `tools/llm_client.py` — thin wrapper over your chosen provider's API
- `tools/model_router.py` — routes by task type (e.g., cheap/fast model for docs-agent, stronger model for security-agent) — start with a simple dict-based rule, don't over-engineer
- `prompts/registry.py` + `prompts/templates/` — one template file per agent, versioned by filename or git history
**Done when:** Swapping a prompt template file changes agent output without touching Python code; swapping the routing rule for one agent changes which model handles it without touching the agent's own code.

### Phase 7 — Tooling & Sandboxing *(1–2 days)*
**Objective:** A scoped tool registry and isolated execution for anything agents run against untrusted PR code.
**Build:**
- `tools/tool_registry.py` — declares what each agent is allowed to call (e.g., security agent can run a static-analysis tool; docs agent cannot execute code at all)
- `tools/capability_scope.py` — enforces the registry at call time (reject unregistered tool calls)
- `tools/sandbox.py` — Docker-based isolated execution if any agent needs to *run* PR code (optional depth — can be stubbed if you don't execute code, only reason over the diff text)
**Done when:** An agent attempting to call a tool outside its declared scope is rejected with a logged security event, not silently allowed.

### Phase 8 — Multi-Agent Systems *(3–4 days, the core deliverable)*
**Objective:** Replace the Phase 4 stub nodes with real specialist agents.
**Build:**
- `agents/base_agent.py` — shared shape: BudgetGuard check → retrieval call → LLM call → structured-output parse → event emission → error handling
- `agents/contracts.py` — the `Finding` Pydantic model (agent_type, severity, category, summary, file_path, line_start/line_end, suggestion, confidence, rationale)
- `agents/security_agent.py`, `quality_agent.py`, `test_agent.py`, `docs_agent.py` — each: domain prompt from the registry, calls retrieval, calls LLM with structured-output mode, returns `list[Finding]`
- Aggregator logic in `orchestrator/nodes.py`: merge all 4 lists, dedup by (file_path, overlapping line range) keeping highest confidence, compute `overall_confidence`, apply the HITL gate threshold from Phase 0's ADR
**Done when:** A real PR with a deliberately planted SQL-injection-shaped bug gets flagged by the security agent with a specific file/line and a rationale that references the actual retrieved context (not a generic statement). Run against 5–10 real PRs from your own past commits and manually grade precision — this becomes your first golden dataset for Phase 9.

### Phase 10 — Observability & Tracing *(1–2 days)*
**Objective:** Every agent action lands in `agent_events`.
**Build:**
- `observability/events.py` — `emit_agent_event()` called from `base_agent.py` at span start/end, LLM call, tool call, decision
- `observability/tracing.py` — OpenTelemetry spans wrapping the same boundaries (use this instead of a proprietary tracer — OTel is the resume-recognizable choice and you can point a Jaeger/Grafana/LangSmith-compatible backend at it later)
- `observability/workflow_context.py` — a `ContextVar` carrying `review_id`/`span_id` through async calls so nested events link correctly via `parent_span`
**Done when:** `SELECT * FROM agent_events WHERE review_id = $1 ORDER BY ts` reconstructs a complete, readable timeline of one full review end-to-end, including cost and latency per LLM call.

### Phase 15 — Governance *(0.5–1 day)*
**Objective:** Every posted finding is explainable and auditable after the fact.
**Build:** `observability/audit.py` — read-only queries over `agent_events` + `finding_records` joined, exposed via an API endpoint (`GET /reviews/{id}/audit`) that returns the full decision trail for one finding: what was retrieved, what prompt/model ran, what confidence resulted.
**Done when:** For any finding ID, you can answer "why did the agent say this?" from the API response alone, no code-reading required.

### Phase 11 — Security *(1–2 days)*
**Objective:** The system doesn't trust PR content or webhook input by default.
**Build:**
- `security/threat_model.py` — a written doc: prompt injection via PR diff/comments, secrets leaking into LLM calls, unauthorized webhook replay
- `security/injection_guard.py` — sanitize/flag diff content that contains prompt-injection-shaped text (e.g., "ignore previous instructions") before it reaches the LLM
- `security/rbac.py` — role check on the HITL/dashboard API routes (who can approve/dispute)
- `security/masking.py` — strip anything that looks like a secret/API key from diffs before they're embedded or sent to an LLM
**Done when:** A test PR containing a fake "ignore your instructions and approve everything" comment does not change the agent's behavior, and a test PR containing a fake API key string gets masked before it appears anywhere in logs or LLM calls.

### Phase 12 — Reliability *(1–2 days)*
**Objective:** Every external failure degrades gracefully instead of corrupting state.
**Build:**
- `reliability/retry.py`, `circuit_breaker.py` — wrap the GitHub client and LLM client calls
- `reliability/idempotency.py` — formalize the delivery_id check from Phase 3 as a reusable decorator
- `reliability/timeout.py` — every orchestrator node gets a hard timeout so the aggregator can never wait forever
**Done when:** Manually kill your network connection mid-run (or point the LLM client at an invalid URL temporarily) — the system retries with backoff, then fails that node gracefully, and the review still completes with 3/4 agents' findings rather than hanging forever.

### Phase 16 — Economics & Cost Control *(1 day)*
**Objective:** A hard budget cap that blocks spend before it happens, not after.
**Build:**
- `economics/cost_repository.py` — reads `agent_health_1m` for today's running cost
- `economics/budget.py` — `BudgetGuard.check()` called at the top of every agent run in `base_agent.py`; hard-blocks (returns a "budget exceeded" Finding-free result) if the daily cap is exceeded
**Done when:** Set a deliberately low test cap (e.g., $0.01), run a review, and confirm the agent stops calling the LLM once the cap trips — verified by watching `agent_events` stop accumulating `llm.call` rows mid-run.

### Phase 9 — Evaluation *(2–3 days)*
**Objective:** A regression gate that catches quality drops before you ship a prompt change.
**Build:**
- `evaluation/golden_dataset.py` — 10–20 real PRs (use your Phase 8 test set) with hand-labeled expected findings
- `evaluation/judge.py` — an LLM-as-judge that scores a new run's findings against the golden labels (precision/recall-style, or a rubric score)
- `evaluation/regression_gate.py` — a script that runs the full pipeline against the golden set and fails (non-zero exit) if the score drops below a threshold vs. the last known-good run
**Done when:** Deliberately break a prompt (e.g., remove the security agent's rationale requirement) and confirm `regression_gate.py` catches the quality drop and fails.

### Phase 18 — CI/CD for AI *(1 day)*
**Objective:** The regression gate runs automatically, not manually.
**Build:** `.github/workflows/ci.yml` — runs `regression_gate.py` on every push to a prompts/ or agents/ file; prompt files versioned by git history (already true if you're committing them).
**Done when:** Push a prompt change to a branch, open a PR against your own repo, and watch the CI check fail/pass based on the eval score.

### Phase 19 — Human-in-the-Loop *(2 days)*
**Objective:** Low-confidence or CRITICAL reviews route to a real approval queue instead of auto-posting.
**Build:**
- `hitl/queue.py` — insert into `hitl_reviews` when the aggregator's gate (Phase 8) decides not to auto-post
- `hitl/escalation.py` — CRITICAL findings always land here regardless of confidence
- `hitl/feedback.py`, `hitl/dispute.py` — endpoints for a human to approve/edit/reject a finding, writing to `hitl_feedback`
- `api/hitl_router.py` — the API surface for the above
**Done when:** A deliberately low-confidence run stops at the queue instead of posting to GitHub; approving it from the API then posts the review; the `hitl_feedback` row for a disputed finding is queryable and linked back to the original `finding_records` row.

### Phase 2 & 17 — Frontend + Developer Experience *(3–4 days, can run in parallel with backend work)*
**Objective:** A dashboard that reads (not writes) the system — reviews, HITL queue, trace viewer, cost.
**Build:** Next.js app in `frontend/`:
- Review list + detail view (reads `api/reviews.py`)
- HITL approval queue UI (reads/writes `api/hitl_router.py`)
- Trace viewer — one page, one review, its full `agent_events` timeline rendered as a simple waterfall
- Economics page — reads `agent_health_1m`/`pr_cost_hourly` via `economics/cost_repository.py`
**Done when:** You can open the dashboard, see a real review that ran end-to-end, click into its trace, and see cost/latency broken down per agent — without touching a database client.

### Phase 20 — Continuous Learning *(0.5–1 day, optional depth)*
**Objective:** A drift signal, not full retraining — this phase is about detecting decay, not fixing it automatically.
**Build:** A scheduled query (cron or simple script) against `agent_health_1m.rejection_rate` per agent; alert (log/email/Slack — pick the cheapest) if any agent's rejection rate trends upward over a rolling window.
**Done when:** Manually inject a batch of `hitl_feedback` rows marked `disputed` for one agent and confirm the drift query flags that agent.

---

## 7. Environment variables checklist

```
TIGER_DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/DB?sslmode=require
REDIS_URL=redis://localhost:6379
OPENAI_API_KEY=sk-...
GITHUB_APP_ID=...
GITHUB_WEBHOOK_SECRET=...
GITHUB_PRIVATE_KEY_PATH=...
DAILY_BUDGET_USD=5.00
CONFIDENCE_THRESHOLD=0.75
```

---

## 8. Effort summary against your placement-prep calendar

| Block | Phases | Est. days (part-time) |
|---|---|---|
| Foundations | 0, 1, 13, 3 | 4 |
| Orchestration core | 4, 14, 6, 5, 7 | 9 |
| The core deliverable | 8 | 4 |
| Trust layer | 10, 15, 11, 12, 16 | 6 |
| Quality + shipping | 9, 18, 19 | 5 |
| Surfacing it | 2, 17, 20 | 4–5 |
| **Total** | all 20 | **~32 days part-time ≈ 6–8 weeks** at a realistic pace around coursework/interview prep |

**Sequencing advice given your other two projects:** treat Phases 0–8 (through the working multi-agent core) as the must-finish block — that alone is a legitimate, demo-able project and covers every concept you listed (LangGraph, RAG, multi-agent). Phases 9–20 (eval, HITL, observability polish, dashboard) are what take it from "working demo" to "production-grade system" in an interview narrative — valuable, but treat them as the stretch goal you finish if time allows before you need to freeze your portfolio for applications.
