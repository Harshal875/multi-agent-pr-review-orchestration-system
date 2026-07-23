# Designing an AI Pull-Request Review Agent — An Architecture Study

*Published July 22, 2026 · A first-principles derivation*
*Lenses: design template, agentic failure modes, one-database data spine*
*Grounded in the `ai-pr-review-agent` codebase · Built by Ayush Singh*

> A PR review agent is not a linter with an LLM bolted on. It is a fan-out of specialist reasoners over a diff, grounded in retrieved codebase context, with every action written to one time-ordered spine. This study derives that architecture from first principles.

**How to read this.** The sections below do not start with boxes and arrows. They start with questions — why an automated reviewer exists at all, how a senior engineer actually reviews, what kinds of knowledge a review needs. Each step ends with two things: **the question we ask** (a reusable thinking move that generalizes to other systems) and **carry into the architecture** (a concrete component, field, or rule). By the end, those carried pieces assemble into the whole design.

---

## Part 0 / The Thinking Mindset — The lens before the system

Before any code-review-specific design: four reusable instruments. A template that turns any messy workflow into an agentic system. A catalog of the ways agentic systems fail. A spectrum for deciding how much human stays in the loop. And a lifecycle that scaffolds the whole build.

> **Driving question:** How do you design an agent that reviews code as well as a careful senior engineer — and proves its work?

### 0.1 The Universal Design Template

Five moves turn any workflow, in any domain, into an agentic design.

**Move 1. Map the mess** — Document what actually happens today, not the process document nobody follows. Record the trigger, every step in the middle, the deliverable at the end, where the human is genuinely thinking vs. mechanically shuffling information, and where it breaks.

**Move 2. Name the trigger and the output** — Every automatable workflow has a precise trigger and a precise output. "A claim email arrives at claims@company.com," not "claims come in." If you cannot state both in one sentence each, you have not looked closely enough.

**Move 3. Assign components** — Detecting that work is needed is a *trigger*. Fetching data is a *tool/API*. Reading unstructured input or writing language is an *LLM*. A score or classification that must be identical every time is *deterministic ML*. A judgment with legal, financial, or safety stakes is a *human checkpoint*.

> Most common mistake: assigning an LLM to a step that should be deterministic. If the output must be identical every time given the same input, it must be deterministic. If the output is language and some variation is acceptable, it can be an LLM.

**Move 4. Choose autonomy** — How much the system does on its own vs. defers to a human. Not a default — a design choice driven by the consequence of error (see 0.3).

**Move 5. Design for failure** — Walk each component and break it on purpose. The system should degrade to slower-but-correct, never fast-but-wrong. The worst failure mode is a wrong answer delivered with confidence.

### 0.2 The Failure Modes Catalog

Every agentic system fails. The only question is whether it fails safely.

| Mode | What happens | Design against it with |
|---|---|---|
| Hallucination in a critical path | The model states something plausible but false in a place that matters | Citation requirement, fact-check layer, human review for high stakes, prompts that permit "I don't know" |
| Model drift | Accurate at deployment, degrades as the world changes | Monitoring dashboard, alert thresholds, periodic retraining, rules fallback |
| Tool / API timeout | An external system stalls and the pipeline hangs | Timeout-and-retry, graceful degradation on partial data, circuit breaker |
| Feedback-loop poisoning | Bad feedback is stored and degrades future behavior | Minimum evidence threshold, audit for protected proxies, decay on old feedback, human reset |
| Orchestration deadlock | Two parallel steps wait on each other; a merge never receives input | Timeouts on every step, health checks, idempotent operations, dead-letter queue |
| Human bottleneck | Auto-handling works, but the escalation queue grows faster than humans clear it | Escalation-rate monitoring, queue prioritization, threshold tuning, honest capacity planning |
| The "almost-right" problem | Output 90% correct, 10% subtly wrong, reviewers drift into complacency | Rotate reviewers, flag low-confidence outputs, random audits, inject known-wrong inputs to test vigilance |

### 0.3 The Human-in-the-Loop Spectrum

Not every system needs the same level of human involvement. The right level is a design choice.

| Level | Description | Where it fits |
|---|---|---|
| Full automation | System handles everything; human samples periodically | Routine, low-stakes, reversible work |
| Human reviews output | System produces, human verifies before it goes out | Drafts with reputational stakes |
| Human handles exceptions | System auto-handles easy cases, human sees the hard ones | Anomalies, low-confidence cases, escalations |
| Human decides, system prepares | System gathers all context, human makes the call | High-consequence, irreversible decisions |
| Full human with AI assist | Human does the work, system helps at specific steps | Early-stage, low-trust, or creative work |

Three factors choose the level: **consequence of error** (a wrong style comment is annoying; a missed SQL injection is dangerous), **reversibility** (an auto-posted review can be disputed and removed; a merged migration cannot be un-run easily), and **system maturity** (new systems need more oversight; proven ones earn less).

> Start with more human involvement than you think you need. Reduce it as the system proves itself. It is far easier to remove a checkpoint than to recover from removing it too early.

### 0.4 The 20-Phase Production Lens

