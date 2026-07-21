---
title: "Persist the Session Last-Used Inference Profile Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: used-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0106-session-last-used-inference-profile.md"
---

# Persist the Session Last-Used Inference Profile Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `used-260710`
- Source: `docs/azents/adr/used-260710-used-inference-profile.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Per-prompt model target and reasoning effort controls should remain sticky within a session. The same default is also needed for runs that are not triggered by a human composer, including continuation and background-driven processing. Passing the profile only in a transient wake-up message would not survive retries, worker handoff, or server restart.

Agent defaults alone are insufficient because they discard the active session's inference choice. Browser-local persistence is also insufficient because backend-triggered runs, other devices, and recovery workers cannot observe it.

Under [time-260710/ADR](../adr/time-260710-time-target-resolution.md), the reusable selection is a model target label plus requested reasoning effort. The resolved model snapshot is run-specific execution provenance and may change when dynamic routing resolves the same target later.

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
