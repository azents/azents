---
title: "Transaction Ownership Phase 21: Engine Scheduled and Subagent Tools"
created: 2026-10-01
tags: [backend, engine, scheduled-task, subagent, architecture, database]
---

# Phase Execution Plan

- Phase: `21, Engine Scheduled Task and Subagent tools`
- Branch/base: `refactor/transaction-ownership-261001-9-engine-scheduled-subagent`
  → `refactor/transaction-ownership-261001-8-engine-runtime-reads` at
  `accb40006` while PR #2016 remains open with required CI passed.
- PR boundary: replace the five Scheduled Toolkit and eight Subagent Toolkit
  caller-owned session contexts with typed completed repository operations.
- Inputs: Phase 20 Runtime/OAuth operations, PR #2016, and the bounded
  51-context/9-file Engine lexical checkpoint.
- Deliverables: completed Scheduled management/cycle reads and mutations,
  completed Subagent policy/tree reads and atomic collaboration mutations,
  unchanged post-commit channel/broker/event effects, and an updated Engine
  residual checkpoint.
- Non-goals: Scheduled dispatch/control/management service ownership outside the
  Toolkit call paths, terminal settlement internals, worker wait behavior, model
  execution, provider output, compactor ownership, public schemas, persistence
  schema, retries, fallbacks, or new locking mechanisms.
- Interfaces: Scheduled Task authority, mutation lock order, cycle projection,
  provider notification ordering, Subagent path resolution, capacity/depth
  enforcement, fork selection, inference inheritance/override validation,
  mailbox scheduling, broker wake/stop timing, tree invalidation, errors, and
  cancellation remain unchanged.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`,
  `transaction-260908/ADR-D1` through `ADR-D3`, and
  `transaction-260908/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations: remove direct session contexts and SQLAlchemy session
  types from the assigned Engine tool modules; repository operations receive no
  service, Engine orchestration, broker, provider, filesystem, Runtime, or
  arbitrary callback dependency.
- Absence verification: assigned direct-session search, repository-to-service
  and repository-to-Engine-orchestration import searches, focused operation and
  Toolkit tests, transaction-closure tests, and post-commit external-effect
  ordering assertions.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Scheduled Toolkit operations | `/root` | `engine/tools/scheduled.py`, Scheduled definition/tool operation repositories, tests, DI | Task, cycle, mailbox, Run repositories and existing authority predicates | Completed active-cycle, started-cycle, create/list/delete operations with detached projections | Scheduled Toolkit tests, operation transaction-closure tests, mutation-order regressions |
| Subagent Toolkit operations | `/root` | `engine/tools/subagent.py`, Subagent operation repository, mailbox composition, tests, Worker DI | Agent, SessionAgent, AgentRun, transcript, mailbox, metadata-source, coordination repositories | Completed policy/tree reads and atomic spawn/send/follow-up/interrupt/list operations | Subagent Toolkit tests, operation transaction-closure/rollback tests, capacity and fork regressions |
| External effects | `/root` | existing channel, broker, and publish call sites after operation return | committed operation results | Channel registration/deletion, broker wake/stop, and tree invalidation only after transaction closure | active-transaction sentinels around every effect |
| Engine residual checkpoint | `/root` | phase/master plans and bounded inventory evidence | assigned workstreams | corrected remaining Engine classification | lexical/call-path search; no completeness claim beyond assigned paths |

- Integration order: extract shared Scheduled database composition, add completed
  Scheduled tool operations, migrate the Toolkit and DI, add Subagent read and
  mutation operations, migrate the Toolkit and Worker DI, add repository
  boundary tests, update Specs, then run the residual checkpoint.
- Spawn boundary: database preparation may return detached policy/history/source
  snapshots for pure Engine inference and fork projection. The final operation
  re-resolves the current SessionAgent, revalidates the invoking running
  AgentRun, locks the root tree, rechecks depth/capacity, and atomically creates
  the child Session, pending Run, inference state, fork transcript, and initial
  wake-producing mailbox item before returning.
- External-effect boundary: Scheduled channel registration/deletion and Subagent
  broker wake/stop plus tree invalidation execute only after completed
  repository operations. Missing targets preserve no-effect responses.
- Independent review: one read-only reviewer inspects the stable integrated diff
  for authority, lock ordering, rollback, post-commit effects, and scope drift.
- Final validation: root runs changed-path Ruff/format, focused Scheduled and
  Subagent pytest, full backend `ty`, pre-commit, direct-session/import searches,
  and creates the next stacked PR.
- Scope-drift check: preserve authority, deterministic ordering, errors,
  snapshots, wake/stop semantics, and atomic groups; add no lock, queue, retry,
  fallback, API, schema, protocol, dependency, or configuration mechanism.
- Context checkpoint: this phase owns all 13 direct session contexts in
  `scheduled.py` and `subagent.py`. Engine execution, provider output, and
  compaction ownership remain later batches.

## Implementation Checkpoint

- `ScheduledTaskToolOperationRepository` owns active-cycle resolution, started
  cycle continuity reads, Task creation, Task listing with execution-state
  derivation, and Task deletion. Existing Session/Agent/Binding authority and
  Mailbox → cycle → Task mutation ordering remain unchanged.
- `SubagentToolOperationRepository` owns current policy/role reads, detached
  spawn preparation, final atomic spawn commit, message/follow-up/interrupt
  mutations, and bounded list projection. Final spawn commit revalidates the
  invoking running Run and root-tree depth/capacity before child Session, pending
  Run, inference state, fork transcript, and initial mailbox commit.
- Scheduled channel registration/deletion and Subagent broker wake/stop,
  queue-only activity notification, and tree invalidation execute after the
  completed database operation returns.
- Assigned `scheduled.py` and `subagent.py` direct session contexts are zero.
  The new operation repositories import no service layer or external client.
- Focused Scheduled/Subagent/resolve/service validation: 98 tests passed.
  Operation transaction-closure tests: 2 passed. Full backend validation:
  6,823 tests passed and 3 skipped. Full backend `ty --error-on-warning`
  and repository-wide pre-commit passed.
- Independent reviewer `/root/phase21-review` reported zero findings after
  checking authority revalidation, Scheduled lock ordering, stale spawn
  snapshots, mailbox atomicity, post-commit effects, and owner-bound operation
  replacement.
- A bounded post-change direct-literal scan finds 23 remaining Engine
  session-manager contexts across `events/execution.py`,
  `events/provider_output.py`, and `events/filters.py`. These are the next
  model-execution, provider-output, and compaction/filter ownership batches; the
  scan is not a completeness claim beyond Engine.
- Design delta: `None`.