Beginners design the happy path: receive, reason, respond. Senior engineers add the back half: observe, secure, recover, govern, optimize, learn.

| Phase | Concern |
|---|---|
| 0 Cognitive Design | What thinking should the system perform; autonomy level; HITL boundaries |
| 1 System Architecture | Boundaries, style, module graph, ADRs |
| 2 Frontend | Dashboard shell, streaming, agent transparency |
| 3 Backend & API | FastAPI, webhook, idempotency, state |
| 4 Workflow Orchestration | Topology, checkpointing, parallel fan-out |
| 5 LLM & Reasoning | Model routing, structured output, prompt registry |
| 6 Memory Architecture | RAG, hybrid retrieval, the vector lane |
| 7 Tooling & Sandboxing | Tool registry, permissions, Docker isolation |
| 8 Multi-Agent Systems | Roles, contracts, the aggregator |
| 9 Evaluation | Golden datasets, LLM-as-judge, regression gates |
| 10 Observability | Traces, token cost, alerts — the events spine |
| 11 Security | Threat model, prompt injection, RBAC, Zero Trust |
| 12 Reliability | Circuit breakers, idempotency, checkpointing |
| 13 Infrastructure | Containers, queues, data-layer provisioning |
| 14 Data Engineering | Ingestion pipelines, schema, encoding |
| 15 Governance | Audit trails, explainability, residency |
| 16 Economics | Token cost attribution, budget caps, routing efficiency |
| 17 Developer Experience | Prompt playground, trace viewer, replay |
| 18 CI/CD for AI | Prompt versioning, eval gates, canary releases |
| 19 Human-in-the-Loop | Approval workflows, escalation, dispute |
| 20 Continuous Learning | Feedback loops, drift detection |

**Part 0 — carry forward:** A five-move design template · a seven-mode failure catalog · a five-level HITL spectrum · a twenty-phase lifecycle.

---

## Part I / First Principles — Why automated review exists, before how it works

> **Level-zero question:** A developer opens a pull request. A webhook fires. What, exactly, should happen next — and why?

### L0 — Why This System Exists

Without automated review, every PR waits on a senior engineer's attention — the scarce resource: slow (PRs queue for hours or days), inconsistent (the same issue caught Monday, missed Friday), and fatigued (the tenth review of the day is not the first). The cost is not "no review happens" — it's that the most expensive, most valuable human time is spent on largely mechanical pattern recognition.

**An automated reviewer exists to reclaim senior-reviewer attention by automating the mechanical part of review, so the human is spent only where judgment is genuinely required.**

> A review agent is not a replacement for human judgment. It is a way to spend human judgment only where it is actually scarce.

Hold onto the word **selective**. The system should not flood the PR with every conceivable comment — it should surface high-value findings and route uncertain ones to a human.

- **Question we ask:** Why does this system exist at all, and what single cost or loss does it remove?
- **Carry forward:** A selective, high-value posture — optimize for surfacing findings worth a senior's attention, not maximal output.

### L1 — Start From How a Senior Reviews

Watch a senior engineer review closely. They do four things a naive single-prompt reviewer does not:

- **Bring codebase context** — they know this function overrides a base class, this pattern contradicts a past decision.
- **Reason across separate concerns** — a security pass, a correctness pass, a test-coverage pass, a documentation pass, each a different mindset.
- **Stay skeptical** — they do not assume the diff is correct.
- **Cite evidence** — "this is wrong because line 40 can be null here," not "looks off."

Translating: "brings context" → retrieval. "Reasons across concerns" → not one reasoner but several. "Stays skeptical" / "cites evidence" → every finding needs a rationale and a confidence.

| Concern | Question it asks |
|---|---|
| Security | "Could this be exploited?" — injection risks, secrets in code, auth bypasses, unsafe deserialization |
| Quality | "Is the logic right?" — correctness bugs, logic errors, code smells, unnecessary complexity |
| Tests | "What's untested?" — missing cases, untested edge conditions, brittle assertions, coverage gaps |
| Docs | "Will the next reader understand?" — missing docstrings, outdated comments, undocumented public APIs |

- **Question we ask:** Is there a mature system — human or engineered — that already solved a version of this, and what structure can I borrow?
- **Carry forward:** Four specialist concerns — security, quality, tests, docs — the seed of the multi-agent design.

### L2 — Map the Mess

A developer pushes a commit, opens a PR, waits. A reviewer eventually notices, context-switches, reads the diff, sometimes pulls the branch to run it, leaves comments, developer iterates. The waiting and context-switching are pure cost.

**Trigger:** GitHub emits a `pull_request` webhook when a PR is opened or updated.
**Output:** A single structured review, posted back to that PR, with findings attached to specific files and lines.

The word **structured** matters — a review is a list of findings, each with a shape:

- `agent_type` — which concern raised this (security, quality, tests, docs)
- `severity` + `category` — CRITICAL down to INFO; a category like "injection" or "missing-test"
- `file` / `line` — the exact location, so the finding posts inline
- `confidence` + `rationale` — how sure, and why (drives the human-review gate and makes findings auditable)

