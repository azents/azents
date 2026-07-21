---
title: "Display Inference Provenance from User Message Metadata Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: message-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0112-user-message-profile-provenance-display.md"
---

# Display Inference Provenance from User Message Metadata Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `message-260710`
- Source: `docs/azents/adr/message-260710-message-profile-provenance-display.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Per-prompt model selection needs durable, discoverable history so users can understand queued inputs, retries, failures, and future dynamic routing. Repeating profile badges on both user and assistant messages would add substantial visual noise. Displaying only the physical resolved model would also replace the stable Agent-owned target label the user actually selected with an implementation detail that can change behind routing policy.

User messages already render compact sent-time metadata. That location directly identifies the prompt whose requested profile created a run boundary without introducing another message row or assistant-response badge.

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
