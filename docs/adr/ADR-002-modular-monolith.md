# ADR-002 — Modular Monolith, Not Microservices

**Status:** Accepted
**Date:** 2026-07-23
**Phase:** 1 — System Architecture
**References:** ARCHITECTURE.md §4.2, §3.1 (interrogating question), §3.7

## Context

The system has clearly separable concerns — ingress, orchestration, four specialist agents, retrieval, observability, HITL, economics — the kind of list that invites "each of these should be its own service." But at this stage there is one deployable, one team, and no measured load that requires splitting anything.

## Decision

Build one process with **23 internal modules** and an **inward-only dependency rule**: `core/` depends on nothing; every outer module may depend inward (toward `core/` and shared models) but never sideways into another outer module's internals; `observability/` is cross-cutting and injected as middleware rather than sitting in the dependency chain at all. Deleting any single outer module should still leave the rest compiling.

Modules: `agents`, `api`, `auth`, `core`, `data`, `database`, `economics`, `evaluation`, `hitl`, `integrations`, `job_queue`, `memory`, `models`, `observability`, `orchestrator`, `prompts`, `reliability`, `security`, `tools`, `webhook_receiver`, plus `migrations` and `frontend` as top-level siblings.

## Rationale

A microservice split is a real cost paid up front — network calls where a function call would do, separate deploys, separate schemas or careful API contracts between them — and it only pays for itself once a genuine scaling or team-boundary pressure exists. We don't have that pressure yet: one webhook, one orchestrator, four agents, one database. Splitting now would mean guessing at service boundaries before the workload has told us where the real seams are.

The inward-only dependency rule buys most of what a service split buys — modules can be reasoned about, tested, and eventually extracted in isolation — without paying the deployment and network cost today. If `agents/` never imports from `api/`, and `core/` never imports from anything, then splitting `agents/` into its own service later is a mechanical extraction, not a redesign.

`observability/` is deliberately not part of the inward chain: every module needs to emit events, so it is injected as middleware/cross-cutting rather than becoming a dependency every other module points at.

## Consequences

- Enforced by convention and code review at this stage: `backend/core/` must have zero imports from any other backend module, for the life of the build. This is checked by inspection each phase, not (yet) by a lint rule.
- A single FastAPI process and a single ARQ worker pool serve all traffic. Both are visible bottlenecks named in ARCHITECTURE §3.1: queue depth outgrowing the worker drain rate, or the webhook endpoint itself becoming a bottleneck at high PR volume.
- Because the module boundaries are already enforced, extracting a service later (e.g., the webhook receiver as a stateless ingress service, or the orchestrator as its own worker pool) changes deployment topology, not module internals.

## Revisit when

- The interrogating question from ARCHITECTURE §3.1 stops being hypothetical: sustained load measured (not anticipated) at a scale where the single ingress endpoint or the single worker pool is the demonstrated bottleneck. At that point, extract the webhook receiver and the orchestrator worker pool as separate services — the module boundaries already drawn here are what makes that extraction mechanical instead of a rewrite.