- **Question we ask:** What is the precise trigger, the precise output, and the shape of the object that travels between components?
- **Carry forward:** An ingress trigger (GitHub webhook) and a structured **Finding** contract: `agent_type`, `severity`, `category`, `file/line`, `confidence`, `rationale`.

### L3 — Industry-Standard Thinking

Four rungs of review automation, and why each falls short of the next:

| Rung | What it does | Why it falls short |
|---|---|---|
| Linters | Pattern-match syntax and style rules | No semantics — cannot reason about intent, logic, or test meaning |
| Static analysis | Data-flow and type analysis | High false-positive rate; no codebase-wide judgment |
| Single-LLM review | One prompt judges the whole diff | One mindset for four concerns; no grounding; hallucinates with confidence; no audit |
| **Agentic fan-out** | Specialist agents, each grounded, each skeptical, merged by an aggregator | The rung this design stands on — demands orchestration, retrieval, a proof layer |

The single-LLM rung is seductive because it works in a demo — but it collapses four concerns into one prompt, doing each shallowly, with no grounding, auditability, or trust.

- **Question we ask:** What does the mature version of this decompose into, beyond the happy path the demo shows?
- **Carry forward:** Parallel specialists, not a single prompt — the agentic fan-out, implying an orchestrator and an aggregator.

### L4 — The Grounding Problem

An LLM handed a diff in isolation knows *what* changed but not *what it changed within*. It cannot know a function overrides a base method, or that a pattern was deliberately rejected before. Under uncertainty, it guesses confidently — hallucination in a critical path.

The fix cannot be "the full repository in the prompt" — that exhausts the context window and most of it is irrelevant to a given diff. The answer is **retrieval**: for each diff, fetch only the most relevant slices of the codebase.

> An ungrounded reviewer is a confident stranger. A grounded one is a colleague who has read the code.

- **Question we ask:** What does this reasoner need to know that is not in front of it, and how do we put exactly that — and only that — in front of it?
- **Carry forward:** A retrieval layer (RAG) — every specialist reasons over diff-plus-context, never the diff alone.

### L5 — What Kinds of Memory Does Review Need?

Context is not one kind of thing. A senior reviewer draws on several kinds of memory, each with a different shape and access pattern.

| Kind of memory | What it holds for review | The data shape it wants |
|---|---|---|
| Semantic | The codebase — functions, classes, modules, ADRs, conventions, as meaning | Vector embeddings + similarity search |
| Episodic | Past reviews — what was flagged, disputed, merged | Time-stamped relational rows |
| Procedural | How this team likes things done — conventions, ADRs, severity policy | Small, high-priority, almost always loaded |

- **Question we ask:** What distinct kinds of state does this system hold, and does each kind want a different shape rather than one undifferentiated bucket?
- **Carry forward:** Three data shapes — vector/ANN (semantic), relational (episodic), small structured (procedural).

### L6 — Trust and Proof

A finding is posted: "this endpoint is vulnerable to SQL injection, confidence 0.6." A developer disputes it. Without a record of why the finding was raised — which context was retrieved, which prompt version ran, what the model returned, what it cost — the system cannot defend itself, cannot be debugged, cannot improve.

Trust requires a third thing beyond reasoning and grounding: **proof**. Every action — every span, LLM call, tool call, decision — recorded as an event, in time order, durably. One stream of events powers three things at once: a **trace viewer**, an **audit trail**, and a **cost ledger**.

> If the system cannot show its work, it has not done the work.

- **Question we ask:** When this system produces an output, can it prove how it got there — and what did that cost?
- **Carry forward:** An events spine — every action a time-ordered event row, feeding trace, audit, and cost ledger. A fourth data need, time-series in shape.

### L7 — When Not to Trust It

Apply the 0.3 HITL spectrum. The agent knows roughly when it is unsure — the confidence field from L2/L6. The design decision is what to do with that knowledge: a **confidence-weighted gate**.

| Condition | Action | Which 0.3 factor |
|---|---|---|
| High confidence, no CRITICAL | Post automatically | Maturity earns autonomy |
| Confidence below threshold | Route to human approval queue | Uncertainty, defer judgment |
| Any CRITICAL finding | Escalate, page a human | Consequence of error too high |
| Developer disputes a posted finding | Route to dispute, record feedback | Reversibility, learning loop |

This places the system at "human handles exceptions," with an escalation path to "human decides."

- **Question we ask:** Where on the human-involvement spectrum does this system belong, and what signal moves a given case up or down it?
- **Carry forward:** A confidence-weighted HITL gate — below threshold or any CRITICAL finding routes to a human approval queue instead of posting. Implies queue and feedback tables.

### L8 — Failure Modes, Applied

Run the 0.2 catalog directly against code review.

