---
title: "Runtime and Session Lock Narrowing Phase 2"
created: 2026-08-07
tags: [runtime, profile, postgresql, concurrency, backend]
---
# Phase Execution Plan

- Phase: `2 — Optimistic Runtime Profile resolution`
- Branch/base: `fix/runtime-profile-resolution-cas` → `fix/runtime-session-lock-narrowing`
- PR boundary: Lock-free Runtime Profile source resolution with selection/version snapshot evidence and final Runtime pointer CAS.
- Inputs: Phase 1 lifecycle lock narrowing and the existing durable Runtime configuration reconcile task.
- Deliverables:
  - Runtime Profile resolution reads Agent selection, Workspace Profile, Infrastructure Profile, and Provider sources without row locks.
  - Immutable configuration revisions retain the exact source snapshot evidence.
  - Runtime binding and desired configuration attachment use the prior pointer, desired generation, and Agent selection as stale fences.
  - A stale attachment enqueues or relies on the current Agent-selection reconcile task instead of committing the stale pointer.
- Non-goals: Source-table schema changes, new task tables, external Provider I/O, Session admission changes, and public API changes.
- Interfaces: Existing resolution result, Runtime configuration revision schema, Runtime pointer attachment API, and reconcile task contract.
- Approved Design mechanisms: Immutable configuration evidence, selection-version fencing, and durable bounded reconciliation.
- Authority references: `runtime-260804/REQ-3`, `runtime-260804/REQ-4`, `runtime-260804/REQ-5`; [Runtime Profile Requirements](../requirements/runtime-260730-workspace-owned-runtime-profiles.md); [Agent Runtime Control](../spec/flow/agent-runtime-control.md).
- Design delta: `None`
- Removal obligations: Remove resolution-time Agent selection and Profile source row locks.
- Absence verification: Repository searches show resolution passes `for_update=False`; service no longer invokes the selection-lock repository API.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Resolution snapshots | root | `python/apps/azents/src/azents/services/runtime_profile_resolution/` | Immutable revision schema | Lock-free source snapshots | Resolution tests |
| Pointer CAS | root | `python/apps/azents/src/azents/repos/agent_runtime/` | Snapshot inputs | Selection and generation-fenced attach | Repository/resolution tests |
| Reconcile convergence | root | `python/apps/azents/src/azents/services/runtime_profile_reconciliation/`, `repos/runtime_profile/` | Existing task contract | Stale selection converges through durable task | Reconciliation tests |

- Integration order: Lock-free snapshots → final attach CAS → stale-selection reconcile coverage → focused quality checks.
- Independent review: `hardtack` reviews immutable evidence, stale-fence predicates, and convergence behavior against the authority references.
- Final validation: `uv run pytest src/azents/services/runtime_profile_resolution/service_test.py src/azents/services/runtime_profile_reconciliation/service_test.py src/azents/repos/agent_runtime/repository_test.py`; Ruff; format; ty; pre-commit.
- Scope-drift check: Preserve current Runtime Profile selection API and task schema; no source-table lock replacement, fallback, or new durable state.
- Context checkpoint: Phase 2 owns all Runtime Profile resolution lock changes. Phase 3 remains responsible for Session admission locks and Session-creation advisory lock removal.
