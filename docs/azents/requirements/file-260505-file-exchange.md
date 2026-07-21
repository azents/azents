---
title: "Adopt Agent File Exchange Storage Separate from Sandbox Workspace Historical Requirements Reconstruction"
created: 2026-05-05
implemented: 2026-05-06
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: file-260505
historical_reconstruction: true
migration_source: "docs/azents/adr/0007-agent-file-exchange-storage.md"
---

# Adopt Agent File Exchange Storage Separate from Sandbox Workspace Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `file-260505`
- Source: `docs/azents/adr/file-260505-file-exchange.md`
- Historical source date basis: `2026-05-05`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

NoIntern's existing file paths mixed File API, EFS, `/data/*`, `shared:///session/*`, and `/home/sandbox`. Web uploads were stored by the backend through the File API under `/data/uploads/{session_id}/...`, and Slack/Discord file bridges read and wrote files through the same File API layer. The LLM-facing file tool also accepted either File API or sandbox daemon injection and handled both through the same `FileStorage` protocol.

However, in the agent-centric raw session and optional dedicated sandbox architecture, files have two different lifecycles.

1. Files uploaded by users or offered to users as downloads need UI/API contracts, TTL, quota, and audit.
2. Files read and written by shell and file tools inside the sandbox need the active filesystem path as the canonical source, and checkpoints should cover `/home/sandbox/**`.

If these two axes are merged into one EFS/File API path, upload handling for sandboxless agents, artifact download, hibernated sandbox restore, and TTL enforcement become hard to define consistently.

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
