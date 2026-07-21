---
title: "Unified OAuth Authentication Flow Historical Requirements Reconstruction"
created: 2026-03-27
implemented: 2026-03-27
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: unified-260327
historical_reconstruction: true
migration_source: "docs/azents/design/unified-oauth-flow.md"
---

# Unified OAuth Authentication Flow Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `unified-260327`
- Source: `docs/azents/design/unified-260327-unified-oauth.md`
- Historical source date basis: `2026-03-27`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

When using per-user OAuth2 toolkits (Sentry, Notion, etc.) from Discord/Slack, unify the flow so platform account linking → toolkit OAuth authentication is connected **without interruption**.

**Problems solved:**

1. Discord adapter has no `AuthorizationRequestEvent` handler, so when `request_authorization` is called, no message reaches user.
2. Platform linking (Discord) and toolkit OAuth (Sentry) are separated as different tools, so after linking completes, user must ask the bot again.
3. Even after linking completes, clicking the DM link again shows already-completed linking page again.

**Usage scenario:**
- Discord user who is not linked asks for Sentry → DM has "Set up" button → Discord linking → **automatically redirects to Sentry OAuth page** → Sentry auth completes → Sentry tools are available from next request.

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