| General failure (0.2) | In code review it looks like | Defense |
|---|---|---|
| Hallucination in critical path | A finding about code the agent never saw | Grounding (L4) + rationale + confidence (L2) |
| Tool / API timeout | LLM provider or GitHub API stalls | Retries with backoff, circuit breakers |
| Orchestration deadlock | The aggregator waits forever on a hung agent | Timeouts on every node, dead-letter handling |
| The "almost-right" problem | A finding 90% right but subtly misattributed | Dedup across agents, confidence threshold, HITL (L7) |
| Human bottleneck | The approval queue grows faster than reviewers clear it | Escalation-rate monitoring on the events spine (L6) |
| Feedback-loop poisoning | The agent "learns" a wrong preference from a few disputes | Minimum evidence threshold before acting on feedback |
| Idempotency gap | A retried webhook posts the same review twice | Idempotency key at ingress, dedup before posting |

- **Question we ask:** For each component, what happens when it fails, and does the system degrade to slower-but-correct rather than fast-but-wrong?
- **Carry forward:** A reliability layer — retries, circuit breakers, timeouts, idempotency at ingress, dedup at the aggregator.

### L9 — The Mental Model

A pull request triggers the work (L2). It is enqueued, not handled inline, decoupling ingress from processing (L2, L8). An orchestrator fans the work out to four specialists — security, quality, tests, docs (L1, L3) — running in parallel. Each specialist is grounded by retrieval over the codebase (L4). The codebase, past reviews, and conventions are three kinds of memory, three data shapes (L5). Each specialist returns structured findings with confidence and rationale (L2). An aggregator merges and deduplicates them, computes an overall confidence, and applies the HITL gate (L7). Every action is written to an events spine (L6). A reliability layer (L8) keeps each step degrading to slower-but-correct.

**Open question carried to Part II:** how many databases does this need? The naive answer is three durable stores (memory, truth, time). Part II interrogates that answer and arrives at one.

**Part I — Running ledger**

| # | Carried piece |
|---|---|
| L0 | A selective, high-value posture |
| L1 | Four specialist concerns: security, quality, tests, docs |
| L2 | Ingress trigger + the Finding contract with confidence and rationale |
| L3 | Parallel specialists, not a single prompt — the agentic fan-out |
| L4 | A retrieval layer: ground every specialist in the codebase |
| L5 | Three data shapes: vector, relational, structured |
| L6 | An events spine: every action a time-ordered row |
| L7 | A confidence-weighted HITL gate |
| L8 | A reliability layer: retries, circuit breakers, idempotency, dedup |
| L9 | The assembled mental model |

---

## Part II / From Principles to Data — Why one database, not three

> **Thesis of ADR-003:** Most AI systems split memory, truth, and time across separate databases. What if one is enough — and clearer?

### 2.1 Three Data Shapes, One Reflex

Three data shapes: **memory** (code chunks, past reviews, conventions), **truth** (review row, findings, GitHub review ID, human decisions), **time** (every span, LLM call, tool call, cost, latency, decision in order).

The reflexive answer maps each shape to a purpose-built store:

| Data shape | Reflexive store | What it holds |
|---|---|---|
| Memory | Qdrant | Embedded code chunks for semantic retrieval |
| Truth | Postgres | Reviews, findings, HITL rows, GitHub IDs |
| Time | Time-series DB | Spans, LLM calls, tool calls, cost, latency |

That sounds clean until: *"For this PR, what code did we retrieve, what review did we produce, which model calls made it expensive?"* With three stores, the app queries three systems and stitches the answer together in application code — more connection pools, more backups, more failure modes, no simple joins.

- **Question we ask:** Can we keep the three shapes, but not split them across three durable databases?
- **Carry forward:** Three shapes, one reflex. Separate databases are only an implementation choice.

### 2.2 One Store, Not Three

**Tiger Cloud is Postgres with the missing powers added** — a managed Postgres-compatible database with extensions for AI memory and time-series events.

**1. Vector search for memory (`pgvector`)** — every file gets turned into an embedding (a list of numbers representing meaning). `pgvector` stores that list in a real Postgres column (`code_chunks.embedding`). A new diff is embedded the same way and compared for nearest neighbors.

**2. `pgvectorscale` and DiskANN** — the fast index on top of `pgvector`. DiskANN keeps more of the search structure on disk/SSD instead of RAM, so search stays fast at millions of code chunks without a huge RAM bill.

**3. Time-series storage (hypertables)** — `agent_events` is naturally time-ordered. A **hypertable** partitions it into time-chunks internally while looking like one normal table, so recent queries touch only recent chunks.

**4. Continuous aggregates** — a dashboard shouldn't scan raw events from scratch on every load. A continuous aggregate is a summary table Tiger keeps updated (cost per minute, p95 latency, token totals) so a BudgetGuard can check spend cheaply before every LLM call.

That gives one store with three lanes inside it: one durable database, one backup story, one place to query, one PR identity connecting memory, truth, and time.

> **Redis stays** — the job queue is still Redis + ARQ. Queue data is short-lived and high-churn; it doesn't need vector search or dashboard rollups. "One database" means one durable data spine, not forcing every workload into SQL.

