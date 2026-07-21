---
title: "Adopt Agent-Centric Raw Sessions and Optional Dedicated Sandboxes Historical Requirements Reconstruction"
created: 2026-05-03
implemented: 2026-05-03
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: sandbox-260503
historical_reconstruction: true
migration_source: "docs/azents/adr/0006-agent-centric-session-sandbox.md"
---

# Adopt Agent-Centric Raw Sessions and Optional Dedicated Sandboxes Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `sandbox-260503`
- Source: `docs/azents/adr/sandbox-260503-sandbox.md`
- Historical source date basis: `2026-05-03`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

NoIntern's existing runtime used `ConversationSession` as the conversation unit, broker routing key, sandbox lifecycle owner, and `/home/sandbox` owner at the same time. This tightly coupled Slack/Discord threads, Web chat, per-session sandboxes, EFS subPaths, and the file-api backing store.

To remove EFS and move to S3 checkpointing, sandboxes cannot be created at the high-cardinality conversation/thread level. Slack, Discord, GitHub, and Jira already provide external channel/thread/ticket/issue units for conversations and work, so there is little need to keep a separate shared ConversationSession domain as the internal runtime unit.

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
