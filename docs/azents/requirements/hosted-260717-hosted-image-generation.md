---
title: "Provider-Hosted Image Generation Restoration Historical Requirements Reconstruction"
created: 2026-07-17
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: hosted-260717
historical_reconstruction: true
migration_source: "docs/azents/design/provider-hosted-image-generation.md"
---

# Provider-Hosted Image Generation Restoration Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `hosted-260717`
- Source: `docs/azents/design/hosted-260717-hosted-image-generation.md`
- Historical source date basis: `2026-07-17`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents has canonical parsing and UI support for provider-hosted `image_generation` activity, but the configurable builtin was removed because request lowering, capability projection, and output materialization were incomplete. The remaining output path replaces a completed image with an unavailable placeholder attachment.

Restoring only the configuration registry would recreate the original drift: a selected builtin could be silently omitted by a lowerer, and a completed provider result would still not produce a usable file.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Restore the semantic `image_generation` builtin in one change across OpenAI SDK, ChatGPT OAuth, and LiteLLM.
- Keep provider-specific wire syntax inside adapter lowerers and normalizers.
- Keep raw Base64 and image bytes out of durable events, database payload columns, REST/WebSocket projections, frontend state, logs, and native artifacts.
- Expose each generated image to later model calls as a ModelFile-backed `FileOutputPart`.
- Expose the same generated image to the user as an Exchange-backed Attachment.
- Preserve provider-tool live activity and canonical terminal status.
- Fail explicitly when the selected model or lowerer cannot provide the shared semantic behavior.

## Non-goals

- Restoring the historical Gemini Shell, reasoning, toolkit, Agent-role, or subagent validation conditions.
- Reintroducing Agent-global builtin settings.
- Treating generic image output modality as proof of provider-hosted image-tool support.
- Persisting provider-native image payloads for exact replay.
- Creating a compatibility path that silently drops unsupported builtins.
- Adding a new public event or attachment schema when the existing `FileOutputPart` and `Attachment` contracts are sufficient.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
