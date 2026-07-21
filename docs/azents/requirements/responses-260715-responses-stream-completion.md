---
title: "Require Explicit Responses Stream Completion Historical Requirements Reconstruction"
created: 2026-07-15
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: responses-260715
historical_reconstruction: true
migration_source: "docs/azents/adr/0145-require-explicit-responses-stream-completion.md"
---

# Require Explicit Responses Stream Completion Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `responses-260715`
- Source: `docs/azents/adr/responses-260715-responses-stream-completion.md`
- Historical source date basis: `2026-07-15`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The LiteLLM Responses output normalizer currently accumulates completed output items and treats them as a completed model step when the native stream reaches EOF, even if it never observes `response.completed`. A stream can therefore end with a reasoning item after `response.incomplete`, `response.failed`, or an unclassified early EOF. Because reasoning is a durable event and there is no foreground client tool call, `AgentRunExecution` can then mark the Run completed without a user-visible assistant response.

The worker already has a failed-run retry and finalization boundary. `ModelCallError` raised by the model execution path becomes a failed attempt, remains non-durable while retrying, and is promoted to terminal failed-run output only when retry policy finalizes it. The missing boundary is strict validation of the adapter-native Responses terminal event before normalized output is admitted as a successful model step.

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
