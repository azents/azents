---
title: "Make PostgreSQL Authoritative for Tool Call Ownership"
created: 2026-07-12
tags: [architecture, backend, engine, worker, reliability, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: postgresql-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0143-make-postgresql-authoritative-for-tool-call-ownership.md"
---

# postgresql-260712/ADR: Make PostgreSQL Authoritative for Tool Call Ownership

## Context

Foreground client tool execution crosses model output persistence, handler side effects, worker shutdown, ownership takeover, result persistence, and live UI delivery. Redis activity and live-event projections previously duplicated active-call state, so recovery could observe a call event, active marker, and result from different authorities. Retrying an unresolved call after worker loss could duplicate a non-idempotent side effect.

Azents requires deterministic recovery without assuming that arbitrary tool handlers are idempotent.

## Decision

PostgreSQL event transcript and `agent_runs.active_tool_calls` are the sole execution authority for foreground client tool calls.

- A run commits the complete model-emitted call set and its active ownership entries before creating any handler task.
- Each ownership entry records the admitting Session owner generation.
- Each terminal result is appended atomically with removal of only its matching active entry.
- Terminal results use a deterministic external ID unique to the run and call.
- Recovery never executes a previous-generation active call or a durable orphan call. It requests best-effort cancellation when applicable and appends one deterministic cancelled result.
- A result with stale active ownership keeps the result and removes only the stale ownership entry.
- TERM closes the admission barrier before waiting for already admitted work.
- REST live state reconstructs active tool-call events from PostgreSQL. Redis carries routing, leases, Pub/Sub delivery, and assistant/reasoning streaming partials, but no active tool-call truth.
- User-stop cancellation candidates come from PostgreSQL active ownership rather than Redis projections.

## Rejected Alternatives

### Re-execute unresolved calls after takeover

This can duplicate external side effects when the old worker completed the handler but crashed before recording the result.

### Require every tool to provide an idempotency key

Azents supports arbitrary builtin, MCP, and custom tools. Universal idempotency is not enforceable and would move a core execution guarantee into every integration.

### Fence every result write by current owner generation

A finishing admitted call may commit during graceful handover. Rejecting that valid completion would replace an observed result with cancellation and create unnecessary ambiguity. Owner generation is recovery evidence, not stale-writer fencing.

### Keep Redis as an active-call cache

A second active-state authority reintroduces disagreement after TTL expiry, process loss, or partial publication. REST resynchronization can project the durable PostgreSQL state directly.

## Consequences

- A side effect may have occurred even when recovery records a cancelled result; Azents deliberately prefers no automatic re-execution over duplicate side effects.
- Tool admission requires a PostgreSQL commit before handler start.
- Recovery and user stop share deterministic result-finalization primitives.
- Redis loss cannot change active execution ownership.
- WebSocket delivery remains best effort; missed actions converge through REST live-state resynchronization.
- Background Runtime operation completion is not part of the tool execution contract. Long-running exec processes remain explicitly observable through process events and `write_stdin`.

## Migration provenance

- Historical source filename: `0143-make-postgresql-authoritative-for-tool-call-ownership.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
