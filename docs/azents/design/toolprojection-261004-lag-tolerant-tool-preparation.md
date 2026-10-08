---
title: "Lag-Tolerant Tool Preparation Design"
created: 2026-10-04
tags: [backend, engine, toolkit, performance, concurrency]
document_role: primary
document_type: design
snapshot_id: toolprojection-261004
---

# Lag-Tolerant Tool Preparation Design

## Design Authority

Revision: 1. [Requirements](../requirements/toolprojection-261004-lag-tolerant-tool-preparation.md) and [ADR](../adr/toolprojection-261004-lag-tolerant-tool-preparation.md) share snapshot `toolprojection-261004`.

- M1 (derived): independent completed read-only managers for saved tool snapshot and GitHub selection loads; `REQ-1`, `REQ-4`, `ADR-D1`. Existing write managers preserve mutation fencing.
- M2 (derived): completed retained Runtime/configuration/Project read operations and read-only Session binding projection; `REQ-2`, `REQ-4`, `ADR-D2`. Actual admission remains unchanged.
- M3 (derived): worktree create/remove visibility consumes retained evidence, active exact Agent Session and ready allocation descriptions; `REQ-3`, `REQ-4`, `ADR-D2`.
- M4 (required): deterministic absence/concurrency/admission verification and comparable latency observations; `REQ-5`.

## Design Approval

Mode: direct implementation of an explicitly requested technical phase. Decision owner: requester for the fixed lag-tolerant read/removal and existing side-effect contract. Date: 2026-10-04. Revision 1, authority set M1–M4 records the derived implementation boundary. No new user-visible recovery, persistence authority, configuration or compatibility decision is introduced. Any material departure returns to Requirements/ADR before implementation.

## M1 — Saved Tool State

Inject `SessionManager[ReadSession]` alongside the existing write manager in the completed snapshot factory and snapshot/selection stores. `with_owner` and `for_execution` rebind only mutation managers. Load uses the unfenced read-only manager and existing typed Toolkit State handle. Replace/save retains its current manager and optimistic replacement contract. Explicitly propagate the new required dependency through production and test constructors; do not infer a raw unfenced manager by unwrapping an ownership wrapper.

Discovery and remote executor I/O remain outside the completed database scope. Rebuilt tools retain the snapshot/server/project or installation identity validations already present. No new refresh policy or static-prompt lifetime change is made.

## M2 — Runtime Description

The Runtime read operation loads Agent capability, Runtime and retained configuration in a read-only scope. Target projection accepts ready retained applied configuration matching the retained desired generation, a ready Runner and Runner-reported workspace path; no target is projected from missing/terminal/unready evidence. Reuse existing target qualification semantics where equivalent rather than weaken admission.

Existing Session binding projection reads exact Agent and context plus root handle through read capability, checks retained capability version, BOUND state, Runtime ID and derived path, then returns a detached description. It must not use Agent/context lock helpers, initialize binding or perform Runtime/transport I/O. Actual binding/admission methods retain their current locking and mutation semantics.

Runtime Toolkit state/prompt paths use projection methods. Their actual tool closures still invoke current target resolution and current binding before external I/O, with the prompt-selected expected authority. The same observed descriptions can be shared within a preparation call without creating a cross-call cache authority.

The generic Engine `prepare_model_call` ownership assertion remains outside these description operations. Removing that blanket lifecycle gate belongs to the later ownership phase; this phase makes no claim that every instruction preceding a model call is already unfenced.

## M3 — Worktree Availability

Replace visibility calls to `require_bindable_context` and `resolve_operation_target` with retained projection evidence. Create additionally requires an active exact Agent Session; removal requires a ready allocation with a registered managed Project. Pending/invalid/missing binding cannot produce an eligible folder projection. Real create/remove admission, bridge identity, action claim, exact resource and ownership fencing are unchanged.

## Removal and Replacement

- Owner-bound description manager: replaced with explicit read-only dependency; verify load never enters owner wait helper and can complete while owner rows are locked.
- Runtime reconciliation during projection: replaced by retained target description; verify `ensure_for_agent`, start and reconciliation are not invoked.
- Agent/context locks and pending binding in projection: replaced by exact retained BOUND-context read; verify SQL contains no explicit row locks and binding state is unchanged.
- Worktree visibility real admission: replaced by retained eligibility; verify real admission still rejects obsolete capability/target/owner.
- Existing tests asserting blanket fencing of description loads are replaced with read-vs-write boundary tests. Public APIs, schema, generated clients, actual mutation scopes and snapshot authority are not removed.

## Test Strategy

E2E primary matrix covers normal Runtime tool preparation and worktree tool visibility, actual create/remove completion, revoked/disabled capability, unready Runtime and stale target rejection. Use the existing required Runtime/profile/worktree suites and fixture substrate; no new provider discovery fixture or credential requirement is necessary. Latest-SHA CI runs affected backend/support checks and existing required E2Es; optional credential-dependent live tests retain their current explicit skip rules.

Deterministic unit and real PostgreSQL tests complement E2E with assertions that read-only projection can run while a separate writer holds owner/Agent/binding rows, without arbitrary timing sleeps. Capture SQL/manager calls to prove lock absence and no reconciliation. Validate missing, PENDING, INVALIDATED, wrong Agent, wrong Runtime, stale capability and changed generation descriptions separately from actual admission. Test snapshot schema/executor and stored source identity pairing.

Record commands, environment, sample workload, count, p50/p95/p99, and structural lock/reconciliation counts for comparable before/after preparation samples. No production rollout or impact percentage is claimed from local measurements. Keep results in a bounded test report, not ongoing telemetry or a runtime control switch.

## Feasibility and Operations

Existing durable rows and typed detached DTOs provide the evidence; existing read-only manager enforces no DML or explicit row lock. Actual operation target/admission already validates expected authority separately. No schema migration, deployment, rollout toggle, discovery TTL, legacy mode or changed public failure contract is required. Static prompt lifecycle, broader owner/lifecycle mutation removal and catalog/Memory read coherence are outside this slice.
