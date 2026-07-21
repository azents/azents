---
title: "Provider Tool Live Activity Historical Requirements Reconstruction"
created: 2026-07-16
implemented: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: activity-260716
historical_reconstruction: true
migration_source: "docs/azents/design/provider-tool-live-activity.md"
---

# Provider Tool Live Activity Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `activity-260716`
- Source: `docs/azents/design/activity-260716-live-activity.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Provider-hosted tools execute as part of a provider-owned model stream. Azents currently normalizes their durable call or result only after the model response reaches a successful completion boundary. When Web search or another hosted tool takes several seconds, the chat timeline shows only general model activity and users cannot distinguish active provider work from a slow response.

The current transports do not share native stream types. OpenAI API-key and ChatGPT OAuth use official OpenAI SDK events, while other providers use LiteLLM Responses events. Future adapters may use additional native SDKs. Product behavior must not depend on one transport's event classes or status vocabulary.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

1. Display observed provider-hosted tool activity before the complete model response is available.
2. Use one provider-neutral projection contract across every adapter output normalizer.
3. Preserve adapter ownership of native event parsing and identity normalization.
4. Restore running activity through the existing `/live` and WebSocket resync surfaces.
5. Replace live activity with durable provider-tool history without duplication or disappearance.
6. Remove attempt-local provider activity on failure, retry, Stop, and terminal cleanup.
7. Keep provider-hosted tools separate from Azents-executed client-tool lifecycle and recovery.

## Non-goals

- Do not infer tool execution from Agent configuration, request tools, elapsed time, or model capability.
- Do not add provider-specific WebSocket actions, REST fields, or frontend components.
- Do not make every provider expose progress when its transport supplies only final output.
- Do not add provider-tool cancellation, retry, or execution ownership to Azents.
- Do not add provider-specific citation rendering.
- Do not persist native progress events or incomplete provider-tool calls in transcript history.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
