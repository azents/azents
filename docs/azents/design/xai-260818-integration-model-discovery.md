---
title: "xAI Integration Model Discovery Design"
created: 2026-08-18
updated: 2026-08-18
implemented: 2026-08-18
tags: [xai, model-catalog, integration, backend, database, testing]
document_role: primary
document_type: design
snapshot_id: xai-260818
---

# xAI Integration Model Discovery Design

- Snapshot: `xai-260818`
- Requirements: [xai-260818/REQ](../requirements/xai-260818-integration-model-discovery.md)
- ADR: [xai-260818/ADR](../adr/xai-260818-integration-model-discovery.md)

## Current Behavior and Gaps

`xai` and `xai_oauth` are currently listed in the system-catalog provider map and are absent from `INTEGRATION_SCOPED_CATALOG_PROVIDERS`. Integration creation therefore does not create or synchronize an xAI catalog, and picker reads fall back to global LiteLLM projections. This fails `xai-260818/REQ-1`, `REQ-2`, and `REQ-6`.

The integration catalog service already owns transactional catalog creation, attempt claiming, cooldown/backoff, last-successful-snapshot preservation, stale refresh, and explicit sync. Existing ChatGPT OAuth, Kimi OAuth, and OpenRouter adapters demonstrate direct provider-authoritative projection. xAI OAuth already has a persisted refresh lifecycle and a credential-safe CLI proxy request identity.

## Architecture and Ownership

- `INTEGRATION_SCOPED_CATALOG_PROVIDERS` owns the scope switch for both xAI providers.
- `model_listing.providers` owns authenticated provider ingress and typed response normalization.
- `IntegrationCatalogProjectionService` owns OAuth refresh, optional LiteLLM enrichment lookup, attempt state, and snapshot publication.
- `LLMCatalogRepository` continues to own SQLAlchemy persistence and stored picker reads.
- xAI owns model existence and supplied capability fields. LiteLLM owns only exact/alias enrichment fields that xAI omitted.

## Provider Listing

### API key

The adapter validates `ApiKeySecrets`, constructs the installed OpenAI-compatible asynchronous client with the integration key and configured xAI developer API base, and calls its public model-list operation. Each valid returned identifier becomes a conservative candidate with text output, xAI developer identity, existing `xai/` runtime routing, and no unverified capability claims.

### OAuth

The service first calls the existing xAI OAuth `ensure_runtime_tokens`. The listing adapter then calls the Grok CLI proxy `/models` endpoint with the refreshed bearer token, account id, pinned client version, client identifier, token-auth marker, and interactive mode. The response is decoded into strict Pydantic ingress models before normalization.

Catalog-safe OAuth fields include model identifier/display name, context window, API backend, reasoning-effort support and levels, backend-search support, and bounded compaction metadata. Provider instructions, tokens, account claims, headers, and unknown raw fields are not persisted.

## Capability Enrichment

For each xAI candidate, projection looks up `xai/<provider model identifier>` in the latest authoritative LiteLLM snapshot. Alias expansion already occurs when that snapshot is ingested.

- If no authoritative source or exact entry exists, the model stays selectable and uses provider-only conservative capabilities.
- If metadata exists, each normalized capability field is filled only when the provider response omitted its corresponding source field.
- Provider values, including explicit false values, win over LiteLLM.
- Provider `supports_backend_search=true` projects semantic `web_search`.
- The existing xAI image-generation policy may use enriched chat/function-calling metadata; it is not inferred when those facts remain unknown.
- Diagnostics record bounded enrichment availability and missing model identifiers without credential material.

## Failure, Retry, and Recovery

Provider adapters wrap expected SDK, HTTP, decoding, and validation failures as `ListingProviderError`.

- `401` and `403`: automatic retry blocked; explicit retry or integration update remains available.
- `429`, timeout/transport, provider `5xx`, and invalid provider response: retryable after existing backoff.
- OAuth refresh failures retain their current rejected/entitlement/transient classification.
- Attempt failure stores sanitized fixed messages and status-derived codes only. It never stores raw SDK exception serialization or provider response bodies.
- Snapshot replacement occurs only after complete listing and projection; any failure preserves the current snapshot.

## Persistence and Migration

A generated Alembic revision:

