---
title: "ADR-0141: Correlate Terminal Run Events by Run ID"
created: 2026-07-12
tags: [architecture, backend, chat, engine, frontend]
---

# ADR-0141: Correlate Terminal Run Events by Run ID

## Context

Chat live state can receive terminal control events after a later Run has already become active. Existing `RunComplete`, `RunStopped`, and `live_run_cleared` payloads do not consistently identify the Run they terminate. The frontend can therefore clear the current Run in response to a delayed event from an older Run.

A separate defect allows the session-level unhandled-error reporter to publish `RunComplete` without first transitioning the corresponding AgentRun to a durable terminal state. This makes a stream boundary disagree with the database lifecycle.

## Decision

Every terminal run control event carries the concrete `run_id` it terminates.

- `RunComplete`, `RunStopped`, and `live_run_cleared` include `run_id`.
- Frontend current-run clearing requires an exact match between the event `run_id` and the active Run `run_id`.
- A stale terminal event remains observable but cannot clear a different active Run.
- `RunComplete` is published only after the identified AgentRun has completed its durable terminal transition.
- A message-processing failure that occurs before a concrete Run exists may publish a user-safe error observation, but it does not publish a run terminal event.
- An unhandled failure after Run creation enters the failed-run finalization boundary so durable terminal state and terminal publication remain one ordered contract.

Preparation failures keep their existing terminal/no-retry semantics. This decision changes correlation and publication ordering, not preparation policy.

## Rejected Options

### Rely on session event delivery order

Rejected. REST responses, reconnect buffering, and distributed publication can delay an older event beyond the start of a newer Run.

### Clear any active Run on a terminal event

Rejected. The event proves only that one Run terminated, not that the current Run terminated.

### Publish `RunComplete` as a generic UI stream boundary

Rejected. The event name and existing consumers represent run termination. A nonterminal message-processing boundary needs a different observation rather than a false terminal event.

## Consequences

- Terminal event schemas and generated clients change.
- Emitters must have the concrete Run ID at publication time.
- Frontend reducers become robust to delayed terminal events.
- Tests can assert that every `RunComplete` corresponds to a durable terminal AgentRun.
- Pre-run errors no longer hide an unrelated or still-running Run.
