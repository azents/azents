---
title: "Explicit AgentSession Write Target Historical Decision Reconstruction"
created: 2026-06-25
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: write-260625
historical_reconstruction: true
migration_source: "docs/azents/design/explicit-agent-session-write-target.md"
---

# Explicit AgentSession Write Target Historical Decision Reconstruction

- Snapshot: `write-260625`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/explicit-agent-session-write-target.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### write-260625/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Decision

Existing-session REST writes must enqueue into the path session after access validation.

For `POST /chat/v1/sessions/{session_id}/messages`:

- `session_id` from the path is the authoritative write target.
- The service validates that the session exists.
- The service validates that the session belongs to the requested `agent_id`.
- The service ensures the agent runtime only to return runtime metadata and validate the session's current denormalized runtime reference during the transition.
- The service creates the `InputBuffer` for the requested `session_id`.
- `InputBufferService.enqueue(...)` marks that same session running.
- Live projection publish, broker `SessionWakeUp`, snapshot, and response all use that same session id.

For the default team-primary chat entry, Web resolves `GET /chat/v1/agents/{agent_id}/team-primary-session` before enqueue, then writes through `POST /chat/v1/sessions/{session_id}/messages`. Once a concrete session id is resolved, the enqueue service must not replace it.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
