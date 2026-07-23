# ADR-000 — Cognitive Design: Autonomy Level and HITL Boundaries

**Status:** Accepted
**Date:** 2026-07-23
**Phase:** 0 — Cognitive Design
**Deciders:** Project owner
**References:** ARCHITECTURE.md §0.1–0.3 (design template, failure modes, HITL spectrum), §L0, §L2, §L6, §L7; ROADMAP.md Phase 0

---

## Context

Before any code exists, we decide *how much the system is trusted to act on its own* and *where a human must stay in the loop*. This is a design choice, not a default (ARCHITECTURE §0.1 Move 4). Getting it wrong in the trusting direction is expensive and hard to reverse: an auto-posted wrong review erodes developer trust in the whole system, and "it is far easier to remove a checkpoint than to recover from removing it too early" (§0.3).

The system's reason to exist is **selective**: reclaim scarce senior-reviewer attention by automating the mechanical part of review, surfacing only high-value findings and routing uncertain ones to a human (§L0). That posture drives every decision below.

## Decision

### 1. The four agent concerns

Review is decomposed into four specialist concerns, each a different reviewing mindset (§L1):

| Concern | Question it asks |
|---|---|
| **Security** | "Could this be exploited?" — injection, secrets, auth bypass, unsafe deserialization |
| **Quality** | "Is the logic right?" — correctness bugs, logic errors, code smells, needless complexity |
| **Tests** | "What's untested?" — missing cases, untested edges, brittle assertions, coverage gaps |
| **Docs** | "Will the next reader understand?" — missing docstrings, stale comments, undocumented public APIs |

These four, and only these four, are the concerns for the initial build. New concerns are added only with their own rationale.

### 2. Autonomy level

The system sits at **"human handles exceptions"** on the HITL spectrum (§0.3), with a defined escalation path to **"human decides, system prepares"** for high-consequence findings.

- Easy, confident, low-stakes cases are auto-handled (posted to the PR).
- Uncertain cases and high-consequence cases are routed to a human.

We deliberately start with *more* human involvement than a mature system would need, and reduce it only as the system earns trust case by case (§0.3, §L7).

### 3. The confidence-weighted HITL gate

The aggregator applies this gate after merging and deduplicating findings (§L7). The three factors from §0.3 — consequence of error, reversibility, system maturity — map directly to the rules:

| Condition | Action | Governing factor |
|---|---|---|
| Confidence ≥ threshold **and** no CRITICAL finding | Post automatically to the PR | Maturity earns autonomy |
| Confidence < threshold | Route to human approval queue | Uncertainty → defer judgment |
| **Any** CRITICAL finding (regardless of confidence) | Escalate; a human must review before posting | Consequence of error too high |
| Developer disputes a posted finding | Route to dispute flow; record feedback | Reversibility → learning loop |

### 4. The thresholds

| Parameter | Value | Notes |
|---|---|---|
| **Auto-post confidence threshold** | **0.75** | `overall_confidence` at or above this auto-posts (subject to the CRITICAL override). Sourced from `CONFIDENCE_THRESHOLD` env var (ROADMAP §7). |
| **Always-escalate severity** | **CRITICAL, always** | A CRITICAL finding forces human review even at confidence 1.0. Never auto-posted. |

The threshold lives in configuration (`CONFIDENCE_THRESHOLD=0.75`), not hardcoded, so it can be tuned as the system matures without a code change.

## Rationale (defensible out loud)

- **Why 0.75, not higher or lower?** It is a starting point chosen to be *conservative but not paralyzing*. Too high (e.g., 0.95) sends nearly everything to the human queue and recreates the bottleneck the system exists to remove (§L0). Too low auto-posts shaky findings and triggers the "almost-right" failure mode — output 90% right, 10% subtly wrong, reviewers drift into complacency (§0.2). 0.75 auto-posts findings the system is clearly confident about while defaulting uncertainty to a human. It is a config value precisely because the *right* number is learned from the rejection-rate signal over time, not known up front.
- **Why is CRITICAL an absolute override, decoupled from confidence?** Confidence measures *how sure* the agent is; severity measures *how bad it is if true*. A confidently-identified SQL injection is exactly the case where a human should look before it becomes a public comment — high consequence, and the confidence being high doesn't lower the stakes. Separating the two axes is the §0.3 "consequence of error" factor made concrete.
- **Why "human handles exceptions" and not full automation?** System maturity is zero at launch; the system has earned no trust yet. Starting conservative and removing checkpoints later is safe; the reverse is not (§0.3).
- **Why selective over exhaustive?** The scarce resource is senior attention (§L0). Flooding a PR with low-value comments spends that attention rather than saving it, and trains developers to ignore the bot.

## Consequences

- The aggregator (Phase 8) and the HITL queue (Phase 19) must implement this gate exactly; `hitl_reviews.reason` will record `low_confidence` vs `critical_finding` to match rows 2 and 3 above.
- `pr_review_records.status` carries `awaiting_human` for gated reviews, `posted` for auto-posted ones.
- The rising-`rejection_rate` signal from `agent_health_1m` (Phase 20) is the calibration input for revisiting the 0.75 threshold — this ADR is expected to be tuned, not frozen.
- Every finding carries `confidence` + `rationale` so the gate has a signal to act on and every decision is auditable (§L2, §L6).

## Revisit when

- Sustained data shows the human queue is clearing far faster than it fills (system has earned more autonomy → consider raising the auto-post rate / lowering reliance on the queue).
- `rejection_rate` for auto-posted findings climbs (threshold too low → raise it).
- A fifth review concern is genuinely needed (add it here with its own justification).
