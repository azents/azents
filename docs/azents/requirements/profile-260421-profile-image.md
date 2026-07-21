---
title: "Agent Profile Image Historical Requirements Reconstruction"
created: 2026-04-21
implemented: 2026-04-21
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: profile-260421
historical_reconstruction: true
migration_source: "docs/azents/design/agent-profile-image.md"
---

# Agent Profile Image Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `profile-260421`
- Source: `docs/azents/design/profile-260421-profile-image.md`
- Historical source date basis: `2026-04-21`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Per-Agent profile image upload/serving feature. Reflect per-agent avatar in web UI display and Slack message sending.

This feature is the first nointern feature to **store/serve user-uploaded files in S3**. Therefore, instead of avatar-specific implementation, it introduces a **generalized file upload framework** (`UploadService` + `UploadHandler`) that future chat attachments / workspace icons can share. Avatar is implemented as its first handler.

- Related issue: [#2828](https://github.com/azents/azents/issues/2828)
- Discussion: [#2830](https://github.com/azents/azents/discussions/2830)
- Decision record: [adr/0001-agent-profile-image.md](../adr/profile-260421-profile-image.md)

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

1. Workspace admin creates agent and uploads profile image.
2. In web UI, select file → square crop (react-easy-crop) → upload.
3. Once saved, displayed as circular avatar in agent list/card/chat header.
4. When that agent responds in Slack, displayed as message sender avatar.
5. To change image, upload again (re-crop = re-upload).
6. If image removed, web falls back to client initials, Slack falls back to app default icon.

**Out of scope**: Discord per-agent avatar (Bot REST API cannot override identity per-message; Webhook transition is separate work, so P1=A abandoned).

## Supporting Scenarios

1. Workspace admin creates agent and uploads profile image.
2. In web UI, select file → square crop (react-easy-crop) → upload.
3. Once saved, displayed as circular avatar in agent list/card/chat header.
4. When that agent responds in Slack, displayed as message sender avatar.
5. To change image, upload again (re-crop = re-upload).
6. If image removed, web falls back to client initials, Slack falls back to app default icon.

**Out of scope**: Discord per-agent avatar (Bot REST API cannot override identity per-message; Webhook transition is separate work, so P1=A abandoned).

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
