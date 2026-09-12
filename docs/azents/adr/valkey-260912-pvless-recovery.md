---
title: "PV-less Valkey Recovery Decisions"
created: 2026-09-12
tags: [reliability, backend, engine, infra]
document_role: primary
document_type: adr
snapshot_id: valkey-260912
---

# PV-less Valkey Recovery Decisions

- Snapshot: `valkey-260912`
- Requirements: [valkey-260912/REQ](../requirements/valkey-260912-pvless-recovery.md)

## Context and Execution Authority

The requester directly authorized removal of retained Redis/Valkey correctness
dependencies and safe operation without a Valkey persistent volume on 2026-09-12.
This is corrective implementation of the existing durable ownership and ephemeral
coordination contract, not a new recovery mode or a request for an interactive
design approval process.

## D1. Enforce existing durable Session ownership at execution boundaries

**Decision:** Keep the existing durable Session owner generation as the single
worker authority. Enforce it at durable execution transactions and external-work
admission boundaries. Redis routing locks remain replaceable scheduling hints.

**Authority:** `valkey-260912/REQ-1`, `valkey-260912/REQ-2`, `valkey-260912/REQ-5`;
the existing canonical Session execution contract and Redis optionality convention.

**Rejected alternatives:** Restoring Redis locks from backups, requiring AOF/PV/HA,
relying on heartbeat timing, or treating an in-process task flag as ownership.
These do not satisfy empty-store correctness. A second generation source is also
unnecessary because the durable authority already exists.

**Consequences:** Superseded output and finalization fail without modifying another
owner's state. Ownership rejection must close further admission and terminate the
active execution path; it is not a retryable model failure. Existing external calls
are not retroactively rolled back and unknown outcomes are not replayed.

## D2. Separate durable admission from external execution

**Decision:** Validate and record admission in short database-only boundaries, then
perform external I/O after the transaction closes. Revalidate durable authority
before admitting the resulting durable state. Keep cancellation best effort for
already-admitted external operations.

**Authority:** `valkey-260912/REQ-2`, `valkey-260912/REQ-5`; existing database-only
transaction convention and durable foreground-call recovery contract.

**Rejected alternatives:** Holding a database transaction across model/tool/Redis
I/O, or broadly retrying ambiguous external operations after takeover.

**Consequences:** Tests distinguish work admitted before takeover from attempts to
admit new work afterward. Durable fencing, not transport timing, determines whether
a result can modify current state.

## D3. Support empty external Valkey without changing durable storage

**Decision:** Preserve the Helm external-endpoint contract. Validate empty-store
replacement without volume/snapshot recovery and document that Valkey persistence
is not an application correctness requirement. Durable application and object
storage retain their existing responsibilities.

**Authority:** `valkey-260912/REQ-1`, `valkey-260912/REQ-3`, `valkey-260912/REQ-4`.

**Rejected alternatives:** Bundling a new Redis deployment into the product chart,
removing durable application storage, or making live volume deletion part of the
application code fix.

**Consequences:** Product rollout and external volume lifecycle are distinct.
Availability may temporarily fail during outage; recovery from a fresh instance
must not depend on retained locks, streams, indexes, or leadership keys.
