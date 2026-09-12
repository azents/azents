---
title: "PV-less Valkey Recovery Design"
created: 2026-09-12
implemented: 2026-09-12
tags: [reliability, backend, engine, infra]
document_role: primary
document_type: design
snapshot_id: valkey-260912
---

# PV-less Valkey Recovery Design

- Snapshot: `valkey-260912`
- Requirements: [valkey-260912/REQ](../requirements/valkey-260912-pvless-recovery.md)
- Decisions: [valkey-260912/ADR](../adr/valkey-260912-pvless-recovery.md)

## Current Gap

Redis ownership loss can route a Session to another Worker. Durable ownership is
incremented, but model output and some engine finalization paths still use an
unbound database session manager. The active heartbeat task treats durable owner
rejection as an ordinary warning. This allows the old execution to survive takeover.

## Architecture and Authority

Retain PostgreSQL Session `owner_generation` and existing Runtime generation
records. Add no generation counter, durable coordination table, fallback authority,
or new externally visible recovery mode.

### M1. Owner-bound durable execution transactions

A repository-owned execution scope locks and validates the exact Session owner
generation before admitting a database operation. The scope is bound to one Session
and one immutable owner generation; model/command preparation, output admission,
phase/retry/terminal updates, tool-result persistence, and relevant compaction
callbacks must use the same authority. Thread the scope through the existing
execution collaborators rather than consulting global state.

Keep transactions short and database-only. External preparation precedes the scope;
external execution follows admission. Check existing lock ordering and concurrency
regressions when composing the authority lock with narrower repositories.

Use the existing root SessionAgent lifecycle gate before the Agent and
root/parent/executing Session rows. Non-blocking row acquisition inside a savepoint
releases the gate on contention; only clean admission scopes retry. Terminal
finalization prelocks its authority before mutating Run rows. This preserves the
existing tree lifecycle boundary without adding another ownership authority.

Generated-file preparation uploads outside database transactions. Its deterministic
resource identities include Run, owner generation, call, and output index, isolating
old-owner uploads and compensation from a replacement owner's resources. Admission
revalidates file authority and commits metadata only; compensation reads committed
metadata before deleting unowned keys outside the transaction. Existing committed
file references remain unchanged.

### M2. Supervised ownership loss and external-work admission

Distinguish owner rejection from recoverable transport failures and user stop.
Ownership loss closes local admission and cancels/supersedes active execution.
Cancellation cleanup must preserve that reason, must not finalize another owner's
Run, and must not delete or flush another owner's live state.

A foreground tool/action must pass current-owner admission before its handler is
invoked. Completed output is revalidated in its commit transaction. A call admitted
before takeover may already have an irreversible effect; it is cancelled best effort
and its unknown result is never automatically replayed. Durable recovery keeps the
existing call identity/dialect and reconciles previous-generation calls.

### M3. Empty-store recovery by role

Retain and test the existing DB-backed mailbox/RUNNING recovery trigger, consumer
group reconstruction, Runtime generation authority, terminal ticket invalidation,
transfer object-store orphan scanning, durable transcript/live-projection separation,
external-channel durable acceptance, and best-effort enrollment limiter semantics.
Where a role has a remaining retained-state dependency, replace that dependency at
its authoritative boundary and add a focused regression.

### M4. Deployment contract and no-PV verification

Keep Helm's external Redis endpoint. The test deployment uses Valkey without a
persistent volume and with persistence disabled explicitly. Validate empty-instance
replacement and fresh work without snapshots or retained keys. Document that
readiness can fail during outage while retained state is not required for correctness.
The operator-owned Valkey volume lifecycle remains outside application rollout.

## Interfaces, Persistence, and Compatibility

- No new public API, durable schema, or migration is planned.
- Internal execution collaborators carry a bound owner authority and a distinct
  ownership-loss signal as needed.
- Existing model dialects/lowerers retain their payload semantics; admission and
  completion fencing applies uniformly above provider translation.
