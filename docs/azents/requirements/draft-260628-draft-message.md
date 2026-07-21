---
title: "Draft Agent Session First Message Creation Historical Requirements Reconstruction"
created: 2026-06-28
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: draft-260628
historical_reconstruction: true
migration_source: "docs/azents/design/draft-agent-session-first-message.md"
---

# Draft Agent Session First Message Creation Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `draft-260628`
- Source: `docs/azents/design/draft-260628-draft-message.md`
- Historical source date basis: `2026-06-28`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Agent-focused chat currently creates a non-primary `AgentSession` as soon as the user clicks the
Agent rail "new session" action. This makes abandoned empty sessions durable, pollutes the session
list, and exposes session-scoped tabs before there is a real conversation.

Target product behavior:

1. Clicking "new session" opens a draft chat surface without creating an `AgentSession` row.
2. The draft surface keeps the Agent top bar so users can open Agent navigation and leave the
draft. Session-scoped Projects and Context tabs remain hidden because there is no session-owned state
yet.
3. Sending the first message creates the session and accepts that message in one backend boundary.
4. The browser URL is replaced with the canonical session URL so refresh resumes the created session.

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

No new testenv fixture support is required. Existing public API fixtures can create a workspace,
agent, auth token, and team primary session. No external LLM credential is required because the test
asserts input-buffer acceptance before model execution.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
