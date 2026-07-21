---
title: "AgentSession Archive Policy"
created: 2026-06-26
tags: [architecture, backend, frontend, ui, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: archive-260626
historical_reconstruction: true
migration_source: "docs/azents/adr/0079-agent-session-archive-policy.md"
---

# archive-260626/ADR: AgentSession Archive Policy

## Context

AgentSession already has an `archived` lifecycle state in the data model, but the product did not expose
an archive action. The Agent-focused sidebar now makes multiple active sessions visible and selectable,
so users need a way to remove obsolete non-primary sessions from the active list without deleting the
durable transcript.

The team-primary session has a different role from other sessions: it is the stable default
conversation anchor for an Agent. The `/chat` route and team-primary lookup rely on that anchor to
exist or be created as the default session. Archiving it would make the default conversation feel
replaceable and would require replacement-session semantics that are easy to confuse with ordinary
session cleanup.

Running sessions also have active worker, live projection, WebSocket, and pending input state. Archiving
them while they are running would introduce ambiguous ordering between stop intent, worker completion,
and session lifecycle changes.

## Decision

Expose AgentSession archive as a soft lifecycle transition for non-primary inactive sessions only.

- The user-facing archive API archives only active sessions with `primary_kind = null`.
- Team-primary AgentSessions cannot be archived.
- Running AgentSessions cannot be archived. Users must stop the run first.
- Archive keeps durable data such as transcript events, runs, files, and project registry rows.
- Archived sessions are removed from active session lists.
- The initial product scope does not include an archived-session browser or restore flow.
- In the Agent session list UI, the archive button appears in the same trailing slot as the running
  indicator and is shown only when the session is non-primary and not running.
- The archive action requires a confirmation dialog before executing.
- If the currently selected non-primary session is archived, the UI navigates back to the Agent `/chat`
  route, which resolves to the team-primary session.

## Consequences

- Team-primary remains the stable default conversation anchor for each Agent.
- Users can clean up non-primary sessions without losing transcript data.
- The UI avoids a separate session actions menu and keeps the archive affordance near the existing
  running-state indicator.
- Running-session safety is explicit and avoids lifecycle races with the worker.
- A future archived-session browser can be added as a separate read-only surface without changing the
  first archive contract.

## Migration provenance

- Historical source filename: `0079-agent-session-archive-policy.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
