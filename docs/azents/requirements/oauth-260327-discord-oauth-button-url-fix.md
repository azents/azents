---
title: "AuthorizationRequestEvent OAuth URL → Web App Setup Page Migration Historical Requirements Reconstruction"
created: 2026-03-27
implemented: 2026-03-27
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: oauth-260327
historical_reconstruction: true
migration_source: "docs/azents/design/discord-oauth-button-url-fix.md"
---

# AuthorizationRequestEvent OAuth URL → Web App Setup Page Migration Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `oauth-260327`
- Source: `docs/azents/design/oauth-260327-discord-oauth-button-url-fix.md`
- Historical source date basis: `2026-03-27`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The URL of the OAuth setup button sent through Discord DM exceeds Discord's 512-character limit, causing 400 Bad Request.

- **Cause**: `AuthorizationRequestEvent` includes the full OAuth URL (PKCE state ~306 chars + code_challenge, etc.), about ~653 chars.
- **Impact**: Discord users cannot receive toolkit OAuth setup button. Slack currently works because it has a 3000-character limit, but the same duplicated path problem exists.

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
