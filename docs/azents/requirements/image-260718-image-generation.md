---
title: "Model-Specific Image Generation Execution Historical Requirements Reconstruction"
created: 2026-07-18
implemented: 2026-07-18
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: image-260718
historical_reconstruction: true
migration_source: "docs/azents/design/model-specific-image-generation.md"
---

# Model-Specific Image Generation Execution Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `image-260718`
- Source: `docs/azents/design/image-260718-image-generation.md`
- Historical source date basis: `2026-07-18`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently models `image_generation` as a model-scoped configurable built-in, but
the runtime assumes every selected built-in is provider-hosted. This works for OpenAI
Responses image generation. It does not provide an equivalent capability when the
selected language model is Grok, because xAI exposes image generation through the
separate Imagine API rather than as a hosted tool executed inside the Grok language-model
request.

A user should enable one `image_generation` capability and receive image generation from
any supported model option. The implementation detail must follow the selected provider:
provider-hosted for OpenAI-family models and Azents client-executed for xAI models.

xAI API-key and xAI OAuth integrations must both work in the first release. Credentials
must remain backend-only, generated image bytes must not enter durable event payloads, and
the result must remain available both to the user and to later model calls.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Keep one model-scoped `image_generation` setting in the Agent and Workspace contracts.
- Treat normalized built-in capability as effective product behavior rather than only a
  provider-hosted feature.
- Continue using provider-hosted image generation for supported OpenAI API-key and
  ChatGPT OAuth model options.
- Provide an `image_generation` client function tool for xAI API-key and xAI OAuth model
  options.
- Reuse the selected xAI integration for Grok and Imagine requests without exposing its
  credential to the model or runtime workspace.
- Support proactive OAuth refresh and one forced refresh retry after an Imagine `401`.
- Produce the existing durable generated-image result: Exchange attachment plus
  ModelFile-backed `FileOutputPart` without durable Base64.
- Preserve deterministic tool catalogs and explicit unsupported-capability failures.

## Non-goals

- Adding image editing, image-to-video, or video generation.
- Adding a separate user-selectable Imagine toolkit or image-provider selector.
- Making provider-hosted and client-executed calls share one event kind.
- Discovering account subscription entitlement during every catalog projection.
- Persisting xAI temporary image URLs or xAI Files API identities.
- Adding a Grok model identifier allowlist.
- Changing existing OpenAI generated-image behavior or replay semantics.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
