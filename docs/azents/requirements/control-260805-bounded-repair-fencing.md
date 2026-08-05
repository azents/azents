---
title: "Runtime Bounded Repair Fencing Requirements"
created: 2026-08-05
updated: 2026-08-05
implemented: 2026-08-05
tags: [runtime, backend, provider, reliability, security]
document_role: primary
document_type: requirements
snapshot_id: control-260805
---

# Runtime Bounded Repair Fencing Requirements

- Snapshot: `control-260805`
- Document reference: `control-260805/REQ`
- Supersedes for current behavior: [Runtime Bounded Drift Re-observation Requirements](runtime-260805-bounded-drift-reobservation.md)

## Problem

A bounded `OBSERVE` repair must not enqueue a configuration that ceased to be
current while Control was preparing the command. Separately, a prior migration
may already exist in a deployed database history even when its durable
reconciliation authority must be removed from the current schema.

## Primary Actor

A platform operator deploying Runtime Control while a Provider reports managed
NetworkPolicy drift and a Runtime Profile resolution may update the desired
configuration concurrently.

## Primary Scenario

Control receives a valid current `OBSERVE` completion with NetworkPolicy drift.
It serializes the Runtime's current configuration decision with any concurrent
lifecycle or desired-configuration write, issues at most one non-destructive
repair for the resulting current target, and records sufficient correlation for
operators to audit the handoff. Schema upgrade removes obsolete reconciliation
projection through a successor migration without rewriting deployed history.

## Supporting Scenarios

- A same-generation desired configuration revision replaces the observed
  revision while Control prepares the repair.
- A lifecycle or terminal-delete transition competes with the repair handoff.
- A database already contains the former reconciliation projection migration.

## Goals

- Prevent a stale same-generation configuration from being dispatched as a
  drift repair.
- Preserve existing lifecycle, configuration-adoption, reset, and terminal-delete
  precedence.
- Keep bounded re-observation and the prohibition on durable drift-repair state.
- Preserve linear Alembic history while removing obsolete schema authority.
- Make repair handoff and dispatch diagnosable through structured logs.

## Non-Goals

- Add a durable repair claim, drift queue, outbox, retry marker, or event ledger.
- Guarantee repair delivery after Control, Provider, or stream loss.
- Change Provider protocol compatibility or introduce a fallback path.
- Execute migrations or mutate live infrastructure as part of this work.

## Requirements

### REQ-1. Linearized current repair target

Control must serialize an eligible `OBSERVE` handoff with concurrent changes to
the Runtime's desired configuration and lifecycle target before it appends an
`UPDATE_CONFIGURATION` repair.

**Acceptance criteria**

- A same-generation desired configuration revision cannot cause an old revision
  to be dispatched after the replacement becomes current.
- Pending lifecycle dispatch and terminal deletion prevent repair dispatch.
- The repair remains one in-place `UPDATE_CONFIGURATION`; it does not create
  durable repair authority or an immediate retry loop.

### REQ-2. Preserved migration history

Removal of obsolete durable reconciliation schema must preserve the already
published migration revision and use a successor revision to return the current
schema to its pre-projection shape.

**Acceptance criteria**

- Historical migration `142719f5305a` is unchanged.
- The current Alembic head is a successor that removes the reconciliation enum,
  columns, foreign key, and index.
- Upgrade and downgrade remain reversible in the migration graph.

### REQ-3. Correlated operational evidence

Control must emit structured handoff and dispatch logs for an eligible bounded
repair without persisting drift evidence.

**Acceptance criteria**

- Both records include Runtime ID, Provider ID, Provider generation, desired
generation, configuration revision, reconciliation kind, and reason.
- The log records do not add a durable Runtime field or retry state.

## Fixed Constraints

- The older `runtime-260805` snapshot remains immutable; current behavior and
  this correction are recorded in this new snapshot and Living Specs.
- Kubernetes Provider admission remains v2-only.
- Repair eligibility still expires on stream completion, reconnect, or Control
  restart until a later periodic `OBSERVE` produces a new handoff.

## Requester Confirmation

The requester explicitly required a successor reversal migration rather than
modifying historical migration `142719f5305a`, and required current-generation
and configuration fences without durable reconciliation state.
