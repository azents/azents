---
title: "OpenRouter API keys"
created: 2026-07-19
tags: [backend, frontend, engine, security, api, testenv]
---

# OpenRouter API keys

Account-discovered models, credit usage, pricing and native provider execution.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Model catalog](../domain/model-catalog.md)
- [Agent](../domain/agent.md)
- [xAI API keys](xai-api-key.md)

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

## API-Key Credit Usage

The integration and decrypted typed API-key secrets are loaded by one completed
native PostgreSQL read-only repository operation. Missing integration is
classified before foreign-Workspace access, preserving the existing error and
privacy contract. The usage-client call runs only after that read closes. Usage
remains read-through; financial-field authorization, provider transport and
provider/secrets redaction retain their existing contracts.

For an enabled OpenRouter integration, the shared subscription-usage route uses the
official SDK public `api_keys.get_current_key_metadata_async` operation to read the
current key at the fixed provider endpoint:

```text
GET https://openrouter.ai/api/v1/key
Authorization: Bearer <integration API key>
```

The SDK owns request construction; the injected HTTP client's timeout remains
authoritative and SDK retries are disabled. Application normalization validates
the original response's consumed field types and presence, before SDK display
coercion can relax them. Sparse compatible responses rejected only for unrelated
SDK display fields still enter that same bounded decoder. One read dispatches one
provider request, cancellation propagates, and the caller retains HTTP-client
ownership. SDK debug output is disabled.

A bounded key is normalized into one primary credit-limit window. Its consumed percentage is calculated from `limit` and `limit_remaining`; known daily and weekly reset policies retain their approximate window length, while the provider does not supply an exact reset timestamp. Workspace members with integration-write permission can expand financial details for the exact limit, remaining credits, cumulative usage, daily usage, weekly usage, monthly usage, reset policy, and whether BYOK usage counts toward the limit. Read-only members and composer surfaces receive only operational percentage data.

When either `limit` or `limit_remaining` is `null`, Azents treats the key as having no displayable bounded limit. The route returns the controlled `no_credit_limit` outcome without limits or financial details, and both Workspace LLM Settings and composer surfaces render no usage affordance. Provider errors remain integration-local unavailable states and do not disable integration management, model selection, or message submission.

## Account-Scoped Model Catalog

OpenRouter uses an integration-scoped catalog because visibility depends on the API key and account preferences. Catalog synchronization requests:

```text
GET https://openrouter.ai/api/v1/models/user?output_modalities=text
Authorization: Bearer <integration API key>
```

The official OpenRouter SDK public `models.list_for_user_async` operation owns
account-catalog routing, Bearer authentication, and dispatch. The application pins
the Pydantic-compatible official SDK release `0.10.8` through normal dependency
resolution. The injected HTTPX client supplies the text-output query filter and
observes the same response at a typed application-codec boundary. Each listing
uses a 20-second timeout and disables SDK retries; the catalog synchronization
lifecycle owns subsequent retry decisions.

The application codec preserves consumed field presence and sparse records before
SDK display-model validation. A successful HTTP 200 response rejected only by the
SDK response schema still uses the validated application payload. Invalid consumed
catalog evidence and non-200 SDK failures remain errors. This boundary performs
one SDK-owned request and releases both transport and SDK resources, including on
cancellation. SDK debug logging is disabled to protect credentials and payloads.

The provider response is normalized under these rules:

- Every valid account-visible model with text output is eligible for selection.
- The provider model identifier is preserved exactly, for example `anthropic/claude-sonnet-4.6`.
- A generic metadata source match is not required for visibility.
- Unknown publishers map to `model_developer=other`; they never fall back to Anthropic.
- Invalid records are skipped with bounded aggregate diagnostics instead of exposing raw provider payloads.
- Catalog reads use the stored projection and never call OpenRouter on the picker read path.
- Failed refreshes use the common current sync status, retry, backoff, and stale-current-data
  behavior, preserving entries, embedded prices, and last-success time.