**Diagram — the collapse:**
```
BEFORE (the reflex)
  Vector DB (Qdrant)  +  Time-series DB  +  Postgres (Neon)
                     ↓ collapse ↓
AFTER (one store)
  Tiger Cloud · TimescaleDB (Postgres-compatible)
   ├─ VECTOR: pgvectorscale/DiskANN → code_chunks (256-dim)
   ├─ EVENTS: hypertables → agent_events (partitioned by 1 day)
   └─ ROLLUPS: continuous aggregates → agent_health_1m, pr_cost_hourly
```

- **Question we ask:** When I choose one database, am I simplifying the product, or hiding a workload the database cannot actually handle?
- **Carry forward:** One Postgres-compatible data spine — memory (pgvector/pgvectorscale), time (hypertables + continuous aggregates), truth (normal relational tables). Redis stays for the queue.

### 2.3 The Three Lanes, in Real Schema

**Lane 1 — Memory: `code_chunks`.** Replaces a Qdrant collection. Ingestion chunks repo files, embeds each chunk, writes here; retrieval searches it for code similar to the PR diff. Combines a DiskANN vector index (`vector_cosine_ops`) with a generated `tsvector` column + GIN index for full-text search — vector search catches meaning, full-text search catches exact names (function names, error codes, config keys); results are merged.

**Lane 2 — Time: `agent_events`.** An append-only row per action: span starts/ends, LLM calls, tool calls, decisions, escalations, cost, latency, payload. Built as a hypertable partitioned by day.

**Lane 3 — Rollups.** Continuous aggregates `agent_health_1m` (cost/latency/rejection-rate per agent per minute) and `pr_cost_hourly` (per-PR cost and token rollup) — precomputed so the dashboard never scans raw events.

**Truth lane** — deliberately ordinary relational tables: `pr_review_records` (one row per review), `finding_records` (one row per finding), `hitl_reviews` (human review state), `hitl_feedback` (human feedback). Normal relational data, normal shape.

> Mental model: memory is `code_chunks`, truth is the review tables, time is `agent_events`. One PR ties them together.

### 2.4 Why Tiger Cloud Beats the Split (ADR-003)

- **vs. plain Postgres** — fine for review rows/findings, not enough alone for fast vector search over millions of embeddings or efficient time-series rollups.
- **vs. Qdrant** — vector search isn't the only question asked; retrieval needs vector similarity *plus* repo filters, freshness, exact-identifier matching, review records, cost records, audit history, all living beside each other.
- **Why DiskANN matters** — keeps more of the search graph on SSD instead of RAM, making large vector memory realistic rather than toy-scale.
- **Why hypertables matter** — dashboards ask recent-time questions; a hypertable partitions by time so recent queries touch recent chunks, not the whole history.
- **Why continuous aggregates matter** — the app reads precomputed summaries instead of recomputing "daily spend" from millions of raw rows every page load.

**Alternatives considered and rejected:**

| Option | Rejected because |
|---|---|
| Keep Qdrant + Postgres | Works, but splits memory from review truth and audit history |
| Plain Postgres only | Good for truth, weak for large vector memory and time-series rollups |
| Add ClickHouse for events | Powerful, but another durable store, connection, schema, failure mode |
| Add Jaeger/Tempo for traces | Useful for infra tracing, but puts the product audit trail outside the product database |

**Trade-offs accepted:** Tiger Cloud is a managed service (accepted because it replaces multiple stores and eases operations); two access styles — SQLAlchemy for normal relational work, asyncpg for hot paths like event inserts and chunk upserts; Redis still exists as a queue/cache, not the durable spine.

- **Question we ask:** When I choose one database, am I simplifying the product, or hiding a workload the database cannot actually handle?
- **Carry forward:** A simpler single spine that keeps memory, truth, and time in one Postgres-compatible store while giving each lane the index/table shape it needs.

---

## Part III / The Architecture, Assembled — Now, and only now, the boxes

Every box below was earned in Parts I and II.

### 3.1 Ingress & the Queue

*From L2 (ingress trigger) and L8 (decoupling):* a GitHub webhook arrives, is validated, and is enqueued — never handled inline.

The ingress handler does exactly three things: verifies the GitHub HMAC-SHA256 signature (rejecting forgeries before any work); checks the idempotency key (the `X-GitHub-Delivery` UUID) so a retried delivery is dropped, not re-reviewed (the L8 idempotency defense); enqueues the job to Redis + ARQ and returns 200 immediately. GitHub expects a fast acknowledgment; heavy work happens asynchronously in an ARQ worker.

> The queue decouples ingress from review. A slow LLM provider or crashed orchestrator can never make the webhook endpoint time out. This is a correctness property, not just performance.

**PR lifecycle:** `GitHub PR → INGRESS (HMAC verify, idempotency) → 200 OK (ack fast) → enqueue(review_job) → Redis/ARQ queue → ORCHESTRATOR (LangGraph fan-out) → HITL? (confidence gate) → post_to_github`

> **Interrogating question:** Where does this break at 10,000 PRs per minute? Queue depth outgrows worker drain rate; the single ARQ worker becomes the bottleneck. The modular-monolith answer (ADR-002): extract the webhook receiver as a stateless ingress service and the orchestrator as a separate worker pool — when the trigger is measured, not anticipated.

