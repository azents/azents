---
title: "Subagent Human Write Boundary"
created: 2026-07-09
tags: [architecture, agent, api, security, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: subagent-260709
historical_reconstruction: true
migration_source: "docs/azents/adr/0098-subagent-human-write-boundary.md"
---

# subagent-260709/ADR: Subagent Human Write Boundary

## Context

Azents adopted a Codex-first subagent model where subagents are child `AgentSession` actors coordinated by the parent agent through model-visible collaboration tools. The frontend exposes child session detail views so users can inspect child transcripts and navigate the subagent tree.

A child detail view is an observation surface, not a human chat target. If a user can bypass the UI and directly mutate a child session through REST writes, the product model becomes ambiguous: work could enter a subagent outside the parent orchestration path, child Todo/Goal state could be edited independently by a human, and future mailbox/follow-up semantics would have to account for unmanaged human-origin inputs.

## Decision

Treat subagent child sessions as human read-only REST targets.

Human-origin direct REST writes to a child subagent session are rejected by the server. This includes direct chat/message input, user-editable session state such as Goal and Todo updates, session metadata mutations, archive/delete operations, pending command/edit/retry controls, action execution retry/discard controls, and manual cleanup requests. Read paths remain allowed for authorized users so child history, live state, and subagent tree detail views can be inspected.

Subagent work must be assigned or updated through the parent-agent control plane. Initial spawning, future follow-up work, mailbox messages, and interruption semantics use explicit subagent collaboration tools and their server-owned orchestration paths rather than generic human chat write APIs.

When a request targets an existing child session but violates this boundary, return a conflict-style error rather than hiding the session as nonexistent. The failure means the session exists but is not a valid direct human write target.

## Consequences

- The UI read-only child detail behavior becomes a backend invariant instead of a client-only affordance.
- Parent-agent orchestration remains the single way to assign human-requested work to subagents.
- Future `send_message` and `followup_task` semantics can assume child input from humans is mediated by collaboration tools.
- Tests should cover direct REST message writes and user-editable state writes against child sessions.
- Child session read APIs and authorized deep links remain available for observability and debugging.

## Migration provenance

- Historical source filename: `0098-subagent-human-write-boundary.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
