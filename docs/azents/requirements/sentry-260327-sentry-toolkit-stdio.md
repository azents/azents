---
title: "Sentry Toolkit — access_token Mode (stdio via mcp-proxy) Historical Requirements Reconstruction"
created: 2026-03-27
implemented: 2026-03-27
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: sentry-260327
historical_reconstruction: true
migration_source: "docs/azents/design/sentry-toolkit-stdio.md"
---

# Sentry Toolkit — access_token Mode (stdio via mcp-proxy) Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `sentry-260327`
- Source: `docs/azents/design/sentry-260327-sentry-toolkit-stdio.md`
- Historical source date basis: `2026-03-27`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Sentry User Auth Token (`sntryu_...`) does not work with remote endpoint (`mcp.sentry.dev`); only OAuth access tokens are allowed. Therefore, to use workspace-level API token, run `@sentry/mcp-server` via stdio and expose it over HTTP through mcp-proxy sidecar.

**Benefits of this mode:**
- Shared across entire workspace after admin configures once.
- Usable in autonomous behavior mode (system session).
- Individual users do not need Sentry OAuth authorization.

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
