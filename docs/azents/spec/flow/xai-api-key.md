---
title: "xAI API Key Provider Flow"
created: 2026-07-10
tags: [backend, frontend, engine, security, api]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, workspace, model-catalog]
code_paths:
  - python/apps/azents/db-schemas/rdb/migrations/versions/25a661df4ff6_add_xai_api_key_provider.py
  - python/apps/azents/src/azents/core/credentials.py
  - python/apps/azents/src/azents/core/enums.py
  - python/apps/azents/src/azents/core/llm_mapping.py
  - python/apps/azents/src/azents/core/xai.py
  - python/apps/azents/src/azents/api/public/llm_provider_integration/v1/**
  - python/apps/azents/src/azents/api/admin/model_catalog/v1/**
  - python/apps/azents/src/azents/repos/llm_provider_integration/**
  - python/apps/azents/src/azents/services/llm_provider_integration/**
  - python/apps/azents/src/azents/services/llm_catalog/**
  - python/apps/azents/src/azents/engine/events/litellm_responses.py
  - python/apps/azents/src/azents/engine/responses.py
  - python/apps/azents/src/azents/engine/run/resolve.py
  - typescript/apps/azents-web/src/features/llm-settings/**
  - testenv/azents/e2e/src/tests/azents/public/test_llm_provider_integration.py
last_verified_at: 2026-07-10
spec_version: 1
---

# xAI API Key Provider Flow

## Overview

`xai` is the stable workspace-scoped xAI developer API-key provider. It is distinct from the experimental `xai_oauth` provider: both use the xAI inference protocol and model family, but they have independent credentials, billing, setup, entitlement, and refresh lifecycles. A workspace may contain integrations for both providers.

The provider capability API exposes `xai` with credential type `api_key` and `experimental=false`. The LLM Settings UI presents it as **xAI API key** and explains that xAI developer API billing is separate from SuperGrok and X Premium subscriptions.

## Credential and Integration Contract

`xai` uses the generic API-key integration contract:

```json
{
  "provider": "xai",
  "name": "xAI API key",
  "secrets": {
    "type": "api_key",
    "api_key": "..."
  },
  "config": null,
  "enabled": true
}
```

Rules:

- The API key is encrypted in `LLMProviderIntegration` secrets before persistence.
- Public create, list, get, and update responses never include secrets.
- Create and update do not call xAI to validate the key.
- Alias or enabled-state updates may omit `secrets`; the stored encrypted key remains unchanged.
- The existing workspace LLM integration read/write permissions govern the CRUD routes.
- The key is sent to xAI only for an inference call. Internal secret-bearing repository paths may decrypt it for credential resolution but do not validate it against xAI.

The PostgreSQL `llm_provider` enum includes the additive `xai` value. Deployments apply revision `25a661df4ff6` before application instances accept `provider=xai` writes. Rollback may hide or disable the provider but does not remove the PostgreSQL enum value.

## Model Catalog

`xai` has its own system catalog projected from the LiteLLM provider family `xai`. It does not fetch xAI `/v1/models` during integration CRUD or normal picker reads.

The `xai` and `xai_oauth` catalogs are separate stored system catalogs even though they share the same source family. Provider-facing model identifiers omit the LiteLLM `xai/` prefix. Runtime mapping restores that prefix before invocation.

## Runtime Resolution and Request Lowering

Run resolution maps an xAI API-key integration to:

- `api_key=<decrypted API key>`;
- `custom_llm_provider="xai"`;
- `base_url="https://api.x.ai/v1"`;
- `api_base="https://api.x.ai/v1"`;
- runtime model identifier prefixed with `xai/`.

API-key integrations never enter the OAuth token refresh path. Refresh and entitlement-state transitions remain exclusive to `provider=xai_oauth`.

Both xAI provider identities share these transport rules:

- Responses requests use `https://api.x.ai/v1/responses` through LiteLLM.
- System instructions are lowered as the first `system` input item; the top-level `instructions` field is omitted.
- Provider-hosted `web_search` is lowered to the xAI Responses tool target.
- Anthropic cache-control hints are not applied.

A model-call HTTP 403 surfaces as a user-visible provider failure and does not trigger token-expiry refresh handling. In the separate OAuth refresh path, HTTP 403 persists `entitlement_denied` rather than treating the token as merely expired.

LiteLLM HTTP, transport, and typed terminal failures are normalized into the common `ModelProviderFailure` contract. The default presentation preserves only the bounded, redacted provider-authored reason under `Model provider error`; credentials, headers, request/output data, raw bodies, and SDK serialization remain excluded. Every provider-attributed failure receives the complete current Run retry budget regardless of category or diagnostic retryability.

## Frontend Behavior

- `xai` appears in the Add integration modal only when returned by the provider capability API.
- Creation and secret replacement use the shared API-key form.
- Edit without a new key updates non-secret metadata and preserves the stored key.
- Integration rows label `xai` and `xai_oauth` separately.
- Stored API keys are never redisplayed.

## Security and Verification

- Public API responses, fixtures, validation reports, and test evidence exclude API keys and OAuth tokens. Azents-owned application code must not add raw credentials to log fields or messages.
- Deterministic CRUD and catalog tests use fake keys and do not call xAI.
- Runtime lowering tests mock the provider transport.
- Live xAI verification is optional and requires an operator-supplied credential; it is not a deterministic CI prerequisite.

## Changelog

| Date | Version | Change | Rationale |
|---|---:|---|---|
| 2026-07-10 | 1 | Documented the stable xAI API-key integration, catalog, runtime, UI, and security behavior | `docs/azents/design/xai-api-key-provider.md` |
