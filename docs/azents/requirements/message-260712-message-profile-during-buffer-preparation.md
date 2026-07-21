---
title: "Resolve User Message Profiles During Buffer Preparation Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: message-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0126-resolve-user-message-profile-during-buffer-preparation.md"
---

# Resolve User Message Profiles During Buffer Preparation Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `message-260712`
- Source: `docs/azents/adr/message-260712-message-profile-during-buffer-preparation.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[time-260710/ADR](../adr/time-260710-time-target-resolution.md) resolves a requested model target when an AgentRun starts, and [atomic-260710/ADR](../adr/atomic-260710-atomic-profile-activation.md) updates the AgentSession last-used profile as part of run activation. Under [drain-260712/ADR](../adr/drain-260712-drain-input-buffers-before-turn-start.md), input-buffer draining is now a preparation stage that completes before the next turn starts. Keeping label resolution in SessionRunner run preparation would preserve an unnecessary coupling between queued message semantics and turn creation.

A user message carries the user-authored content, including attachments and file parts, plus optional model and reasoning-effort overrides. Processing that message must apply those settings deterministically while preserving an immutable account of what the message changed.

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
