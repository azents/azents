---
title: "Use an Explicit Nested Inference Profile Request Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: public-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0115-public-inference-profile-request-contract.md"
---

# Use an Explicit Nested Inference Profile Request Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `public-260710`
- Source: `docs/azents/adr/public-260710-public-inference-profile-request-contract.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Per-prompt selection requires every run-producing human input to carry durable target intent before it enters the FIFO buffer. Deriving a queued message's target later from mutable AgentSession state would make its requested profile ambiguous. Allowing clients to submit provider or physical model snapshots would bypass the Agent-owned target policy introduced by [label-260709/ADR](../adr/label-260709-label-targets.md).

The chat API has separate request shapes for a new session's first message, existing-session Composer input, message editing, failed-run retry, and commands. Model target and reasoning effort form one conceptual inference profile and may gain additional target-policy attributes in the future.

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
