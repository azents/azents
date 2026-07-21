---
title: "Keep Native Artifact Compatibility Keys Strict Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: artifact-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0154-keep-native-artifact-compatibility-keys-strict.md"
---

# Keep Native Artifact Compatibility Keys Strict Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `artifact-260716`
- Source: `docs/azents/adr/artifact-260716-artifact-compatibility-keys-strict.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents stores adapter-native output items as opaque `NativeArtifact` data. Replay is allowed only when the artifact compatibility key matches the target lowerer:

```text
adapter:native_format:provider:model:schema_version
```

The Phase 1 OpenAI migration replaces the LiteLLM transport and adapter for OpenAI API-key and ChatGPT OAuth Responses HTTP calls. Existing artifacts therefore have `litellm:responses:...` keys while newly produced artifacts will have `openai:responses:...` keys.

The migration could add a cross-adapter exception that lets the OpenAI lowerer consume old LiteLLM Responses artifacts. That would preserve more provider-native historical context, including reasoning items that canonical fallback lowering intentionally does not replay. However, it would weaken the purpose of the compatibility key by treating independently owned adapter schemas as interchangeable without an explicit data migration.

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
