---
title: "Image Generation Model Selection Requirements"
created: 2026-09-10
updated: 2026-09-10
tags: [agent, workspace, image-generation, model-catalog]
document_role: primary
document_type: requirements
snapshot_id: image-260910
---

# Image Generation Model Selection Requirements

- Snapshot: `image-260910`
- Document reference: `image-260910/REQ`

## Problem

Agent administrators can enable image generation for a selectable conversation model,
but they cannot control which image model performs that work. The current configuration
also cannot distinguish an automatically maintained default from an intentionally pinned
image model or help an administrator recover when a pinned model becomes unavailable.

## Primary Context

### Primary Actor

An Agent administrator configuring a selectable conversation model option.

### Primary Scenario

The administrator enables image generation, chooses either the maintained default or a
specific compatible image model exposed by the selected provider integration, saves the
Agent, and subsequent image-generation calls use that choice.

## Supporting Scenarios or Effects

- A Workspace administrator configures the same behavior in default selectable model
  options copied by newly created Agents.
- An administrator can identify and repair a saved image-model choice that is no longer
  available without Azents silently changing the configured model.

## Goals

- Allow image generation to follow an automatically maintained default.
- Allow an administrator to pin a specific supported image model when the provider
  integration has verified availability evidence.
- Keep available choices scoped to the selected conversation model and its provider
  integration.
- Preserve explicit administrator intent when provider availability changes.
- Avoid live provider requests during ordinary settings rendering.

## Non-Goals

- Adding image quality, size, format, moderation, or editing controls.
- Adding a separate image provider that is independent from the selected conversation
  model integration.
- Adding image, video, or audio generation to providers without an implemented execution
  path.
- Automatically replacing an unavailable saved image model.
- Guaranteeing explicit image-model choices for providers that do not expose a verified
  credential-scoped availability source.

## Requirements

### REQ-1. Provider-aware image model choices

When image generation is enabled for a selectable conversation model option, the
administrator can choose the maintained default and any specific image models that
Azents supports and the selected provider integration can currently expose.

**Acceptance criteria**

- The maintained default is presented as the recommended first choice.
- A specific model appears only when it belongs to the selected provider's supported
  image-model set and has the required integration-scoped availability evidence.
- Providers without verified explicit-model availability expose only the maintained
  default.
- The image-model control is absent when the selected conversation model does not support
  image generation or when image generation is disabled.

### REQ-2. Default-following and explicit pinning

The saved choice distinguishes automatic default following from explicit model pinning,
and image-generation execution honors the saved intent for that selectable model option.

**Acceptance criteria**

- The maintained default follows the provider or Azents maintained default without
  persisting a transient concrete model identifier as user intent.
- A specific selection remains pinned to its saved model identifier until an
  administrator changes it.
- Agent and Workspace default selectable model options preserve the same behavior.
- A new Agent copied from Workspace defaults receives the complete image-generation
  choice.

### REQ-3. Unavailable selection recovery

Azents preserves a saved explicit image-model choice when that model is no longer
available and requires an administrator to resolve the invalid state deliberately.

**Acceptance criteria**

- The unavailable saved model remains visible and is identified as unavailable.
- Azents does not silently replace the unavailable model with the maintained default or
  another specific model.
- The administrator can recover by choosing an available model or disabling image
  generation.
- Saving a configuration that still contains an unavailable explicit choice is rejected
  with an actionable validation result.

### REQ-4. Stored availability lifecycle

Image-model choices are served from stored provider-integration availability state with
bounded refresh, retry, and failure behavior.

**Acceptance criteria**

- Opening Agent or Workspace settings does not synchronously call a provider model-list
  API.
- Stale stored availability can trigger a background refresh.
- A failed refresh preserves the last successful availability snapshot.
- Never-synced, refreshing, stale, and failed states remain distinguishable to the
  settings experience.
- An authorized administrator can explicitly retry synchronization.

### REQ-5. Compatibility and credential protection

Image-model configuration preserves the current provider-specific execution paths and
keeps provider credentials outside user-visible and model-visible state.

**Acceptance criteria**

- Existing provider-default image generation continues to work for supported OpenAI,
  ChatGPT OAuth, xAI API-key, and xAI OAuth conversation models.
- A provider-specific image model identifier is never sent to a different provider's
  execution path.
- Provider credentials are not returned in catalog or Agent configuration responses and
  are not included in model-visible tool configuration.
- Unsupported or invalid image-model configuration fails before provider image
  generation is dispatched.

## Fixed Constraints

- Image generation remains a model-scoped built-in tool setting on each selectable model
  option.
- The selected conversation model must advertise the implemented `image_generation`
  capability before any image-model choice is accepted.
- Explicit availability must be the intersection of an Azents-maintained supported
  image-model registry and credential-scoped provider visibility.
- ChatGPT OAuth and xAI integrations remain default-only until an explicit image-model
  availability source is implemented and verified for those credential modes.
- The initial OpenAI API-key explicit choices are `gpt-image-2.5-flare`, presented as the
  recommended fast everyday choice, and `gpt-image-2.5-sunburst`, presented as the
  highest-capability choice.
- Existing generated-image storage, transcript, attachment, and later-model-input
  behavior must remain unchanged.

## Open Assumptions

- OpenAI API-key integrations are the first credential mode with explicit image-model
  choices because the provider model-list API supplies credential-scoped model
  visibility.
- Registry descriptions and recommendation metadata can evolve without changing a
  saved explicit model identifier.

## Confirmation

Confirmed by the requester on 2026-09-10 before ADR and design decisions began.
