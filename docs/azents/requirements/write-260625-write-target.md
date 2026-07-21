---
title: "Explicit AgentSession Write Target Historical Requirements Reconstruction"
created: 2026-06-25
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: write-260625
historical_reconstruction: true
migration_source: "docs/azents/design/explicit-agent-session-write-target.md"
---

# Explicit AgentSession Write Target Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `write-260625`
- Source: `docs/azents/design/write-260625-write-target.md`
- Historical source date basis: `2026-06-25`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

This document defines Phase 2 of the multi-active `AgentSession` migration: user input writes must target the explicitly requested `AgentSession`. Runtime-owned active/current session lookup must not redirect a write to another session.

Phase 1 already moved execution-control state such as `run_state`, `run_heartbeat_at`, pending command, and stop request fields to `AgentSession`. Phase 2 makes the write path align with that ownership: the input buffer row, live projection, broker wake-up, and write response all use the same target session id.

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