### 3.2 The Orchestrator

*From L3 (parallel-specialists fan-out):* the orchestrator is a graph, not a pipeline. Nodes run simultaneously; state is checkpointed between them.

**LangGraph** defines the workflow as a directed graph of nodes and edges. Parallel fan-out — running the four specialists at once — is first-class via the **Send API**. A typed state object flows through the graph; LangGraph checkpoints that state to Redis at each node boundary, so a worker crash mid-review resumes from the last completed node rather than restarting. The checkpoint store is the same Redis the queue uses.

Code layout — `backend/orchestrator/`: `graph.py` (wires the `StateGraph` + `Send` fan-out), `state.py` (typed state), `nodes.py` (`build_context`, the four specialist nodes, `aggregate`), `langgraph_engine.py` (implements the engine interface). The aggregator node runs only after all four specialist nodes complete — the graph encodes that join, not hand-orchestration. This is the L8 orchestration-deadlock defense: every node has a timeout, so the join cannot hang forever on one stalled agent.

### 3.3 Trade-off: LangGraph vs Temporal (ADR-001)

**The need:** coordinate four parallel sub-agents, persist workflow state across steps so a crash doesn't lose work, handle retries cleanly when an LLM or tool call fails.

| | LangGraph (chosen) | Temporal |
|---|---|---|
| Where it runs | Inside our Python process — zero extra infra | A separate server plus separate worker processes |
| Parallel fan-out | First-class via the `Send` API | Supported, but heavier to express |
| Checkpointing | To the same Redis we already run for the queue | Durable, built-in, very strong guarantees |
| LLM integration | Tight tool-calling integration; fast local iteration | Generic; not LLM-specific |
| Maturity / scale | Newer; unproven at thousands of concurrent workflows | Battle-hardened (Uber, Netflix); excellent at scale |
| Operational cost | None beyond the app | Meaningful ops overhead before we understand our workflow shapes |

**Decision:** use LangGraph for Phases 1–12. Made safe by a single abstract interface — `backend/core/workflow_engine.py` — with `run(workflow_id, input)`, `resume(workflow_id, state)`, `get_state(workflow_id)`. The LangGraph implementation lives in `backend/orchestrator/langgraph_engine.py`. All orchestrator code imports from `core.workflow_engine`, never from LangGraph directly. If scale later demands Temporal, write a Temporal implementation of the same interface and swap it in — nothing else in the codebase changes.

> Revisit if sustained concurrent workflows exceed 50/minute, cross-service coordination is needed, or Redis checkpointing proves insufficient against data loss.

- **Question we ask:** Can I make the cheaper decision now and hide the harder one behind an interface, so swapping it later changes one file, not the system?

### 3.4 Specialists & the Aggregator

*From L1 (four concerns) and L2 (the Finding contract):* four specialists run in parallel, each returning structured findings, merged by one aggregator.

The four specialists — security, quality, tests, docs — share a base shape in `backend/agents/base_agent.py` (BudgetGuard check, retrieval call, LLM call, event emission, error handling) and differ only in domain prompt and post-processing. Each returns a list of `Finding` objects (`agents/contracts.py`) matching the L2 contract: `agent_type`, `severity`, `category`, `summary`, `file_path`, `line_start`/`line_end`, `suggestion`, `confidence`, `rationale`.

The aggregator merges all four lists, deduplicates findings multiple agents raised on the same file/line (keeping the highest-confidence one, noting agreement), computes an `overall_confidence`, and applies the L7 HITL gate: post automatically when confident and free of CRITICAL findings, otherwise insert into the human approval queue.

**Fan-out diagram:** `ORCHESTRATOR (LangGraph Send API) → [security | quality | tests | docs] agents (parallel) → AGGREGATOR (merge + dedup, score + route) → HITL confidence gate → GitHub`

### 3.5 The Retrieval Path

*From L4 (grounding) and L5 (data shapes):* each specialist queries the vector lane for codebase context relevant to the diff. Retrieval is hybrid — vector and keyword in parallel.

`backend/memory/`: `tiger_client.py` (`TigerMemoryClient`), `embedder.py` (`text-embedding-3-large`, 256-dim), `context_retriever.py` (hybrid merge). Pure vector search finds meaning but misses exact identifiers; pure keyword search finds exact strings but misses semantic relevance. Runs both against `code_chunks`: DiskANN ANN search over the embeddings, and full-text search over the `content_tsv` GIN index. A hybrid merge fuses the two result sets by reciprocal rank fusion, returning the top-k chunks into the specialist's prompt. `repo_file_index` tracks freshness so ingestion only re-embeds changed files.

**Path diagram:** `PR diff → Embed (256-dim) → [DiskANN ANN search | FTS keyword GIN] (parallel, both against code_chunks · Tiger Cloud) → Hybrid merge (RRF · top-k) → Specialist agent prompt`

> **Interrogating question:** What happens when embeddings go stale — a function refactored but its chunk still describes the old version? `repo_file_index.last_indexed_at` drives incremental re-embedding; a unique index on `(repo, path, chunk_index)` lets upserts overwrite stale chunks. The real question: is a weekly full reindex cheaper than on-demand freshness? Depends on repo churn.

