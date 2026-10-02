---
title: "Historical Memory Phase 2: Preparation Pipeline and Boundary Snapshots"
created: 2026-10-01
updated: 2026-10-01
tags: [memory, backend, scheduler, engine, testing]
---

# Historical Memory Phase 2: Preparation Pipeline and Boundary Snapshots

## Phase Execution Plan

- Phase: `2/6 — Preparation pipeline and boundary snapshots`
- Branch/base: `feature/historical-memory-2-preparation` → `feature/historical-memory-1-foundation`
- PR boundary: activate bounded asynchronous Historical Memory preparation and replace active per-turn Saved Memory selection with persisted initial/post-compaction boundary snapshots, without adding VFS reads or public settings surfaces
- Inputs: Phase 1 PR #2020 and commit `a5d113de0`; confirmed `memory-260930/REQ`; accepted `memory-260930/ADR-D1` and `ADR-D3` through `ADR-D15`; approved `memory-260930/DESIGN` revision `1`
- Deliverables: five-minute discovery task, registered target-Agent Job Runtime handler, bounded Lightweight preparation flow, strict prompt/output/summary guard, retry/publication and metrics, typed `memory/context_snapshot` Toolkit State, deterministic Saved/Historical selection, initial and post-compaction snapshot boundaries, and injected Saved/Historical Memory block
- Non-goals: VFS router/backends, Memory virtual tree, generic read-tool ownership, dedicated Memory/history tool removal, Historical settings API/UI, generated clients, E2E, load validation, Spec promotion, deployment, or merge
- Interfaces: `historical_memory_discovery` Scheduler definition; `historical_memory.prepare` Job Runtime request/result payload; preparation service and prompt contract; `MemoryContextSnapshotState`; boundary identity by `model_input_head_event_id`; snapshot selection/filter/render service; Memory-read Toolkit prompt provider
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`, `M14`, `M15`
- Authority references: `memory-260930/REQ-1` through `REQ-8` and `REQ-10`; `memory-260930/ADR-D1`, `ADR-D3` through `ADR-D11`, `ADR-D14`, `ADR-D15`; current Memory, Context Compaction, Toolkit, and Periodic Execution Specs
- Design delta: `None`
- Removal obligations: replace active per-turn dynamic Saved Memory summary selection after boundary snapshots are active and covered by equivalence/privacy tests; retain Saved Memory CRUD and model-facing read/write tools until their approved later cutover phases
- Absence verification: active Memory-read prompt path no longer calls live Saved Memory summary selection on ordinary turns; no VFS mount/router/backend, public Historical route/UI, generated client, removed read tool, or final Scheduler rollout enablement outside the approved Phase 2 activation appears in the diff

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase contract | `/root` | `docs/azents/plans/historical-memory-phase-2-preparation.md` | Phase 1 checkpoint | Current Phase 2 scope, interfaces, removal, validation, and drift boundary | Docs validation, diff check |
| Discovery and dispatch | `/root` | `python/apps/azents/src/azents/{scheduler/registry.py,job_runtime/registry.py,job_runtime/registry_test.py,scheduler/registry_test.py,services/historical_memory/**}` | Phase 1 repository | Five-minute bounded admission/discovery, post-commit Agent dispatch, coalesced registered handler, reserved concurrency | Scheduler/Job Runtime/service tests |
| Preparation model flow | `/root` | `python/apps/azents/src/azents/services/historical_memory/**`, directly required model-stream/provider helpers and focused tests | Phase 1 contracts and projections | Frozen Lightweight candidate chain, strict prompt/output decode, 9,000-byte guard, candidate advancement, retry progress, atomic publication, safe metrics | Provider doubles, retry/candidate tests, transaction-boundary tests |
| Snapshot state and selection | `/root` | `python/apps/azents/src/azents/core/historical_memory_snapshot.py`, `python/apps/azents/src/azents/repos/historical_memory/**`, `python/apps/azents/src/azents/services/historical_memory/**`, focused tests | Prepared source rows and Saved Memory repository | Typed persisted boundary snapshot, deterministic Team/User privacy selection, complete-block budgets, filter-without-reselection behavior | Repository/service privacy and determinism tests |
| Boundary integration and prompt cutover | `/root` | `python/apps/azents/src/azents/engine/tools/builtin.py`, `python/apps/azents/src/azents/engine/tools/builtin_test.py`, `python/apps/azents/src/azents/engine/events/**` only where boundary signaling is required, Worker composition paths | Snapshot service | Initial and post-compaction snapshot creation; ordinary-turn load/filter/render; active per-turn Saved selection removed | Initial/ordinary/post-compaction tests, Memory-disabled tests, prompt snapshots |

- Integration order: phase plan → snapshot domain/repository contracts → discovery/Job Runtime registration → preparation model flow → snapshot selection/rendering → boundary/toolkit integration → removal/absence checks → integrated backend validation
- Independent review: `/root/historical-memory-reviewer`; `/root` requests review only after all Phase 2 workstreams are complete, the integrated diff is stable, and final validation passes
- Final validation: root runs docs validation and `git diff --check`; backend Ruff/format and whole-subproject typecheck; focused Scheduler, Job Runtime, Historical preparation, snapshot, Toolkit prompt, compaction-boundary, privacy, retry, and model-operation tests; full backend pytest; OpenAPI no-diff; transaction-boundary and absence searches
- Scope-drift check: Phase 2 must implement only `M1-M8/M14/M15`, keep `Design delta: None`, preserve duplicate/restart computation without a durable lease ledger, use only the Lightweight chain with no Main fallback, keep Saved Memory independent, and omit every Phase 3-6 interface and removal
- Context checkpoint: Phase 1 PR #2020 supplies reviewed persistence, authorization locks, model/output contracts, semantic projection, and migration `459a4285993c`; Phase 2 owns first behavior activation and boundary snapshots; remaining phases own VFS, tool cutover, settings/UI, E2E, Specs, implemented markers, and plan cleanup; conditional risks are model-provider contract integration, compaction boundary signaling, snapshot privacy filtering, and reserved Job Runtime concurrency
