---
title: "Runtime Bounded Drift Re-observation"
created: 2026-08-05
tags: [runtime, backend, provider, reconciliation, architecture]
document_role: primary
document_type: adr
snapshot_id: runtime-260805
---

# Runtime Bounded Drift Re-observation

- Snapshot: `runtime-260805`
- Document reference: `runtime-260805/ADR`
- Requirements: [Runtime Bounded Drift Re-observation Requirements](../requirements/runtime-260805-bounded-drift-reobservation.md) (`runtime-260805/REQ`)
- Decision mode: Requester-directed
- Decision owner: requester

## Context

`runtime-260804` correctly removed Provider-local command-history authority, but
it added a durable Runtime drift projection, repair claim, and retry state.
NetworkPolicy application is idempotent and periodic explicit observation already
rediscovers drift. The requester selected bounded re-observation rather than
durable continuation of a transient observation.

## Decisions

### runtime-260805/ADR-D1: Use bounded re-observation instead of durable drift state

**Affected requirements:** `runtime-260805/REQ-2`, `REQ-3`

Runtime Control does not persist reconciliation status, reason, observation
fences, or repair-request time on `agent_runtimes`. Control or report loss may
discard an observed drift. The next periodic explicit `OBSERVE` rediscovers any
remaining drift and supplies a new current observation.

**Rejected alternatives:**

- Retaining the current durable projection and atomic repair claim was rejected
  because it makes a convergent observation a second durable Runtime authority.
- A durable event ledger was rejected because no audit replay or exactly-once
  repair guarantee is required.

### runtime-260805/ADR-D2: Repair only from an OBSERVE completion handoff

**Affected requirements:** `runtime-260805/REQ-2`, `REQ-3`

The gRPC bridge retains the command type only for the lifetime of its active
Provider stream. When a successful current `OBSERVE` completion carries supported
NetworkPolicy drift, the report sink hands that transient observation to the
Reconciler for one fenced `UPDATE_CONFIGURATION` dispatch. The bridge does not
trigger repair from ordinary reports, watch/failover reports, `START`, or
`UPDATE_CONFIGURATION` completions.

This transient source correlation prevents a failed repair completion from forming
an immediate repair loop. A later periodic `OBSERVE` is the only retry trigger.

**Rejected alternatives:**

- Repairing every drift-bearing report was rejected because an
  `UPDATE_CONFIGURATION` completion could recursively enqueue itself.
- Adding command source to the durable Runtime row was rejected because it would
  recreate the removed repair state.
- Adding a command source field to the Provider protocol was rejected because
  stream-local request correlation already provides the required bounded handoff.

### runtime-260805/ADR-D3: Keep typed drift reporting and v2-only admission

**Affected requirements:** `runtime-260805/REQ-1`, `REQ-3`, `REQ-4`

The structured current-v2 `network_policy` observation remains the typed Provider
fact contract. Kubernetes v1 remains rejected before registration. Removing
durable projection does not return drift to lifecycle strings, Provider-selected
commands, or untyped diagnostics.

### runtime-260805/ADR-D4: Define strict plane ownership

**Affected requirements:** `runtime-260805/REQ-4`

- **Provider plane:** inspect backend resources, apply only received commands,
  and report factual lifecycle plus typed managed-resource comparison. It cannot
  choose repair commands, persist Control authority, or rewrite lifecycle using
  command history or drift.
- **Report-sink plane:** authenticate/generation-check report delivery, validate
  immutable binding and current configuration evidence, and persist only durable
  lifecycle/configuration/connection projections. It cannot retain drift,
  reconstruct backend facts, or independently retry commands.
- **Reconciler plane:** select and dispatch commands from durable desired state,
  current connection fences, and an explicitly handed-off current OBSERVE result.
  It cannot inspect Kubernetes, infer drift from lifecycle strings, or redefine
  Provider facts.

## Consequences

- A crash after drift observation can delay repair until the next periodic
  observation, rather than continuing from a database projection.
- The Runtime schema and migration return to their pre-projection shape.
- Repair duplication is bounded by one completion handoff per OBSERVE and the
  existing idempotent Provider application boundary.
- The typed Provider report contract remains necessary to keep drift separate from
  lifecycle.