### 3.6 The Events Spine in Operation

*From L6 (trust and proof):* every action is one row in `agent_events`, and three consumers read that one table.

`backend/observability/`: `events.py`, `tracing.py`, `audit.py` — emits an event for every span, LLM call, tool call, decision, carrying the `span_id`/`parent_span` chain, cost, latency, confidence, outcome. The **trace viewer** reconstructs any review with `SELECT ... WHERE review_id = $1 ORDER BY ts`. The **audit trail** is the same append-only table, immutable by construction. The **cost ledger** reads the continuous aggregates — and so does the **BudgetGuard**, which reads the day's running cost from `agent_health_1m` at the top of every agent run and hard-blocks before any LLM call if the daily cap is exceeded (ADR-004). Continuous aggregates also surface drift: a rising `rejection_rate` per agent is the calibration signal for continuous learning.

**Diagram:** `agent_events (TimescaleDB hypertable, partitioned by 1 day) → [Trace Viewer | Audit Trail | Cost Ledger]` — three queries against one time-ordered spine, fed by span.start/end, llm.call, tool.call, decision.

### 3.7 The Full System

`GitHub PR → FastAPI Ingress (HMAC · idempotency) → Redis/ARQ queue → ARQ Worker (LangGraph engine: security | quality | tests | docs in parallel) → Aggregator (merge · dedup · score) → HITL gate (confidence) → post_to_github`, with `Tiger Cloud · TimescaleDB` (one managed Postgres: `pgvectorscale`/DiskANN `code_chunks`; `agent_events` hypertable partitioned 1-day; `agent_health_1m`/`pr_cost_hourly`) as the shared spine beneath every component, and a Next.js dashboard reading the continuous aggregates. Deployed on Railway.

**Part III — carry forward:** Ingress (HMAC + idempotency) and Redis/ARQ decoupling · LangGraph fan-out with Redis checkpointing behind `core/workflow_engine.py` · four specialists returning Findings merged and routed through the confidence gate · hybrid DiskANN + FTS retrieval and the `agent_events` spine, all on the one Tiger Cloud store from Part II.

---

## Part IV / The Implementation Plan — From design to code

### 4.1 The 20-Phase Build Roadmap

Each phase proves one thing, ends green, and has a written gate before the next starts. "Tiger" marks phases where Tiger Cloud is load-bearing.

| # | Phase | What it proves / its green gate | Tiger |
|---|---|---|---|
| 0 | Cognitive Design | Autonomy level and HITL boundaries decided and written | |
| 1 | System Architecture | Module graph and ADRs exist; dependency rule defined | |
| 2 | Frontend Engineering | Dashboard shell renders; streaming wired | |
| 3 | Backend & API | FastAPI up; webhook validates HMAC; idempotency holds | |
| 4 | Workflow Orchestration | LangGraph fans out to 4 nodes in parallel; checkpoints resume | |
| 5 | LLM & Reasoning | Model routing per agent; prompt registry versioned | |
| 6 | Memory Architecture | RAG on pgvectorscale; hybrid retrieval returns top-k | ✓ |
| 7 | Tooling & Sandboxing | Tool registry enforces scope; Docker sandbox isolates | |
| 8 | Multi-Agent Systems | 4 specialists + contracts + aggregator produce one review | |
| 9 | Evaluation | Golden dataset runs; LLM-as-judge scores; regression gate blocks | |
| 10 | Observability & Tracing | OTel spans land in the `agent_events` hypertable | ✓ |
| 11 | Security | Threat model written; RBAC enforced; audit trail immutable | |
| 12 | Reliability | Retries, circuit breakers, idempotency verified under fault injection | |
| 13 | Infrastructure | Tiger Cloud provisioned; Tiger MCP wired | ✓ |
| 14 | Data Engineering | Ingestion pipeline runs; hypertable schema designed and migrated | ✓ |
| 15 | Governance | Audit logs queryable; explainability per finding | |
| 16 | Economics & Cost Control | Per-agent cost via continuous aggregates; BudgetGuard hard-blocks | ✓ |
| 17 | Developer Experience | Prompt playground and trace viewer usable | |
| 18 | CI/CD for AI | Prompt versioning; eval gates; canary release path | |
| 19 | Human-in-the-Loop | Approval queue, escalation, dispute, feedback all wired | |
| 20 | Continuous Learning | Drift detection reads continuous aggregates | ✓ |

### 4.2 The Module Map

One process, 23 internal modules, inward-only dependencies (ADR-002). The dependency rule holds throughout: `core` depends on nothing; outer modules depend inward only; observability is cross-cutting, injected as middleware. You can delete any outer module and the inner ones still compile.

