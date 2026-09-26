---
title: "Client-Executed OpenAI Image Generation Design"
created: 2026-09-25
updated: 2026-09-25
tags: [agent, engine, image-generation]
document_role: primary
document_type: design
snapshot_id: image-260925
---

# Client-Executed OpenAI Image Generation Design

- Snapshot: `image-260925`
- Authority: [Requirements](../requirements/image-260925-client-executed-openai-generation.md), [ADR](../adr/image-260925-client-executed-openai-generation.md).
- Revision: 1.

## DESIGN-1 — Tool binding and model transport

`resolve_builtin_tools` routes OpenAI API-key and ChatGPT OAuth `image_generation` to client execution. The Engine binds one auto-scoped function tool using the current Run's selected credential and the validated image-model setting. Only `web_search` remains in the hosted tool list. Existing function-tool call/result handling supplies model continuation and durable events.

## DESIGN-2 — Images request and output

The official OpenAI SDK Images API generates one `gpt-image-2` image for maintained default, or the explicit configured API-key model. The resolved client config supplies the API key, endpoint, organization/project, and ChatGPT account headers already used for the selected conversation integration. Tool arguments expose only a bounded prompt; credentials and model pin are server-owned. The single returned Base64 image is validated and handed to the existing generated-file admission path; the ordinary function result contains no Base64.

## DESIGN-3 — Failures and validation

Runtime model pin validation remains before dispatch. SDK authentication, rate limit, provider status and transport errors map to bounded client-tool failures, without exposing request headers, raw provider bodies, or provider keys. ChatGPT OAuth first retries one image request after forcing the existing persisted token refresh on an image 401; a second 401 requires reconnect. The refreshed token also updates later model turns in this Run. Cancellation propagates. No hosted image-generation fallback occurs on client-tool failure.

## Verification

- Deterministic mock SDK tests for both credential modes, endpoint/headers/model selection, invalid and empty output, and provider failures.
- Engine tests asserting client-tool binding and absence of provider-hosted image generation with existing web search intact.
- Existing generated-file admission tests for attachment, ModelFile, safe persisted transcript, and continuation.
- Focused Ruff, typecheck, and pytest plus live subscription/API image smoke when usable credentials and a Session test environment are available.
