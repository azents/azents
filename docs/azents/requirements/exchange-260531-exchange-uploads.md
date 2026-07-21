---
title: "Agent-scoped Exchange Uploads Historical Requirements Reconstruction"
created: 2026-05-31
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: exchange-260531
historical_reconstruction: true
migration_source: "docs/azents/adr/0045-agent-scoped-exchange-uploads.md"
---

# Agent-scoped Exchange Uploads Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `exchange-260531`
- Source: `docs/azents/adr/exchange-260531-exchange-uploads.md`
- Historical source date basis: `2026-05-31`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Web chat file upload required AgentSession ID through `POST /chat/v1/sessions/{session_id}/upload`. Because of this, attaching a file before sending the first message in a new chat required creating a session before upload or re-querying active session.

This model had these problems:

- From the user's perspective, file upload is Agent/Workspace work, but it required a session identifier.
- If active session re-query right before upload returns a session different from the current screen's session, workspace membership validation runs against the wrong session and can fail with 403.
- `exchange_files` table keeps `agent_session_id` and `agent_runtime_id` as required columns, unnecessarily coupling upload with runtime/session lifecycle.
- It creates the concept of "file list per session," but actual attachments are referenced by messages through `exchange://...` URI. For single-file download/delete access control, file workspace is enough.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
