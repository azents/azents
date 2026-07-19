---
title: "OpenRouter API Key Provider Flow"
created: 2026-07-19
tags: [backend, frontend, engine, security, api, testenv]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, workspace, model-catalog]
code_paths:
  - python/apps/azents/db-schemas/rdb/migrations/versions/7e9b625b4c81_add_openrouter_provider.py
  - python/apps/azents/src/azents/core/credentials.py
  - python/apps/azents/src/azents/core/enums.py
  - python/apps/azents/src/azents/core/llm_mapping.py
  - python/apps/azents/src/azents/core/openrouter.py
  - python/apps/azents/src/azents/api/public/llm_provider_integration/v1/**
  - python/apps/azents/src/azents/repos/llm_provider_integration/**
  - python/apps/azents/src/azents/services/llm_provider_integration/**
  - python/apps/azents/src/azents/services/model_listing/**
  - python/apps/azents/src/azents/services/llm_catalog/**
  - python/apps/azents/src/azents/engine/events/litellm_responses.py
  - python/apps/azents/src/azents/engine/events/responses_lowering.py
  - typescript/apps/azents-web/src/features/llm-settings/**
  - typescript/apps/azents-web/src/features/agents/components/ModelCatalogPicker.tsx
  - testenv/azents/e2e/src/tests/azents/public/test_llm_provider_integration.py
  - testenv/azents/e2e/src/tests/azents/public/test_model_selection.py
last_verified_at: 2026-07-19
spec_version: 1
---

# OpenRouter API Key Provider Flow

## Overview

`openrouter` is a stable workspace-scoped API-key provider. One integration exposes the models available to its authenticated OpenRouter account, including models from publishers that Azents does not recognize. Azents does not maintain a model, publisher, family, or upstream-provider allowlist for OpenRouter visibility.

The provider capability API exposes OpenRouter with credential type `api_key` and `experimental=false`. The LLM Settings UI presents the shared API-key form and explains that OpenRouter account settings own upstream routing, data handling, and zero-data-retention policy.

## Credential and Integration Contract

OpenRouter uses the generic API-key integration shape:

```json
{
  "provider": "openrouter",
  "name": "OpenRouter",
  "secrets": {
    "type": "api_key",
    "api_key": "..."
  },
  "config": null,
  "enabled": true
}
```

Rules:

- The API key is encrypted before persistence and is never included in public create, list, get, or update responses.
- Create and update do not synchronously validate the key with OpenRouter.
- Enabled integration creation, API-key replacement, and re-enable trigger the existing integration-catalog synchronization lifecycle.
- Name-only updates and disable operations do not trigger catalog synchronization.
- The provider API origin is fixed by Azents. No public API or frontend field accepts a custom base URL.
- The PostgreSQL `llm_provider` enum additively includes `openrouter`. Downgrade leaves the enum value in place.

## Account-Scoped Model Catalog

OpenRouter uses an integration-scoped catalog because visibility depends on the API key and account preferences. Catalog synchronization requests:

```text
GET https://openrouter.ai/api/v1/models/user?output_modalities=text
Authorization: Bearer <integration API key>
```

The provider response is normalized under these rules:

- Every valid account-visible model with text output is eligible for selection.
- The provider model identifier is preserved exactly, for example `anthropic/claude-sonnet-4.6`.
- A LiteLLM metadata match is not required for visibility.
- Unknown publishers map to `model_developer=other`; they never fall back to Anthropic.
- Invalid records are skipped with bounded aggregate diagnostics instead of exposing raw provider payloads.
- Catalog reads use the stored projection and never call OpenRouter on the picker read path.
- Failed refreshes use the common catalog-attempt status, retry, backoff, and stale-snapshot behavior.

The runtime model identifier adds the LiteLLM routing prefix to the exact provider identifier, for example `openrouter/anthropic/claude-sonnet-4.6`.

## Capability Projection

Model visibility is broader than capability claims. OpenRouter entries conservatively project only capabilities that Azents can safely normalize from the account listing:

- text and verified image input;
- text output;
- function-tool support;
- reasoning support and available effort levels;
- supported standard generation parameters;
- semantic `web_search` as an effective OpenRouter provider-level capability.

The initial projection does not advertise PDF, audio, video, image output, image generation, prompt caching, or strict structured output. Missing or unverified metadata disables the individual capability without hiding an otherwise valid text-output model.

## Runtime Resolution and Request Lowering

Run resolution maps an OpenRouter integration to:

- `api_key=<decrypted API key>`;
- `base_url` and `api_base` set to `https://openrouter.ai/api/v1`;
- `custom_llm_provider="openrouter"`;
- `extra_headers={"X-OpenRouter-Title": "Azents"}`;
- a runtime model identifier prefixed with `openrouter/`.

Azents does not send `HTTP-Referer` by default and does not add request-level upstream routing or privacy overrides. OpenRouter account and API-key settings remain authoritative for upstream selection and data policy.

OpenRouter execution uses the LiteLLM Responses adapter and the common canonical transcript, streaming, usage, cost, and provider-failure paths. Provider-first lowering applies these dialect rules:

- semantic `web_search` lowers to the OpenRouter Responses tool type `openrouter:web_search`;
- Anthropic cache-control hints are disabled even when the model publisher is Anthropic;
- unknown publishers use neutral behavior and cannot activate Anthropic-specific cache or hosted-tool lowering.

## Frontend Behavior

- OpenRouter appears in the Add integration modal when returned by the provider capability API.
- Creation and secret replacement use the shared API-key form.
- Editing without a replacement key preserves the stored encrypted key.
- The setup guide states that the catalog is account-scoped and that routing, data retention, and ZDR eligibility are controlled in OpenRouter.
- The model picker uses the shared integration-catalog search, pagination, stale, sync, and failure states.
- A manual catalog refresh is available after account policy or model availability changes, subject to the common synchronization policy.

## Snapshot Semantics

Workspace defaults and Agent model choices resolve through the stored OpenRouter catalog. The resulting snapshot preserves the hosting provider, exact provider model identifier, display name, recognized or neutral developer, family, normalized capabilities, source metadata, and refresh time.

Later OpenRouter catalog changes do not mutate existing Agent or Workspace snapshots. Execution can fail when the referenced integration is disabled, deleted, or rejected by OpenRouter; this remains an integration/provider availability failure rather than automatic snapshot replacement.

## Security and Verification

- API keys are excluded from public responses, logs, catalog failure messages, source metadata, snapshots, and test evidence.
- The fixed API origin prevents a workspace user from turning provider operations into arbitrary server-side requests.
- Source metadata is bounded and does not retain the raw account catalog response.
- Deterministic tests use fake keys and public product APIs; they do not call OpenRouter or write directly to the product database.
- Deterministic coverage includes provider discovery, secret-safe CRUD, catalog synchronization, exact known and unknown publisher IDs, search, pagination, Workspace defaults, and Agent snapshot selection.
- Runtime tests mock transport and verify fixed credentials, attribution, web-search lowering, cache-control isolation, streaming, usage, and bounded provider failures.
- Live account catalog or inference verification is optional and requires a separately prepared operator credential snapshot.

## Changelog

| Date | Version | Change | Rationale |
|---|---:|---|---|
| 2026-07-19 | 1 | Documented the stable OpenRouter API-key integration, account catalog, runtime, UI, and security behavior | ADR-0169 and the verified OpenRouter implementation |
