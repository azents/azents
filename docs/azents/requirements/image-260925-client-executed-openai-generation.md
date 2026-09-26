---
title: "Client-Executed OpenAI Image Generation Requirements"
created: 2026-09-25
tags: [agent, engine, image-generation]
document_role: primary
document_type: requirements
snapshot_id: image-260925
---

# Client-Executed OpenAI Image Generation Requirements

- Snapshot: `image-260925`
- Document reference: `image-260925/REQ`

## Problem

OpenAI API-key and ChatGPT subscription Agents currently depend on the conversation provider's hosted image-generation tool. This couples image generation availability to the conversation model's hosted-tool support and differs from the client-executed image-generation path already used for xAI.

## Primary Scenario

An Agent with image generation enabled on a supported OpenAI API-key or ChatGPT subscription conversation model requests an image. Azents executes the image-generation client tool with the selected integration's credential, returns a generated image attachment, and continues the conversation without asking the conversation provider to execute its hosted image-generation tool.

## Goals

- Use an Azents-executed image-generation function tool for both OpenAI API-key and ChatGPT subscription integrations.
- Keep the configured maintained default or explicitly selected image model effective where supported.
- Preserve generated image file admission, attachment delivery, history, and credential secrecy.

## Non-Goals

- Change xAI image generation or provider-hosted web search.
- Expand explicit image-model selection to ChatGPT subscription without a verified availability source.
- Change existing image quality, editing, or moderation controls.

## Requirements

### REQ-1. Both OpenAI credentials execute images as client tools

For supported OpenAI API-key and ChatGPT subscription conversation models, image generation exposes an Azents-executed function tool and no provider-hosted `image_generation` tool.

**Acceptance criteria**

- Both integration modes bind the function tool with their own selected integration credential.
- GPT-6 conversation models that can call client tools can enable image generation even when their provider-hosted image tool is unavailable.
- A client tool call invokes the provider's image-generation endpoint and returns a generated file through existing file admission.
- ChatGPT subscription credentials use a verified supported subscription image-generation endpoint rather than an API-key endpoint that rejects subscription tokens.
- Authentication, provider errors, and cancellation retain safe behavior without exposing credentials or raw image bytes in persisted history.
- ChatGPT subscription image calls remain usable across token expiry through the existing credential refresh path, or require reconnection when refresh fails.

### REQ-2. Preserve image selection and user-visible behavior

The image model used by the client tool honors the existing maintained-default or explicit pinned selection where that selection is supported. The generated image appears to users as an attachment and is available as later model input according to existing file policy.

**Acceptance criteria**

- OpenAI API-key explicit image-model selection remains pinned, including pre-dispatch validation.
- ChatGPT subscription remains maintained-default only until a verified explicit-model availability source exists.
- Image bytes are stored only through existing generated-file admission, never in tool arguments or durable text output.
- Existing xAI execution and hosted web search remain unchanged.

## Fixed Constraints

- Image generation remains a model-scoped built-in tool setting.
- No unverified provider API or hand-written substitute for a supported external-service SDK is introduced without explicit approval.
- Existing implemented Requirements and ADR documents remain immutable.

## Confirmation

Requested by the requester on 2026-09-25 (KST) for ChatGPT subscription, then explicitly extended to OpenAI API-key in the same conversation.
