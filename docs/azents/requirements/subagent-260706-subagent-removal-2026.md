---
title: "Subagent Removal Historical Requirements Reconstruction"
created: 2026-07-06
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: subagent-260706
historical_reconstruction: true
migration_source: "docs/azents/design/subagent-removal-2026-07-06.md"
---

# Subagent Removal Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `subagent-260706`
- Source: `docs/azents/design/subagent-260706-subagent-removal-2026.md`
- Historical source date basis: `2026-07-06`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The current subagent model exposes subagents as specialized agents linked through an `agent_subagents` junction table. Parent agents receive a generated `subagent` tool that invokes the child agent and projects `subagent_start` / `subagent_end` events into the parent transcript.

This model is no longer the desired foundation. The next subagent direction should not inherit the old role/linking/event contract by accident. Existing deployments used for this cleanup do not require preserving subagent data.

## Primary Actor

The old implementation will be deleted rather than hidden or partially retained.

Rationale: the next design should not inherit old API, DB, runtime event, or frontend semantics accidentally.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Remove the current subagent runtime/tool implementation.
- Remove the agent-subagent link repository, service, API routes, schemas, and database model.
- Remove public API and generated-client surfaces for subagent links.
- Remove frontend subagent management and transcript rendering surfaces.
- Remove current living specs that describe subagent behavior.
- Preserve historical ADRs and unrelated design records unless they are dedicated obsolete implementation notes.

## Non-goals

- Design or implement the next subagent architecture.
- Preserve compatibility for existing subagent API clients.
- Preserve subagent table data.
- Rewrite adopted ADR history.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
