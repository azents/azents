---
title: "Sentry Toolkit Historical Requirements Reconstruction"
created: 2026-03-27
implemented: 2026-03-27
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: toolkit-260327
historical_reconstruction: true
migration_source: "docs/azents/design/sentry-toolkit.md"
---

# Sentry Toolkit Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `toolkit-260327`
- Source: `docs/azents/design/toolkit-260327-sentry-toolkit.md`
- Historical source date basis: `2026-03-27`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Service Toolkit using Sentry official MCP server (`@sentry/mcp-server`). Enables agent to query Sentry issues, events, traces, and perform AI-based root cause analysis (Seer).

**Usage scenarios:**
- When agent receives bug report, query related issues/events in Sentry and analyze cause based on stacktrace.
- When errors spike after deploy, search Sentry issues and understand impact scope.
- Use Seer AI for automatic root cause analysis + code fix suggestions.

**Implementation Phases:**
- **Phase 1 (this document)**: per-user OAuth mode — reuse Notion pattern, no infra change
- **Phase 2**: access_token mode — stdio via mcp-proxy sidecar ([separate document](../design/sentry-260327-sentry-toolkit-stdio.md))

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