1. creates empty integration catalogs for every existing `xai` and `xai_oauth` integration that lacks one;
2. deletes both obsolete xAI system catalogs, cascading their snapshots, entries, and attempts through existing foreign keys; and
3. restores empty system catalogs on downgrade without deleting integration catalogs.

No provider credential or model data is copied from the old global catalog because it is not authoritative for any integration.

## API and UI Impact

Public API shapes do not change. Existing catalog entry, sync, status, and picker behavior automatically switch to integration scope through the provider set. Initial creation, credential/configuration update, re-enable, stale reads, and explicit sync reuse existing route behavior.

Admin system-catalog provider enums and tests remove `xai` and `xai_oauth`; only true system providers remain.

## Observability and Security

Attempt diagnostics include provider, integration id, trigger, counts, bounded metadata-match misses, and retry classification. They exclude API keys, access/refresh/id tokens, account ids, email, request headers, raw provider bodies, and raw exception messages that could contain request details.

## Test Strategy

### E2E primary verification matrix

| Scenario | Expected result | Execution |
|---|---|---|
| Create xAI API-key integration | Empty integration catalog is created and initial sync is queued | Deterministic backend route/service test |
| Create xAI OAuth integration | Empty integration catalog is created and initial sync is queued | Deterministic backend OAuth/service test |
| Different credentials | API-key and OAuth listings publish different stored model sets | Deterministic integration projection test |
| Missing LiteLLM entry | Provider-listed model remains selectable with conservative capabilities and safe diagnostics | Deterministic projection test |
| OAuth near expiry | Refresh completes before model listing uses the token | Deterministic service test |
| Provider failure | Last successful snapshot remains and retry block matches status class | Deterministic integration test |
| Secret safety | Attempt diagnostics and public outputs contain no credential values | Deterministic assertion |

### Fixtures and prerequisites

Unit fixtures model the verified OAuth response containing `grok-4.5` and `grok-4.6`, 500,000-token context windows, Responses backend, reasoning support, backend search, and conflicting provider defaults that are normalized without trusting multiple defaults. API-key tests use fake SDK model objects. No live credential is required in CI.

### CI policy

Focused adapter, projection, repository, route, migration, and Living Spec checks must pass in normal CI. Live xAI verification remains optional and must not run without an explicitly supplied credential.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
|---|---|---|---|---|
| xAI entries in system provider map | `xai-260818/ADR-D1` | Integration-scoped provider set and sync dispatch | Backend service constants and admin enum | System catalog list/refresh tests exclude both providers |
| xAI system catalog rows | `xai-260818/ADR-D1` | Empty per-integration catalogs | Generated migration | Migration tests and repository reads show no system fallback |
| LiteLLM-gated xAI visibility | `xai-260818/ADR-D2` | Provider-authoritative direct projection with optional enrichment | Projection service and tests | Missing metadata test remains selectable |
| xAI system-catalog statements in Living Specs | `xai-260818/REQ-1` | Integration-specific discovery behavior | Model catalog and xAI flow specs | Documentation validation and spec review |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
|---|---|---|---|
| M1 | Both xAI providers use integration-scoped stored catalogs | `xai-260818/REQ-1`, `xai-260818/ADR-D1` | required |
| M2 | xAI listing owns existence and LiteLLM is optional fill-only enrichment | `xai-260818/REQ-2`, `REQ-3`, `xai-260818/ADR-D2` | decided |
| M3 | Installed OpenAI-compatible SDK serves API-key discovery; typed CLI-proxy HTTP serves OAuth discovery | `xai-260818/ADR-D3`, external-service SDK convention | decided |
| M4 | OAuth refresh and integration-catalog retry lifecycle are reused unchanged | `xai-260818/REQ-4`, `REQ-5`, `REQ-6`, `xai-260818/ADR-D4` | existing |
| M5 | Migration backfills empty integration catalogs and removes xAI system catalogs | `xai-260818/REQ-1`, `REQ-6`, `xai-260818/ADR-D1` | derived |

## Design Approval

- Mode: `Collaborative`
- Decision owner: `Requester`
- Approved on: `2026-08-18`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5`
- Approved scope: Replace shared xAI system visibility with credential-specific integration catalogs using provider-authoritative discovery and optional conservative LiteLLM enrichment.
