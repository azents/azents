---
title: "xAI API Key Provider Flow"
created: 2026-07-10
tags: [backend, frontend, engine, security, api]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, workspace, model-catalog]
code_paths:
  - python/apps/azents/src/azents/core/route_capability_constraints.py
  - python/apps/azents/src/azents/core/active_model_capabilities.py
  - python/apps/azents/src/azents/core/model_provider_declarations.py
  - python/apps/azents/src/azents/engine/events/effective_model_request.py
  - python/apps/azents/src/azents/repos/engine_resolve.py
  - python/apps/azents/src/azents/repos/llm_catalog_operations.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/097a97177350_create_operational_schema_baseline.py
  - python/apps/azents/src/azents/core/credentials.py
  - python/apps/azents/src/azents/core/enums.py
  - python/apps/azents/src/azents/core/llm_mapping.py
  - python/apps/azents/src/azents/core/xai.py
  - python/apps/azents/src/azents/api/public/llm_provider_integration/v1/**
  - python/apps/azents/src/azents/api/admin/model_catalog/v1/**
  - python/apps/azents/src/azents/repos/llm_provider_integration/**
  - python/apps/azents/src/azents/services/llm_provider_integration/**
  - python/apps/azents/src/azents/services/llm_catalog/**
  - python/apps/azents/src/azents/services/model_listing/providers.py
  - python/apps/azents/src/azents/engine/events/pydantic_ai_lowering.py
  - python/apps/azents/src/azents/engine/events/pydantic_ai_adapter.py
  - python/apps/azents/src/azents/engine/events/pydantic_ai_output.py
  - python/apps/azents/src/azents/engine/providers/**
  - python/apps/azents/src/azents/engine/responses.py
  - python/apps/azents/src/azents/engine/run/resolve.py
  - typescript/apps/azents-web/src/features/llm-settings/**
  - testenv/azents/e2e/src/tests/required/public/test_llm_provider_integration.py
last_verified_at: 2026-10-04
spec_version: 7
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
- The key is sent to xAI only for model-catalog synchronization and inference. Internal secret-bearing repository paths may decrypt it for those provider calls but do not otherwise validate it against xAI.

The consolidated PostgreSQL baseline includes the `xai` value in the `llm_provider` enum. Application instances accept `provider=xai` writes only when the database is at the current Alembic head.

## Model Catalog

Each `xai` integration has its own stored integration catalog. Enabled creation, API-key replacement, re-enable, stale picker reads, and explicit sync use the shared integration-catalog lifecycle. Synchronization calls xAI's configured developer model endpoint through the installed OpenAI-compatible SDK using that integration's decrypted key.

xAI's response is authoritative for model existence. An exact current source-model
`xai/<model>` entry may fill capabilities omitted by xAI and provide normalized pricing, but a
missing entry never hides the model. Final schema-3 boolean/list fields express
support after exact listing/source declarations and reviewed route bounds are
compiled. Source absence stays diagnostic rather than a final unknown state.
Picker reads use only current stored integration entries and latest sync state and do not call xAI. Runtime uses the same exact raw provider ID;
`xai/` belongs only to the metadata source's lookup vocabulary.

The exact `grok-4.7` identity has a reviewed hosted web-search supplement on the
xAI API inference route. An omitted discovery flag does not suppress that web
contract. Own-provider null with matching-source false still denies web search
without rewriting the null declaration; explicit own false denies it, while own
true retains support over matching generic false. This web supplement and its
guard do not apply to other model IDs or other feature fields.

Selection copies its exact-scope normalized available or unavailable price definition.
Each physical call captures the saved candidate and aware call time without a pricing DB
read, complete source restoration, or native/OAuth cross-host borrowing.

## Runtime Resolution and Request Lowering

Run resolution supplies the decrypted API key and configured xAI endpoint to the
official OpenAI-compatible SDK and public Pydantic Responses model. The model ID
remains the exact configured provider ID; the source's `xai/` prefix is metadata
addressing rather than an execution-library model prefix.

Active same-identity reads and NEW operations compile current authorized LOCAL
metadata. Existing operations retain captured capability/condition snapshots.
Request admission evaluates final support against the actual encoded scalar,
reasoning, tools and output envelope. The canonical seven-level effort domain
excludes raw provider `ultra` declarations without remapping them.

API-key integrations never enter the OAuth token refresh path. Refresh and entitlement-state transitions remain exclusive to `provider=xai_oauth`.

Both xAI provider identities share these transport rules:

- Responses requests use the configured xAI HTTP endpoint (by default
  `https://api.x.ai/v1/responses`) through the public Pydantic AI model boundary and official
  OpenAI-compatible SDK; there is no gRPC mode or transport fallback.
- System instructions are lowered as the first `system` input item; the top-level `instructions` field is omitted.
- Provider-hosted `web_search` is lowered to the xAI Responses tool target.
- Anthropic cache-control hints are not applied.

A model-call HTTP 403 surfaces as a user-visible provider failure and does not trigger token-expiry refresh handling. In the separate OAuth refresh path, HTTP 403 persists `entitlement_denied` rather than treating the token as merely expired.

Official SDK/model HTTP, transport, and typed native-terminal failures enter the common
`ModelProviderFailure` contract only when their typed status or identifiers map to a known category.
The default presentation preserves only the bounded, redacted provider-authored reason under
`Model provider error`; credentials, headers, request/output data, raw bodies, and SDK serialization
remain excluded. Classified provider failures receive the complete current Run retry budget
regardless of diagnostic retryability. Unclassified outcomes remain internal errors. Native
response acquisition, parsed-event progress and successful completion are observed independently
of common model assembly; SDK/model recovery cannot issue a hidden second generation.

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
| 2026-10-03 | 6 | Adopted current catalog/latest sync state and exact saved pricing | Preserve API-key discovery and separate native/OAuth source namespaces |
| 2026-09-30 | 5 | Documented public Pydantic AI/official SDK HTTP Responses execution with raw model IDs | Preserve developer API-key identity and account discovery while removing executable package routing |
| 2026-08-18 | 4 | Moved API-key model visibility to credential-specific integration catalogs with provider-authoritative discovery | [xai-260818/ADR](../../adr/xai-260818-integration-model-discovery.md) |
| 2026-07-18 | 3 | Routed unclassified provider outcomes to internal-error handling without provider retry state | Preserve actionable incident tracebacks instead of generic unknown-provider logs |
| 2026-07-18 | 2 | Applied the bounded common provider-failure contract and complete Run retry budget | [failures-260718/ADR](../../adr/failures-260718-failures-transparent.md) coordinated provider-failure cutover |
| 2026-07-10 | 1 | Documented the stable xAI API-key integration, catalog, runtime, UI, and security behavior | `docs/azents/design/xai-260710-xai-api-key.md` |
