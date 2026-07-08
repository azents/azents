---
title: "ADR-0097: Continue FIFO Processing After Failed TurnActions"
created: 2026-07-08
tags: [architecture, backend, engine, session]
---

# ADR-0097: Continue FIFO Processing After Failed TurnActions

## Context

ADR-0094 modeled session operations as ordered TurnActions. Its original failure policy stopped later
pending input until the user retried or discarded the failed operation action. During the prerequisite
stack validation, this behavior conflicted with the intended turn-boundary queue semantics: a failed
TurnAction is a terminal result for that action, not a permanent run/session blocker.

The same validation found that successful Project-mutating TurnActions must still be a context
invalidation boundary. Continuing with a stale model/tool context after `session_workspace_projects`
changes can omit the new Project, Project-scoped instructions, and Skill projection from the next
model call.

## Decision

A failed operation TurnAction is marked failed and FIFO processing continues to the next pending input
or action. Retry and discard APIs may still mutate failed action execution state, but they are not
required to unblock the input queue.

A successful Project-mutating TurnAction remains a context invalidation boundary. When it completes
inside an already-running model-call boundary, the runner exits the current processing boundary,
marks the current agent run cancelled without appending a completed run marker, and enqueues a
follow-up wake-up when pending input remains. The next processing pass rebuilds run context from the
updated Project registry before promoting later model input.

## Consequences

- One failed TurnAction no longer strands later user messages or actions behind retry/discard.
- Failed operation history remains visible through action execution state.
- Project/context changes still prevent stale model/tool context from reaching the next model call.
- Run history does not show a misleading completed run marker for context-invalidation handoff
  boundaries.