- No compatibility reader, permissive fallback, or Redis restoration path is added.

## Failure and Recovery

An owner mismatch aborts the current database transaction. The old execution stops
without reporting a model error, consuming a user stop, clearing newer live work,
or completing a newer owner's Run. A current owner recovers from durable transcript,
mailbox, and Run records. In-flight transient Runtime/terminal/transfer work may fail
closed and callers may start fresh work after re-registration.

## Test Strategy

1. Preserve the real PostgreSQL/Redis model-response takeover reproduction and make
   stale output rejection deterministic at the response boundary.
2. Cover ownership loss during tool admission, result persistence, heartbeat,
   terminal/failure finalization, and old-owner cleanup. Verify database transactions
   are closed before provider/model/tool/Redis I/O.
3. Add a scoped two-Worker E2E fixture and an explicit model-response barrier; use
   supported test APIs and observable state rather than timing or E2E database writes.
4. Retain existing empty-Valkey Runtime E2E, add fresh Session work after loss, and
   validate terminal/transfer/external-channel/live roles with targeted loss checks.
5. Run focused regressions, complete backend quality checks, relevant Helm rendering,
   Spec review, independent code review, and PR CI. Report executed coverage and gaps
   separately; never treat skipped or timed-out work as passed.
6. Measure added test duration separately from existing fixture setup. If the new
   container-replacement/two-Worker test slows the suite, keep its one-time evidence
   in the implementation report and remove that test and dedicated support from the
   shipped diff. Preserve fast deterministic owner-boundary regressions and existing
   recovery coverage.

## Rollout and Rollback

Deploy corrected application code before changing an operator-owned Valkey volume
configuration. Keep PostgreSQL and object storage unchanged. Removing/restoring a
Valkey PV is not performed by this change. Rolling back to unfenced application code
would invalidate the no-retained-state correctness guarantee.

## Observability and Risks

- Log ownership revocation separately from a retryable heartbeat transport failure.
- Avoid duplicate exception logging and stale execution failure events.
- Watch database lock ordering and keep authority scopes free of external callbacks.
- A pre-admitted external effect cannot be retroactively undone; correctness requires
  conservative durable settlement and no ambiguous replay, not a claim of rollback.

## Design Authority

- Design revision: `1`

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Bound durable owner checks at execution transactions | `valkey-260912/REQ-2`, `valkey-260912/ADR-D1` | decided |
| M2 | Supervised owner loss and DB-only external admission | `valkey-260912/REQ-2`, `valkey-260912/ADR-D2` | decided |
| M3 | Role-specific recovery without retained state | `valkey-260912/REQ-1`, `valkey-260912/REQ-3`, existing ephemeral coordination contract | required |
| M4 | External Valkey without PV and reproducible validation | `valkey-260912/REQ-4`, `valkey-260912/ADR-D3` | decided |

## Removal and Replacement

| Existing behavior | Removal authority | Replacement | Absence verification |
| --- | --- | --- | --- |
| Unbound old-owner engine output/finalization | `valkey-260912/REQ-2` | M1 | Real DB takeover regressions |
| Owner rejection logged as an ordinary heartbeat warning | `valkey-260912/REQ-2` | M2 | Active-execution cancellation tests |
| Stale cleanup modifying newer execution projections | `valkey-260912/REQ-2`, `valkey-260912/REQ-5` | M2 | New-owner state preservation tests |
| Reliance on persisted Valkey state for deployment validation | `valkey-260912/REQ-4` | M4 | No-PV empty-store validation |

## Feasibility and Execution Approval

Existing durable owner fields, repository locks, short execution scopes, broker
recovery, and disposable Valkey fixtures provide the required mechanisms without a
schema migration. Exact callback coverage and lock ordering are implementation
verification obligations, not a new product choice.

The requester directly authorized implementation of the complete outcome on
2026-09-12. This document records the derived corrective mechanisms under that
execution request (revision 1, M1–M4); it does not claim a separate interactive
review or approval of the document. No intermediate approval gate was requested.
