---
title: "Workspace User Invitation Feature Historical Requirements Reconstruction"
created: 2026-02-19
implemented: 2026-02-19
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: invitation-260219
historical_reconstruction: true
migration_source: "docs/azents/design/workspace-invitation.md"
---

# Workspace User Invitation Feature Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `invitation-260219`
- Source: `docs/azents/design/invitation-260219-invitation.md`
- Historical source date basis: `2026-02-19`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Feature allowing workspace members (manager or higher) to invite other users to workspace by email address. Invited users can check invitation list on `/workspaces` page and accept/decline.

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

- Email-based invitation: can invite regardless of signup status.
- Invitation token unnecessary: after login, show invitation list by email matching.
- Send invitation email: button with login link.
- Permission: only manager or higher can invite (`WORKSPACE_USERS:WRITE`).
- Automatically create WorkspaceUser on invitation accept.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
