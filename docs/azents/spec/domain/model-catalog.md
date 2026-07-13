---
title: "Model Catalog Domain Spec"
created: 2026-06-21
tags: [backend, frontend, engine]
spec_type: domain
domain: model-catalog
code_paths:
  - python/apps/azents/src/azents/services/llm_catalog/__init__.py
  - python/apps/azents/src/azents/repos/llm_catalog/__init__.py
  - python/apps/azents/src/azents/repos/llm_catalog/data.py
  - python/apps/azents/src/azents/api/public/llm_provider_integration/v1/__init__.py
  - python/apps/azents/src/azents/api/public/llm_provider_integration/v1/data.py
  - python/apps/azents/src/azents/api/admin/model_catalog/v1/__init__.py
  - python/apps/azents/src/azents/services/agent/__init__.py
  - python/apps/azents/src/azents/services/workspace_model_settings/__init__.py
  - python/apps/azents/src/azents/services/model_listing/providers.py
  - typescript/apps/azents-web/src/features/agents/components/ModelCatalogPicker.tsx
  - typescript/apps/azents-web/src/features/agents/containers/useAgentFormContainer.ts
  - typescript/apps/azents-web/src/features/llm-settings/containers/useLlmSettingsContainer.ts
  - typescript/apps/azents-web/src/trpc/routers/llm-provider-integration.ts
last_verified_at: 2026-07-13
spec_version: 6
---

# Model Catalog Domain Spec

## Purpose

The model catalog stores projected model choices for Agent and Workspace model selection. Normal picker and submit paths use stored catalog projections instead of request-time provider model listing.

## Catalog scopes

Catalogs have two ownership scopes.

- System catalog: managed by Azents for providers whose selectable models are not scoped to a customer integration. Current system catalogs cover OpenAI, ChatGPT OAuth fallback, xAI API key, xAI OAuth, Anthropic, and Google Gemini using the active lowerer target projection source.
- Integration catalog: scoped to a provider integration for providers whose visible models depend on customer credential, account, region, or project. Current user-scoped integration catalogs cover AWS Bedrock, ChatGPT OAuth, and Google Vertex AI.

A public model picker starts from an enabled LLM provider integration. Reads first try the integration catalog. If an integration catalog does not exist, the read path falls back to the provider system catalog.

## Stored projection entries

A catalog snapshot contains entries projected into Azents' canonical model contract. Each entry records:

- provider
- optional provider integration id
- provider model identifier
- lowerer target
- runtime model identifier
- display name
- normalized capabilities
- lifecycle status
- visibility status
- publisher and family when known
- source metadata
- projection metadata
- optional hidden reason

Only entries with selectable visibility are returned by the public picker list API.

## Source snapshots and sync attempts

LiteLLM is the current lowerer target projection source. The source sync service records LiteLLM source snapshots before projection. System and integration projections use the stored LiteLLM source snapshot rather than fetching external model metadata from the picker read path.

ChatGPT OAuth integration catalogs additionally fetch the authenticated account-visible model list from the ChatGPT Codex backend during sync. Backend metadata is authoritative for visibility, Responses Lite compatibility, reasoning efforts, modalities, context window, and tool capabilities. ChatGPT entries do not require a matching LiteLLM model metadata key; the LiteLLM source snapshot remains attached to the catalog snapshot because the existing lowerer-target catalog lifecycle requires one.

Reasoning capabilities are projected from LiteLLM's canonical provider model metadata schema. Explicit effort levels are reconstructed in the deterministic order `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`. The optional `none`, `minimal`, `xhigh`, and `max` levels follow their corresponding LiteLLM support flags. Every model marked as reasoning-capable receives the baseline `low`, `medium`, and `high` levels, except that an explicit `supports_low_reasoning_effort: false` removes `low`. A model with no projected effort levels allows no explicit effort override; an empty list is not interpreted as unrestricted support.

Each catalog sync records an attempt with status, counts, failure metadata, action hint, and diagnostics. Failed syncs keep the last successful snapshot available when one exists.

## Public read API

The public catalog entry list endpoint returns the stored catalog entries for one integration. It supports search, limit, and offset. The response includes:

- catalog id
- nullable current snapshot id
- nullable current snapshot creation time
- latest sync attempt, including failure metadata when no successful snapshot exists
- paged entries
- total count
- limit and offset

A catalog with no current snapshot still returns a successful status-aware response when the catalog exists. In that case entries are empty and latest attempt state distinguishes never synced, running, and failed-without-snapshot states.

