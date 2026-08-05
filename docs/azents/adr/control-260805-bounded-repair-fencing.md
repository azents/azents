---
title: "Runtime Bounded Repair Fencing"
created: 2026-08-05
tags: [runtime, backend, provider, reconciliation, architecture]
document_role: primary
document_type: adr
snapshot_id: control-260805
---

# Runtime Bounded Repair Fencing

- Snapshot: `control-260805`
- Document reference: `control-260805/ADR`
- Requirements: [Runtime Bounded Repair Fencing Requirements](../requirements/control-260805-bounded-repair-fencing.md) (`control-260805/REQ`)
- Decision mode: Requester-directed
- Decision owner: requester

## Context

`runtime-260805` removed durable reconciliation authority and bounded repair to
a correlated `OBSERVE` completion. A current configuration pointer can change
without changing the desired generation, however. Also, the former schema
migration may already be part of a deployed Alembic history. The earlier
implemented snapshot is immutable, so these corrections require a new snapshot
and current-spec update.

## Decisions

### control-260805/ADR-D1: Hold the Runtime row lock through bounded repair append

**Affected requirements:** `control-260805/REQ-1`

The Reconciler locks the target Runtime row, validates all repair fences, reads
the exact configuration through that same database session, and appends the one
`UPDATE_CONFIGURATION` command before releasing the lock. Concurrent desired
configuration, lifecycle, and terminal-delete writes serialize after the append.
The lock is not a repair claim and stores no drift/retry state.

**Rejected alternatives:**

- A durable repair claim, outbox, or queue was rejected because it recreates the
  removed reconciliation authority and changes retry semantics.
- A best-effort reread before append was rejected because a same-generation
  desired revision can change after the reread.

### control-260805/ADR-D2: Preserve history with a forward removal migration

**Affected requirements:** `control-260805/REQ-2`

Migration `142719f5305a` remains immutable. Successor revision `d51acb332a07`
removes the reconciliation enum, Runtime columns, foreign key, and index. The
current schema therefore returns to the pre-projection shape while Alembic
history remains linear and deployable.

**Rejected alternatives:**

- Deleting or editing the former migration was rejected because it can have run
  in an environment.
- Leaving the obsolete columns for compatibility was rejected because it leaves
  a second durable Runtime authority.

### control-260805/ADR-D3: Emit transient repair correlation logs

**Affected requirements:** `control-260805/REQ-3`

The Reconciler logs the eligible `OBSERVE` handoff and successful repair dispatch
with Runtime/Provider identity, current generations, exact revision, and typed
NetworkPolicy kind/reason. Logs are operational evidence only and never become
Runtime persistence or retry input.

## Consequences

- A concurrent same-generation profile resolution cannot enqueue its replaced
  NetworkPolicy as the bounded repair target.
- The short row-lock scope includes volatile command append; Control or Provider
  loss still intentionally relies on the next periodic `OBSERVE`.
- Operators can correlate one transient drift handoff to its command dispatch.
- The prior `runtime-260805` migration-head wording is historical context only;
  `control-260805/ADR-D2` is the current migration-history decision.
