---
title: "Agent User Folder Recognition Historical Requirements Reconstruction"
created: 2026-04-03
implemented: 2026-04-03
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: folder-260403
historical_reconstruction: true
migration_source: "docs/azents/design/user-folder-recognition.md"
---

# Agent User Folder Recognition Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `folder-260403`
- Source: `docs/azents/design/folder-260403-folder-recognition.md`
- Historical source date basis: `2026-04-03`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Current sandbox guarantees file isolation by mounting `/data/user/` differently per user through bwrap per-user mount namespace. This mechanism was the only way to make LLM recognize user folder through fixed path `/data/user/`.

However, Discussion #2246 decided:

- **Privacy purpose of file isolation is discarded**: bwrap per-user mount prevents "B explicitly asking agent for A's file," but cannot prevent A's memory from being exposed in A session response in public channel.
- **Privacy boundary = bot access control**: assume user memory sharing among people who can access bot (→ #2242)
- **Keep user memory path**: `agents/{agent_id}/users/{nointern_user_id}/` structure remains for personalization, without isolation guarantee

→ If bwrap per-user mount is removed, LLM can no longer know user folder location. This design solves that.

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