| Module | Files | Purpose |
|---|---|---|
| `agents/` | `base_agent`, `contracts`, `security_agent`, `quality_agent`, `test_agent`, `docs_agent` | The four specialists and their shared base + Finding contract |
| `api/` | `reviews`, `economics_router`, `hitl_router`, `queue`, `schemas` | REST endpoints for reviews, economics, HITL, queue status |
| `auth/` | `dependencies` | RBAC dependencies for FastAPI routes |
| `core/` | `workflow_engine`, `exceptions` | The abstract orchestration interface and shared exception types |
| `data/` | `ingestion`, `freshness` | Code-chunk ingestion pipeline and re-embed freshness tracking |
| `database/` | `postgres`, `models`, `repository` | Async engine + Tiger pool + `init_tiger_schema`; ORM models; repos |
| `economics/` | `cost_repository`, `budget`, `routing_advisor` | Reads aggregate views; BudgetGuard; model-routing advice |
| `evaluation/` | `golden_dataset`, `judge`, `regression_gate` | Golden PRs, LLM-as-judge, regression gate for CI |
| `hitl/` | `queue`, `escalation`, `feedback`, `dispute` | Approval queue, escalation engine, feedback capture, dispute API |
| `integrations/` | `github_client`, `github_models` | GitHub REST wrapper with retry; GitHub payload models |
| `job_queue/` | `arq_worker` | ARQ worker process consuming review jobs from Redis |
| `memory/` | `tiger_client`, `embedder`, `context_retriever`, `redis_client` | `TigerMemoryClient` (pgvectorscale + hybrid), embedding, retrieval, session cache. `qdrant_client` retired per ADR-003 |
| `models/` | `enums`, `findings`, `review`, `webhook` | Pydantic schemas: Finding, Review, WebhookEvent, enums |
| `observability/` | `events`, `tracing`, `audit`, `alerting`, `logging`, `workflow_context` | `emit_agent_event` → hypertable; OTel; audit; alerts; ContextVar |
| `orchestrator/` | `graph`, `nodes`, `state`, `langgraph_engine` | LangGraph StateGraph, node functions, typed state, engine impl |
| `prompts/` | `registry`, `templates/` | Prompt registry + versioned prompt files per agent |
| `reliability/` | `retry`, `circuit_breaker`, `idempotency`, `timeout` | The L8 reliability mechanics |
| `security/` | `threat_model`, `injection_guard`, `rbac`, `masking` | Threat model, prompt-injection guard, RBAC, secret masking |
| `tools/` | `tool_registry`, `model_router`, `llm_client`, `sandbox`, `capability_scope` | Tool catalog, model routing, LLM client, Docker sandbox, scoping |
| `webhook_receiver/` | `validator`, `parser`, `router` | HMAC validation, payload parsing, event routing to the queue |
| `migrations` | `scripts/migrations/2026-06-tiger-init.sql` | Idempotent schema DDL — the lanes and tables from Part II |
| `frontend/` | `src/app`, `components`, `lib` | Next.js: review dashboard, HITL queue, trace viewer, economics page reading continuous aggregates |

### 4.3 The Tiger Integration Plan (ADR-003)

Staged in four independently verifiable phases (greenfield — no live data to move, so no zero-downtime requirement):

| Phase | What happens | Verified by |
|---|---|---|
| A · Infra | Provision Tiger Cloud, run `2026-06-tiger-init.sql`, verify extensions (`timescaledb`, `vector`, `vectorscale`) | Extensions present; hypertable and aggregates listed |
| B · Events | Wire `emit_agent_event()` in the orchestrator nodes and the LLM client | Every span, llm.call, tool.call lands in `agent_events` |
| C · Memory | Retire `qdrant_client.py`; test hybrid retrieval end-to-end on `code_chunks` | DiskANN + FTS return top-k; recall verified |
| D · Dashboard | Wire the continuous-aggregate endpoints to the frontend economics page | Per-agent cost and p95 latency render from `agent_health_1m` |

---

## Closing — How to reuse this

The transferable framework — the "question we ask" moves, none of which mention code review:

1. Why does this system exist? Name the one scarcity it relieves, or do not build it.
2. What mature system already solved a version of this? Borrow its decomposition.
3. What is the precise trigger, output, and the object on the arrows? The contract matters more than the boxes.
4. What does the mature version decompose into? Find the hidden back half; stand on the highest rung you can afford.
5. What does this reasoner need that is not in front of it? Retrieve exactly that, and only that.
6. What distinct kinds of state, by access pattern? Kinds drive shapes; shapes drive stores.
7. Can it prove how it got there, and what it cost? Design the audit stream with the decision, not after.
8. Where on the autonomy spectrum, and what signal moves a case along it? Let the system earn trust case by case.
9. What happens when each box fails? Degrade to slower-but-correct, never fast-but-wrong.
10. Count the data shapes before the databases. One store until a shape proves it cannot live there.
11. Can the hard decision hide behind an interface? Make the cheap choice now; swap one file later.

> Design is not a parts list. It is a chain of questions, each one earning the next box. If a component cannot be traced back to a question you can defend, it is either missing a justification or it does not belong.

*ADR-001 (LangGraph vs Temporal) · ADR-002 (modular monolith) · ADR-003 (Tiger Cloud data layer) · ADR-004 (cost control) · Schema: `scripts/migrations/2026-06-tiger-init.sql`*
