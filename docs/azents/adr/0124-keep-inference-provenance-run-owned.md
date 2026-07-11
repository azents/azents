---
title: "ADR-0124: Keep Resolved Inference Provenance Run-Owned"
created: 2026-07-11
tags: [architecture, api, chat, frontend, observability]
---

# ADR-0124: Keep Resolved Inference Provenance Run-Owned

## Context

ADR-0122 projected the latest associated AgentRun summary into durable chat events and required the worker to republish existing `history_event_appended` events whenever run provenance changed. The frontend replaced the existing timeline item with the republished event.

This made an append-only transcript transport behave like a mutable projection. A user input could be broadcast repeatedly as its run was created, resolved, retried, or completed. Replacing the old item by removing and appending it moved historical inputs to the bottom of the timeline, while accepting every broadcast created duplicates. The event-level projection also required history and live REST reads to join events back to AgentRuns.

Resolved model display for historical messages is useful, but it does not justify mutating or reordering canonical transcript events.

## Decision

Resolved inference provenance remains owned and projected by AgentRun only.

- Persist requested and resolved provenance on AgentRun as defined by ADR-0117.
- Keep the current live run summary in the dedicated live Run projection. Token/context usage may use that summary only when run IDs match exactly.
- Keep requested target and effort on user/action input events so historical inputs can display their immutable requested intent.
- Do not attach `inference_run_summary` to history events, partial-history events, or input-buffer event projections.
- Do not query AgentRun summaries while listing chat events.
- Do not republish an existing `history_event_appended` event when AgentRun provenance changes.
- Treat a repeated `history_event_appended` event ID as idempotent on the client: preserve the existing timeline item and its position.

This decision supersedes ADR-0122's event-level inference-summary projection and provenance-triggered history-event refresh. ADR-0122 remains as immutable decision history.

Historical resolved-model display may return through a separate run-owned read model or interaction later. It must not depend on mutating canonical transcript events.

## Rejected options

### Continue replacing repeated history events in place

The event transport has no revision or ordering contract for mutable records. Replacement also couples transcript identity to an independently changing Run projection.

### Remove and append the refreshed event

This visibly reorders old user inputs and caused the reported timeline instability.

### Keep summaries only in REST history responses

REST and WebSocket would expose different event shapes, and reconnect could still rewrite immutable timeline state from a derived latest-run association.

## Consequences

- Canonical history append events are stable and idempotent by event ID.
- Run lifecycle changes update only the live Run projection and other run-owned surfaces.
- Historical messages show requested target/effort but no resolved physical model.
- Terminal token/context usage no longer recovers context limits from historical event summaries; the indicator requires the matching active live Run summary.
- Chat history and live baseline queries no longer perform event-to-run provenance joins.
- A future historical resolved-model feature needs an explicit run-owned API and UI design.
