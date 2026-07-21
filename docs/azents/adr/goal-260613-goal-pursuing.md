---
title: "Goal Pursuing Is Owned at Session Scope"
created: 2026-06-13
tags: [backend, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: goal-260613
historical_reconstruction: true
migration_source: "docs/azents/adr/0060-session-scoped-goal-pursuing.md"
---

# goal-260613/ADR: Goal Pursuing Is Owned at Session Scope

## Context

To introduce Codex-style goal pursuing into Azents within a realistic scope, Goal ownership scope must be fixed first. Codex manages a single persisted goal per thread, and if an active goal remains, it is used as basis for idle continuation.

Azents has both parent agent sessions and subagent sessions. If Goal is inherited or shared from parent to subagent, automatic continuation, complete judgment, blocked judgment, and user control get mixed across session boundaries. Conversely, if Goal is run-scoped, pursuing state that persists across turns cannot be represented.

## Decision

In Azents, Goal for goal pursuing is owned at session scope.

- Goal belongs to `AgentSession`.
- Goal is not run-scoped state.
- Parent session Goal is not inherited by subagent session.
- Subagent has independent session, so Goal is also owned independently.
- Whether to expose goal toolkit to subagents is a separate decision.
- Even if goal toolkit is exposed to subagents, that toolkit reads or changes only the subagent's own session Goal.
- Parent passing an objective to subagent is task delegation, not Goal inheritance.

## Consequences

- Goal continuation is always judged only inside the same session.
- Complete or blocked judgment of parent session and subagent session are independent.
- Do not create a path where subagent implicitly changes parent goal state.
- Whether to provide Goal toolkit to subagents is separated as a capability exposure issue.
- Unlike Todo, Goal is not parent session shared state.

## Migration provenance

- Historical source filename: `0060-session-scoped-goal-pursuing.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
