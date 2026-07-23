# ADR-001 — Orchestration Engine: LangGraph vs. Temporal

**Status:** Accepted
**Date:** 2026-07-23
**Phase:** 1 — System Architecture
**References:** ARCHITECTURE.md §3.3, §L3, §L8

## Context

Four specialist agents must run in parallel against one PR diff, their combined state must survive a worker crash mid-review, and a failed LLM or tool call must retry cleanly without corrupting the rest of the run. Something has to coordinate that fan-out and own the state.

Two real options exist: **LangGraph**, a graph-based orchestration library that runs inside our own Python process, and **Temporal**, a durable-execution platform that runs as its own server plus separate worker processes.

## Decision

Use **LangGraph** for Phases 1–12, behind a narrow abstract interface (`backend/core/workflow_engine.py`: `run(workflow_id, input)`, `resume(workflow_id, state)`, `get_state(workflow_id)`). All orchestrator code depends on this interface, never on LangGraph directly; the concrete implementation lives in `backend/orchestrator/langgraph_engine.py`.

## Rationale

| Dimension | LangGraph | Temporal |
|---|---|---|
| Infrastructure | Runs inside our existing process — nothing new to deploy | A separate server and worker fleet to run and operate |
| Parallel fan-out | First-class (`Send` API) — exactly the four-way fan-out we need | Possible, but more code to express the same shape |
| Checkpointing | Piggybacks on the Redis we already run for the job queue | Durable and strong, but its own storage story |
| LLM fit | Built with tool-calling/agent loops in mind | General-purpose; no special LLM affordances |
| Maturity at scale | Newer, unproven past a few thousand concurrent workflows | Battle-tested at Uber/Netflix scale |
| Operational cost | Zero beyond the app itself | Real ops overhead, worth paying only once the workflow shapes are well understood |

At our current scale (a handful of PRs at a time, one process, one team), Temporal's durability guarantees are real but not yet the bottleneck — the bottleneck is building the four-agent fan-out at all. LangGraph gets us there with no new infrastructure and fast local iteration, which matters more while the workflow shape is still being figured out.

The risk of choosing LangGraph — that we outgrow it — is deliberately absorbed by the interface, not ignored. Nothing outside `orchestrator/langgraph_engine.py` and `core/workflow_engine.py` needs to know which engine is running. If Temporal is later warranted, we write a second implementation of the same three methods and swap it in; the specialist agents, the aggregator, and the API layer don't change.

## Consequences

- `backend/core/` must depend on nothing else — it defines the interface, not the implementation, so it stays swappable.
- The job queue's Redis instance doubles as the LangGraph checkpoint store. This is acceptable now; if checkpoint volume or durability requirements grow, that's a separate decision from the engine choice.
- Every orchestrator node needs its own timeout (Phase 12), because LangGraph does not give us Temporal's built-in retry/timeout guarantees for free.

## Revisit when

- Sustained concurrent workflows exceed roughly 50/minute.
- Cross-service coordination (beyond one Python process) becomes necessary.
- Redis-backed checkpointing proves insufficient against real data loss in practice.
