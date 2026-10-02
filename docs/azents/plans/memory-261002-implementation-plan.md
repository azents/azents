---
title: "Agentic Historical Memory Implementation Plan"
created: 2026-10-02
tags: [memory, engine, backend, implementation]
---

# Agentic Historical Memory Implementation Plan

- Snapshot: [memory-261002/REQ](../requirements/memory-261002-consolidated-history.md), [ADR](../adr/memory-261002-consolidated-history.md), [approved Design revision 2](../design/memory-261002-consolidated-history.md).
- Approved authority IDs: M1–M15, explicitly approved by the requester at 2026-10-02 21:25:10 UTC.
- Design delta: **None**.
- Implementation/integration/validation owner: primary Agent `/root`; no implementation or design delegation.
- Single independent read-only reviewer: `/root/memory-implementation-reviewer`, for every integrated stable phase diff.
- Refreshed starting main: `602b1720e4cc707d4326113273fa7349b7bbbd0b`.
- Delivery shape: dependent stacked phase PRs, created in order before CI monitoring. Merge/production rollout require separate authority.

## Phases and Boundaries

| Phase | Scope / approved mechanisms | Dependency | Branch | Output / integration gate |
|---|---|---|---|---|
| 1 | Shared execution-neutral model/tool iteration core, foreground host adaptation, parity (M1) | Main | `feat/memory-261002-1-shared-loop` | No duplicated production inference loop; no internal Session fiction; foreground tests unchanged |
| 2 | Current source identity/availability, work enrollment and unit/draft storage, exact-scope query, optional VFS mutations (M2–M5, M9, M15) | Phase 1 | `feat/memory-261002-2-storage-vfs` | Generated linear additive migration, deterministic repository races and file-tool regression |
| 3 | Internal Lightweight host, source coverage, receipts, recovery, host validation/publication, quotas/limits (M6–M11) | Phase 2 | `feat/memory-261002-3-consolidation` | Genuine multi-turn tools, no Runtime, exact work acknowledgement and stale-writer fencing |
| 4 | Whole compact documents, 10k independent rendering/20k assembly, live VFS, lifecycle and cutover/rollback (M12–M15) | Phase 3 | `feat/memory-261002-4-context-cutover` | New snapshot kind; source/Saved preservation; no packing fallback; forward/reverse rehearsal |
| 5 | Full deterministic E2E and capacity/dependency QA, removal checks, Living Spec promotion and plan cleanup (all mechanisms) | Phase 4 | `feat/memory-261002-5-verification` | Root-owned full matrix, useful test report, immutable implemented snapshot after verified completion |

All work uses approved Design interfaces. Per-phase plans precede implementation and bind exact work paths, validation and review boundaries. No phase is started before the previous phase PR is open; all PRs are created before waiting for the full stack's CI.

## Interfaces and Prerequisites

- Shared core accepts execution-neutral host operations and transient state; only foreground adapters own public events/repository terminal effects.
- Exact Team/personal authority is distinct from foreground personal Team+User reads.
- Source content/availability identity, pending work IDs and dependency receipts are repository-owned database state.
- Mutation and atomic patch protocols remain optional and separate from read-only backends.
- Model/tool/context/lease/retention limits are the approved D7 profile; no unapproved tuning.
- Use current operation/authority interfaces on main, linear Alembic generation, existing provider/lowerer contracts and normal generated-client workflow if a public schema changes.
- Deterministic unit/repository tests use synthetic fixtures. Required product E2E extends the existing Memory proxy; no live provider credentials are necessary. Runtime is absent for consolidation and used only for retained Runtime adapter regressions.

## Removal and Verification

Owning phases remove the old authoritative surfaces only when replacements activate: foreground algorithm duplication (1), Runtime-exclusive mutation binding (2), obsolete source-packing snapshot shape/ranking and current Spec claims (4–5), old concurrency default15 (3), and temporary plans after validated Spec promotion (5). Preserve Stage1 projection/source preparation, Saved CRUD, original-history authority, Skills/import and durable foreground events.

Evidence includes no-open-transaction callbacks, durable-before-output ordering, cancellation and recovery, no fake Session IDs, zero Runtime startup, Team/User sentinel request captures, complete dependencies, revocation/restore continuity, exact-row coverage, multilingual framing bytes, forward/reverse cutover and large-manifest lock latency.

## Checkpoints and Scope Control

Root records phase branch/base/PR, stable diff, test environment/commands/results, reviewer findings/fixes, mechanism coverage, removed references, remaining phases and risks. New findings are classified as local detail versus material Design delta; no plan invents requirements, persisted modes or fallback.

The feature remains unimplemented until all phases and verification gates complete. Current blockers are implementation tasks rather than external credentials: extract foreground coupling, add authority/storage boundaries, extend deterministic proxy, and prove concurrency/cutover.

## External Actions and Cleanup

PR submission is part of implementation delivery. Do not merge or apply migrations/deploy/restart production resources. Local test environment creation is separate from production. Remove this plan and all phase plans only after integrated validation and Living Spec promotion; retain final Design, ADR, Requirements and useful evidence reports.
