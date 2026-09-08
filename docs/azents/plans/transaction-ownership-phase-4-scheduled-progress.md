---
title: "Transaction Ownership Phase 4: Scheduled Task Progress Effects"
created: 2026-09-08
tags: [backend, architecture, database, scheduled-task, external-channel]
---

# Phase Execution Plan

- Phase: 4, Scheduled Task progress provider-effect transaction ownership.
- Branch/base: `refactor/scheduled-task-transactions-260908` →
  `refactor/title-repository-transactions-260908`.
- PR boundary: one reviewable Scheduled Task progress correction that separates
  repository-owned database admission and settlement from provider and Runtime I/O.
- Inputs: requester transaction rules and implementation instruction;
  [transaction-260908/DESIGN](../design/transaction-260908-repository-ownership.md),
  revision 1; the Session/Agent transaction research report; current Scheduled Task
  and External Channel Living Specs.
- Reviewer: `/root/tx-review` (read-only).
- Integration owner: `/root`.
- Mechanisms: M1, M2, M3, M4, M5.
- Authorities: `transaction-260908/REQ-1` through `REQ-5`;
  `transaction-260908/ADR-D1` through `ADR-D3`.
- Design delta: None.

## Milestones

### M1. Repository-owned progress preparation and effect admission

Add Scheduled Task cycle operation-repository boundaries that own their session
lifetimes and compose the existing AgentRun, cycle, and External Channel database
primitives. The preparation operation validates the current Run/cycle/Binding and
atomically records progress plus Tracker claim while returning detached provider
plans. The effect-admission operation revalidates the current started cycle and
exact expected cycle version in a completed database-only transaction.

### M2. Provider and Runtime effects outside database transactions

Execute prepared reply parts and the Tracker mutation only after effect admission
commits and no database transaction remains active. Preserve the existing operation
seeds, file and Runtime authority arguments, one-attempt behavior, provider unknown
and failure outcomes, cancellation propagation, reply-part ordering, and
reply-before-Tracker ordering. Introduce no replay, fallback, queue, history, or
cross-I/O lock.

### M3. Repository-owned Tracker settlement

Settle a completed Tracker outcome in a fresh database-only operation using the
existing cycle identity, active phase, expected desired revision, projection-part
ordinal, and optimistic cycle-version behavior. A concurrent revision,
terminalization, or projection replacement prevents the stale outcome from
changing canonical Tracker state. Provider failure and unknown outcomes retain the
existing projection mapping.

### M4. Deterministic regression coverage and Living Spec synchronization

Cover zero active database transactions during every external effect, a revision
that supersedes the initially prepared work before effect admission, an inactive
cycle before admission, cancellation after provider return and before settlement,
provider failure, and duplicate operation seeds. Use explicit events/barriers or
repository-controlled state transitions rather than sleeps. Update the Scheduled
Task and External Channel Living Specs only for the current transaction boundary;
make no API, schema, or product-policy change.

### M5. Validation and exception conclusion

Run focused repository/service tests, changed-path Ruff and format checks, the full
backend `ty --error-on-warning` check, and repository pre-commit. Confirm by search
that the migrated progress service no longer owns a database session or passes a
session alias/callback across provider I/O. Report the residual race boundary and
record that no cross-I/O database/distributed/process lock was added; a standalone
memory implementation is not relevant to this lock-free slice.

## Exact Concurrency Boundary

The baseline second phase locks the cycle row, revalidates the cycle version, keeps
the lock across every provider effect, and settles the Tracker before releasing the
transaction. Its stale-effect linearization point is therefore the second lock and
version check, not the initial progress-preparation commit.

The replacement effect-admission operation preserves suppression of any newer
progress revision or inactive cycle committed after initial preparation but before
admission. Once admission commits, the one-attempt provider effect is authorized;
settlement still rejects a result when a later revision or terminalization wins.
Without a lock spanning provider I/O or durable serialized execution, no lock-free
implementation can atomically couple an external call with the absence of a commit
that occurs after admission. This phase does not add either forbidden mechanism.
The residual admission-to-call window is reported explicitly rather than hidden by
an in-memory lock or a renamed transaction owner.

## Owned Paths and Interfaces

| Workstream | Owner | Owned paths | Output | Validation |
| --- | --- | --- | --- | --- |
| Scheduled progress orchestration | `/root/impl-scheduled-progress` | `python/apps/azents/src/azents/services/scheduled_task/channel.py`, directly related callers and tests | Detached preparation/admission snapshots; provider I/O outside DB; preserved outcomes and ordering | Service boundary and deterministic concurrency tests |
| Database composition | `/root/impl-scheduled-progress` | `python/apps/azents/src/azents/repos/scheduled_task_cycle/**`, new Scheduled progress operation data/repository modules, directly related tests | Repository-owned preparation, admission, and settlement transactions using narrow SQL-only repositories | Atomicity, version/desire fences, duplicate seed tests |
| Current behavior documentation | `/root/impl-scheduled-progress` | Current Scheduled Task and External Channel Specs as required | Current DB/I-O/DB boundary and residual race statement | Spec validation and pre-commit |

Strictly necessary dependency-injection and caller updates belong to this phase.
Registration, deletion, initial Tracker, terminal publication, general Channel
Work, Mailbox/VFS, and other Scheduled Task transaction ownership remain outside
this PR unless a direct interface change requires a bounded caller update.

## Removal and Absence Verification

Remove `execute_progress` ownership of both service-level session contexts and the
cycle row lock spanning provider/Runtime effects. Replace them with typed completed
repository operations. Do not add a generic transaction callback, service-visible
session alias, provider call from a repository, or compatibility wrapper.

Search every affected constructor/caller and verify that all touched application DB
operations are repository-owned. Verify absence of provider, Runtime, file storage,
broker, Redis, and filesystem I/O in the new operation repositories, and absence of
new lock, retry, durable queue/history, migration, API, or schema surfaces.

## Validation Commands

From `python/apps/azents`:

- focused `uv run pytest` for Scheduled Task channel and cycle operation tests;
- `uv run ruff check` and `uv run ruff format --check` for changed Python paths;
- full `uv run ty check --error-on-warning`;
- repository pre-commit from the worktree root.

Record exact pass/failure counts and any prerequisite issue. This owner does not
commit, push, open, or merge the PR.