Runtime dispatch uses the exact saved provider identifier, for example
`anthropic/claude-sonnet-4.6`, without an execution-library prefix or publisher-path stripping.

## Capability Projection

The account listing preserves architecture modality lists and complete supported
parameter declarations, including absence, null and explicit empty values. The
compiler combines those exact declarations with applicable local source facts and
reviewed implemented-route bounds to produce final schema-3 support fields.
Original evidence gaps and route exclusions remain diagnostic rather than final
unknown states.

Function calling, parallel calls, strict function schemas and structured responses
remain independent. `structured_outputs` is the explicit account response-schema
declaration; a generic format flag or strict function support is not equivalent.
Input/output forms and built-ins are limited to actual implemented product routes.
Conditional final features stay configurable and are constrained by the actual
encoded request at dispatch. Literal publisher paths remain identity, not a
cross-host capability match.

## Runtime Resolution and Request Lowering

Run resolution maps an OpenRouter integration to:

- `api_key=<decrypted API key>`;
- `base_url` set to `https://openrouter.ai/api/v1`;
- `extra_headers={"X-OpenRouter-Title": "Azents"}`;
- the exact provider model identifier, including its publisher path.

Azents does not send `HTTP-Referer` by default and does not add request-level upstream routing or privacy overrides. OpenRouter account and API-key settings remain authoritative for upstream selection and data policy.

OpenRouter execution uses the Pydantic AI public Responses model boundary with an official
OpenAI-compatible SDK client. It retains the Responses API envelope rather than switching to a
Chat Completions wrapper. Canonical transcript, provider-safe failures, usage and saved-candidate
cost normalization remain Azents-owned. Response-handle acquisition has a provider-specific
60-second deadline; parsed-native-event idle and absolute-attempt deadlines remain on the common
policy. Provider-first lowering applies these dialect rules:

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
- Bounded API keys show credit-limit usage in LLM Settings and the selected-model composer affordance.
- API keys with a `null` limit or remaining-limit value render no credit usage affordance.

## Snapshot Semantics

Workspace defaults and Agent model choices resolve through the stored OpenRouter catalog. The resulting snapshot preserves the hosting provider, exact provider model identifier, display name, recognized or neutral developer, family, normalized capabilities, server-owned normalized pricing, source metadata, and refresh time.

Active Agent/Workspace reads and NEW operation preparation compile current exact
authorized LOCAL declarations for the same configured IDs. Reads and unrelated
saves preserve user identities, order, settings and independently saved pricing.
Once an operation exists, retries, quota progression and historical replay retain
its captured capabilities and cursor. Disabled/deleted integration or provider
rejection remains an availability failure rather than a model substitution.

## Security and Verification

- API keys are excluded from public responses, logs, catalog and credit-usage failure messages, source metadata, snapshots, and test evidence.
- The fixed API origin prevents a workspace user from turning provider operations into arbitrary server-side requests.
- Source metadata is bounded and does not retain the raw account catalog response.
- Deterministic tests use fake keys and public product APIs; they do not call OpenRouter or write directly to the product database.
- Deterministic coverage includes provider discovery, secret-safe CRUD, catalog synchronization, exact known and unknown publisher IDs, search, pagination, Workspace defaults, and Agent snapshot selection.
- Runtime tests mock transport and verify fixed credentials, attribution, web-search lowering, cache-control isolation, streaming, usage, and bounded provider failures.
- Live account catalog or inference verification is optional and requires a separately prepared operator credential snapshot.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/services/llm_catalog`](../../../../python/apps/azents/src/azents/services/llm_catalog)
- [`python/apps/azents/src/azents/core/model_provider_declarations.py`](../../../../python/apps/azents/src/azents/core/model_provider_declarations.py)
- [`python/apps/azents/src/azents/engine/events`](../../../../python/apps/azents/src/azents/engine/events)