Selectable entries are ordered by a stored or derived freshness rank before display name and model identifier tie breakers so newer model generations appear first.

The read path must not call provider listing APIs, models.dev, or remote LiteLLM source fetch. Those operations belong to sync paths.

## Sync API

The integration catalog sync endpoint refreshes the stored catalog for one integration.

For AWS Bedrock and Google Vertex AI, sync fetches the provider-visible model list and projects it against the stored LiteLLM source snapshot. For ChatGPT OAuth, sync refreshes the OAuth token when necessary, calls the account-scoped Codex model endpoint with the fixed compatibility client version, and projects backend-visible models directly. Provider credential and permission failures are recorded as sync failure state instead of surfacing as unhandled server errors. User catalog failure diagnostics include a retry policy marker: automatic user-catalog retry is blocked, and retry occurs only through explicit user sync or integration create/update. Successful ChatGPT OAuth connection also queues an initial best-effort catalog sync.

Starting sync while the latest attempt for the catalog is still running returns a conflict instead of creating a duplicate running attempt.

The deterministic E2E fixture integration can sync a deterministic test catalog for stable product tests. This fixture support is not a production provider behavior.

System catalog sync is not user-triggered from the public picker. It is invoked by periodic execution infrastructure and can be operated separately from normal user reads. Admin model catalog operations can list system catalog states, refresh all supported system catalogs, or refresh one supported provider catalog, including the stable `xai` catalog. Every Admin model-catalog operation requires an authenticated Azents user bearer token with a live persisted `system_admin` assignment; no shared machine credential or unauthenticated mode is supported.

## Submit normalization

Agent creation/update and Workspace model settings update accept selectable model option entries. Each entry contains a label plus a model selection input with an LLM provider integration id and provider model identifier. During submit normalization, services resolve every option entry through the stored catalog read service. The resolved catalog entry is copied into the stored Agent or Workspace `AgentModelSelection` snapshot inside that selectable option.

Transition compatibility direct model selection inputs use the same normalization path. If no selectable stored catalog entry matches a requested integration and model identifier, the service rejects the selection. Submit normalization must not refetch a dynamic provider listing as a fallback.

## Snapshot semantics

Agent and Workspace model selections remain snapshots. Catalog changes do not automatically mutate existing selections. UI can surface drift diagnostics between the stored selection snapshot and the current catalog, but runtime selection remains the saved snapshot unless the user changes it.

If an integration is deleted or disabled, runtime or configuration operations can still fail because the credential/config source is unavailable. That is an integration availability failure, not a catalog drift failure.

## Picker behavior

The web picker is integration-first. The form displays the current model summary and opens a model picker modal to change the selection. Forms and settings pages must not prefetch every integration catalog while rendering. The picker lazily reads the selected integration catalog only after the modal is opened and an integration is selected.

The picker shows catalog status and supports search plus infinite-scroll paged loading. It renders provider-independent catalog UI states for no integration selected, loading, never synced, syncing without snapshot, failed without snapshot, ready, ready with latest failed attempt, ready empty result, and loading next page. Failure state renders before empty result state.

For user-scoped integration catalogs, the picker can trigger integration sync. For system catalog fallback entries, public users do not trigger system sync.

## Change History

| Date | Version | Change |
|---|---:|---|
| 2026-07-13 | 6 | Documented live system-administrator authorization for Admin model-catalog operations |
| 2026-07-12 | 5 | Added account-scoped ChatGPT OAuth integration catalogs and backend-authoritative Responses Lite capability projection |
| 2026-07-10 | 4 | Documented canonical LiteLLM reasoning-effort capability projection and strict empty-list semantics |
| 2026-07-10 | 3 | Added the separate xAI API-key system catalog projected from the shared LiteLLM xAI family |
| 2026-07-09 | 2 | Documented selectable model option submit normalization through stored catalog projection |
| 2026-06-21 | 1 | Initial model catalog domain spec |

## Current implementation notes

The current implementation does not use models.dev for model catalog source data. OpenAI and Anthropic provider API listing are not part of the current model catalog path. Current system providers use LiteLLM projection source data for the active lowerer target. ChatGPT OAuth uses its system catalog only before an account-scoped integration catalog exists. The separate `xai` and `xai_oauth` system catalogs are both projected from LiteLLM provider family `xai`; provider-facing identifiers remove the `xai/` prefix, and runtime invocation reconstructs the LiteLLM `xai/` route prefix.
