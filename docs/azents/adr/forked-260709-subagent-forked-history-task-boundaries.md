---
title: "Mark Forked History Boundaries for Subagent Tasks"
created: 2026-07-09
tags: [architecture, backend, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: forked-260709
historical_reconstruction: true
migration_source: "docs/azents/adr/0101-subagent-forked-history-task-boundaries.md"
---
# forked-260709/ADR: Mark Forked History Boundaries for Subagent Tasks

## Context

Azents subagents can receive forked parent history through `fork_turns`. When the fork includes all or part of the parent conversation, earlier user instructions remain visible to the subagent. Without an explicit boundary, the subagent can misread those inherited user instructions as direct instructions for its own current task.

Codex-compatible subagent behavior relies on two separate signals:

1. a boundary between inherited parent history and the subagent's current assignment; and
2. an explicit envelope for the parent-to-subagent task payload.

Azents should preserve these signals instead of relying on role ordering alone.

## Decision

When `fork_turns` copies parent history (`all` or a positive integer), Azents will insert a system reminder immediately after the copied history and before the subagent's current task. The reminder is rendered in a `<system-reminder>` envelope, marks everything above it as inherited parent history, and marks the following message as the subagent's current task.

Parent-to-subagent current tasks will also be rendered with an explicit task envelope rather than as undifferentiated text. The envelope must identify the message as a new task, include sender/recipient context, and place the actual task in a payload section.

`fork_turns=none` does not need the forked-history boundary reminder because no parent history is copied.

## Rationale

The boundary reminder directly addresses the model interpretation problem: the subagent must know where inherited context ends and where its own assignment begins. Placing the reminder after the copied history keeps the signal adjacent to the boundary it describes.

The task envelope is still required because the boundary alone only separates history from the next item. The envelope gives the next item its semantics: it is a parent-assigned task, not merely another historical message.

## Consequences

- Subagent prompt construction must distinguish copied parent history from the current parent-to-subagent task.
- The boundary reminder is only inserted when there is inherited history.
- The current task renderer must produce a stable, explicit envelope for parent-to-subagent assignments.
- Specs for agent execution and toolkit behavior must describe the boundary and task envelope once implemented.

## Migration provenance

- Historical source filename: `0101-subagent-forked-history-task-boundaries.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
