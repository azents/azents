---
title: "PV-less Valkey Recovery Requirements"
created: 2026-09-12
implemented: 2026-09-12
tags: [reliability, backend, engine, infra]
document_role: primary
document_type: requirements
snapshot_id: valkey-260912
---

# PV-less Valkey Recovery Requirements

- Snapshot: `valkey-260912`
- Document reference: `valkey-260912/REQ`

## Problem

Transient coordination loss can admit a new Session worker while the former worker
continues producing output. Existing recovery coverage is not sufficient to assert
that all Redis-backed paths are safe when a fresh instance has no retained data.

## Primary System Outcome

A Helm-deployed Azents installation can operate with Valkey without persistent
storage. Replacing Valkey with an empty instance preserves durable correctness,
fences obsolete work, and resumes useful work without restoring Valkey data.

## Supporting Scenarios or Effects

- An operator can remove Valkey's dependency on a persistent volume after deploying
  the corrected application, without losing authoritative user data.
- Existing transient displays and in-flight operations may fail or reconnect safely.
- A new worker can recover accepted pending work after lost wake-up notifications.

## Goals

- Remove correctness dependence on retained Redis/Valkey keys across all audited uses.
- Make worker ownership loss a terminal authority boundary for obsolete execution.
- Verify empty-store recovery and document deployment constraints accurately.

## Non-Goals

- Remove durable application or file storage.
- Promise uninterrupted availability while the coordination service is unavailable.
- Promise rollback of an external effect that completed before authority was revoked.
- Replay external effects whose prior outcome is unknown.
- Apply infrastructure changes or delete existing production volumes during this work.

## Requirements

### REQ-1. Empty coordination recovery

Losing all coordination data must not be interpreted as successful completion or
restore obsolete authority. The service must recover automatically once an empty
coordination service becomes available.

**Acceptance criteria**

- Accepted durable inputs remain recoverable when their wake-up notifications vanish.
- Fresh work completes after empty-store replacement without restoring old keys.
- Previously issued transient capabilities are rejected or safely reconciled.

### REQ-2. Superseded execution is fenced

After another worker acquires authoritative Session ownership, the old worker must
not commit model output, terminal run state, or tool results under its old authority.
It must not admit new external work under superseded authority.

**Acceptance criteria**

- Ownership takeover during model response observation rejects the old durable output.
- Ownership loss is propagated to active execution rather than treated as a routine
  heartbeat warning.
- Takeover at tool admission and result persistence boundaries cannot revive or
  finalize the superseded execution.
- Already-started external work is handled conservatively without automatic replay.

### REQ-3. Every coordination role has a recovery contract

Runtime connections, operations, terminals, transfers, broker ownership/wakes, live
projections, external-channel coordination, rate limits, and administrative replay
must have explicit behavior for lost retained state.

**Acceptance criteria**

- Each audited role has code-level recovery/failure evidence and focused verification.
- Durable history and accepted work do not use transient live projections as authority.
- Cleanup can recover without retaining transient indexes or leadership state.
- Limits intentionally reset by storage loss remain separate from authentication.

### REQ-4. PV-less deployment is supported and verified

The supported deployment contract must allow an externally supplied Valkey instance
without a persistent volume, snapshot restore, or append-only recovery log.

**Acceptance criteria**

- Configuration and deployment guidance do not require Valkey persistence for correctness.
- Validation starts or replaces Valkey with no retained data and no persistent volume.
- Documentation distinguishes application readiness coupling from retained-data dependence.

### REQ-5. Preserve existing product and durable authority

The fix must preserve established input ordering, stop behavior, run recovery,
permission checks, and durable data ownership.

**Acceptance criteria**

- Existing recovery, execution, terminal, transfer, and external-channel tests remain valid.
- Previous-generation callbacks cannot undo a newer owner's durable state.
- No new permissive fallback or Redis-derived durable authority is introduced.

## Fixed Constraints

- Database transactions contain database work only; no external I/O while holding a transaction.
- Lost transient work may fail closed; availability is not guaranteed during Redis outage.
- Implemented historical snapshots and executed migrations remain immutable.
- Production resource mutation and PR merge require separate authorization.
- Measure the runtime cost of new persistence-loss tests. Remove newly added slow
  tests when they measurably slow the test suite; retain verification evidence
  separately rather than imposing an ongoing CI cost.

## Open Assumptions

- The exact external Valkey deployment is operator-owned; the product Helm chart
  connects to an external endpoint rather than provisioning its data volume.

## Confirmation

The requester directly instructed implementation of all retained-coordination
independence fixes on 2026-09-12 and added safe removal of the Helm deployment's
Valkey persistent volume as the required operational outcome. This snapshot records
those explicit execution requirements; no intermediate design approval was requested.

On 2026-09-12 the requester additionally required removal of new persistence-loss
tests if they are observed to slow the test suite.
