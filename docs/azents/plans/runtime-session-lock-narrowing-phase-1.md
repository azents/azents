---
title: "Runtime and Session Lock Narrowing Phase 1"
created: 2026-08-07
tags: [runtime, postgresql, concurrency, backend]
---
# Phase Execution Plan

- Phase: `1 — Runtime lifecycle atomicity and NetworkPolicy repair`
- Branch/base: `fix/runtime-session-lock-narrowing` → `main`
- PR boundary: Conditional Runtime lifecycle state transitions, narrowed Runtime locks, and lock-free NetworkPolicy repair validation.
- Inputs: Merged PR #1198 and the approved lock review.
- Deliverables:
  - `set_desired_state()` updates the Runtime through an atomic conditional `UPDATE ... RETURNING`.
  - `set_desired_state_if_ready()` and `ensure_lifecycle_configuration_revision()` lock only the Runtime with `FOR NO KEY UPDATE`.
  - NetworkPolicy repair revalidates current evidence without holding the Runtime row lock through dispatch.
- Non-goals: Runtime Profile resolution changes, Session admission changes, schema changes, API changes, and table splitting.
- Interfaces: Existing repository and reconciler method signatures; existing desired-generation and configuration-revision fencing semantics.
- Approved Design mechanisms: Existing generation fencing and current-configuration repair boundaries.
- Authority references: `runtime-260804/REQ-3`, `runtime-260804/REQ-4`, `runtime-260804/REQ-5`; `runtime-260804/ADR-D4`, `runtime-260804/ADR-D5`; [Agent Runtime Control](../spec/flow/agent-runtime-control.md).
- Design delta: `None`
- Removal obligations: Remove the NetworkPolicy repair Runtime row lock and the pre-lock in ordinary desired-state updates.
- Absence verification: Search the reconciliation handoff and Runtime repository for the removed lock paths; verify no external dispatch happens while a repair transaction has a Runtime lock.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Lifecycle transition | root | `python/apps/azents/src/azents/repos/agent_runtime/` | None | Atomic update and narrowed locks | Repository tests, Ruff, ty |
| Reconciliation handoff | root | `python/apps/azents/src/azents/runtime/control_protocol/` | Lifecycle fence semantics | Lock-free current-evidence revalidation | Reconciler tests |
| Regression coverage | root | Runtime repository and reconciler tests | Both workstreams | Concurrent/stale behavior coverage | Focused pytest |

- Integration order: Repository transition semantics → reconciler handoff → focused tests → quality checks.
- Independent review: `hardtack` reviews the Phase 1 PR against the authority references, generation fencing, absence of external I/O under a Runtime lock, and focused test evidence.
- Final validation: `uv run ruff check .`; `uv run ruff format --check .`; `uv run ty check --error-on-warning`; focused runtime repository/reconciler pytest suites.
- Scope-drift check: Preserve all lifecycle commands, terminal-delete behavior, and Runtime control contracts; reject profile-resolution, Session, schema, and API changes.
- Context checkpoint: Phase 1 changes only Runtime repository/reconciler concurrency mechanics. Later phases own Profile resolution and Session admission.
