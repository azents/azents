---
title: "Execute OpenAI Image Generation in Azents"
created: 2026-09-25
tags: [architecture, agent, engine, image-generation]
document_role: primary
document_type: adr
snapshot_id: image-260925
---

# Execute OpenAI Image Generation in Azents

- Snapshot: `image-260925`
- Authority: [image-260925/REQ](../requirements/image-260925-client-executed-openai-generation.md).

## D1 — Client ownership for both OpenAI credential modes

Azents exposes `image_generation` as a client-executed function tool for OpenAI API-key and ChatGPT subscription integrations. The selected integration's credential and endpoint execute one Images API request through the supported OpenAI SDK. The conversation-model request does not advertise provider-hosted image generation; provider-hosted web search and the xAI Imagine path remain unchanged.

This supersedes the hosted image-generation ownership recorded in the historical [hosted-260717 ADR](hosted-260717-hosted-image-generation.md) for these two credential modes only. Other providers retain their existing policy.

**Alternatives rejected:** Keep the hosted tool for one OpenAI credential mode (inconsistent capability and UI semantics); implement custom HTTP for Images API (duplicates supported SDK and authentication handling).

**Risk:** The ChatGPT subscription image endpoint may differ from the public API in entitlement and failure behavior. Exercise the real subscription endpoint before claiming live compatibility; failures must remain visible, never silently fall back to hosted execution. Reuse the existing persisted OAuth refresh when an image request receives a 401, with at most one retry.

## D2 — Model selection and file ownership

The maintained client-tool default follows the Codex-compatible `gpt-image-2` model for both credential modes. An explicit OpenAI API-key image model remains pinned to the configured identifier. ChatGPT subscription stays default-only. Keep all image bytes transient until existing generated-file admission creates its attachment and model file; leave the ordinary client-tool result free of inline image data.

**Alternatives rejected:** Select an implicit conversation-model-specific image generator (not a stable image model); persist Base64 in function results (violates existing storage boundary).

**Risk:** Replacing provider-managed default with the client-maintained concrete model changes which provider image model performs default generation. Administrators retain the existing explicit model choice for supported API-key integrations.
