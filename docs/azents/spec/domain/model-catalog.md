---
title: "Model Catalog Domain Spec"
created: 2026-06-21
tags: [backend, frontend, engine]
spec_type: domain
domain: model-catalog
code_paths:
  - python/apps/azents/src/azents/core/llm_catalog.py
  - python/apps/azents/src/azents/core/llm_catalog_sync.py
  - python/apps/azents/src/azents/services/llm_catalog/__init__.py
  - python/apps/azents/src/azents/services/llm_provider_integration/__init__.py
  - python/apps/azents/src/azents/services/chatgpt_oauth/__init__.py
  - python/apps/azents/src/azents/repos/llm_catalog/__init__.py
  - python/apps/azents/src/azents/repos/llm_catalog/data.py
  - python/apps/azents/src/azents/api/public/llm_provider_integration/v1/__init__.py
  - python/apps/azents/src/azents/api/public/llm_provider_integration/v1/data.py
  - python/apps/azents/src/azents/api/admin/model_catalog/v1/__init__.py
  - python/apps/azents/src/azents/services/agent/__init__.py
  - python/apps/azents/src/azents/services/workspace_model_settings/__init__.py
  - python/apps/azents/src/azents/services/model_listing/providers.py
  - python/apps/azents/src/azents/services/builtin_capabilities.py
  - typescript/apps/azents-web/src/features/agents/components/ModelCatalogPicker.tsx
  - typescript/apps/azents-web/src/features/agents/containers/useAgentFormContainer.ts
  - typescript/apps/azents-web/src/features/llm-settings/containers/useLlmSettingsContainer.ts
  - typescript/apps/azents-web/src/trpc/routers/llm-provider-integration.ts
  - typescript/apps/azents-admin-web/src/features/model-catalog/containers/useModelCatalogPageContainer.ts
last_verified_at: 2026-07-19
spec_version: 14
---

# Model Catalog Domain Spec

## Purpose

The model catalog stores projected model choices for Agent and Workspace model selection. Normal picker and submit paths use stored catalog projections instead of request-time provider model listing.

## Catalog scopes

Catalogs have two ownership scopes.

- System catalog: managed by Azents for providers whose selectable models are not scoped to a customer integration. Current system catalogs cover OpenAI, xAI API key, xAI OAuth, Anthropic, and Google Gemini using the active lowerer target projection source.
- Integration catalog: scoped to a provider integration for providers whose visible models depend on customer credential, account, region, or project. Current user-scoped integration catalogs cover AWS Bedrock, ChatGPT OAuth, Google Vertex AI, and OpenRouter.

An integration-scoped catalog is created in the same transaction as its provider integration. Public reads for integration-scoped providers use only that catalog and never fall back to a system catalog. For providers with system-owned model visibility, the picker resolves the provider system catalog through the enabled integration.

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

ChatGPT OAuth integration catalogs additionally fetch the authenticated account-visible model list from the ChatGPT Codex backend during sync. Backend metadata is authoritative for visibility, reasoning efforts, modalities, and context window. Request-dialect hints are excluded from normalized capabilities and stored projection metadata. Following Codex's provider-level capability policy, every API-supported and picker-visible ChatGPT OAuth model is projected with the semantic `web_search` built-in tool capability. `image_generation` is projected only from an explicit trusted source flag or the maintained OpenAI-family model support policy shared with OpenAI system catalog projection. ChatGPT entries do not require a matching LiteLLM model metadata key; the LiteLLM source snapshot remains attached to the catalog snapshot because the existing lowerer-target catalog lifecycle requires one.

OpenRouter integration catalogs fetch the authenticated account-visible text-output model list from the fixed OpenRouter `/models/user` endpoint. Every valid returned model is eligible for direct projection without a model, publisher, family, upstream-provider, or LiteLLM metadata allowlist. Exact provider identifiers are preserved and receive the `openrouter/` runtime prefix. Recognized publisher aliases map to the canonical model developer; an unrecognized publisher maps to `other` and never falls back to Anthropic. OpenRouter capabilities remain conservative: missing or unverified metadata disables an individual capability rather than hiding the model. The initial projection can advertise text and verified image input, text output, function tools, reasoning, standard parameters, and semantic `web_search`; it does not advertise PDF, audio, video, image generation, prompt caching, or strict structured output.

Reasoning capabilities are projected from LiteLLM's canonical provider model metadata schema. Explicit effort levels are reconstructed in the deterministic order `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`. The optional `none`, `minimal`, `xhigh`, and `max` levels follow their corresponding LiteLLM support flags. Every model marked as reasoning-capable receives the baseline `low`, `medium`, and `high` levels, except that an explicit `supports_low_reasoning_effort: false` removes `low`. A model with no projected effort levels allows no explicit effort override; an empty list is not interpreted as unrestricted support.

Built-in tool capability projection is filtered through the implemented configurable registry. The current registry contains `web_search` and `image_generation`; unimplemented identifiers such as `web_fetch` are not advertised. Normalized support represents an effective selectable capability rather than only a provider-hosted feature. Trusted `supports_image_generation: true | false` metadata has first precedence, followed by explicit trusted supported-tool lists. When neither declaration exists, the maintained OpenAI/ChatGPT model policy determines hosted support, while selectable xAI API-key and xAI OAuth entries use chat mode plus function-calling support as the client-executed Imagine fallback. Generic image output modality alone is not evidence of image-tool support. The xAI fallback does not use a Grok model identifier allowlist because Imagine execution is provided by the Azents client tool rather than the selected language-model endpoint. Account credential validity, quota, and Imagine entitlement remain runtime concerns. A future built-in tool becomes selectable only after capability projection, validation, runtime execution ownership, UI presentation, and deterministic coverage exist together.

Each catalog sync records an attempt with status, counts, failure metadata, action hint, and diagnostics. Failed syncs keep the last successful snapshot available when one exists.

## Public read API

The public catalog entry list endpoint returns the stored catalog entries for one integration. It supports search, limit, and offset. The response includes:

- catalog id and ownership scope
- nullable current snapshot id
- nullable current snapshot creation time
- latest sync attempt, including failure metadata when no successful snapshot exists
- stale state, earliest explicit sync time, and automatic-retry-blocked state
- paged entries
- total count
- limit and offset

A catalog with no current snapshot still returns a successful status-aware response when the catalog exists. In that case entries are empty and latest attempt state distinguishes never synced, running, and failed-without-snapshot states.

Selectable entries are ordered by a stored or derived freshness rank before display name and model identifier tie breakers so newer model generations appear first.

The read path must not call provider listing APIs, models.dev, or remote LiteLLM source fetch. It returns the stored response first. When an integration-scoped projection is stale, the route queues a best-effort background refresh whose synchronization policy rechecks eligibility before provider work begins.

## Sync API

The integration catalog sync endpoint refreshes the stored catalog for one integration.

For AWS Bedrock and Google Vertex AI, sync fetches the provider-visible model list and projects it against the stored LiteLLM source snapshot. For ChatGPT OAuth, sync refreshes the OAuth token when necessary, calls the account-scoped Codex model endpoint with the fixed compatibility client version, and projects backend-visible models directly. For OpenRouter, sync calls the fixed authenticated account-model endpoint and projects every valid text-output model directly without requiring a LiteLLM metadata match.

Integration catalog synchronization has four triggers:

- enabled integration creation or successful OAuth connection;
- credential/configuration update or re-enable;
- explicit user sync;
- stale lazy refresh while the integration catalog is actively viewed.

Name-only updates and disable operations do not trigger synchronization. Create/configuration-change triggers bypass cooldown and failure backoff because they represent new provider state, but they do not replace an active attempt. Explicit sync bypasses the credential-failure automatic block while respecting cooldown and transient backoff. Stale refresh respects all policy guards.

Explicit and stale requests use a 30-second integration cooldown and a 5-second workspace cooldown. Retryable provider failures use a 5-minute backoff. A snapshot becomes stale after 15 minutes. A running attempt older than 15 minutes is marked failed and recovered by the next eligible request.

Attempt claim locks the workspace and catalog rows before it evaluates policy and creates the running attempt. This makes duplicate-running and workspace/integration throttle decisions atomic. Attempt completion locks the catalog again and publishes only when the completing attempt is still the catalog's latest attempt, fencing work that was superseded after running-lease recovery. A current running attempt or superseded completion returns conflict; a cooldown or backoff denial returns HTTP 429 with `Retry-After` for explicit requests.

Provider credential, configuration, and permission failures are recorded with `automatic_retry_blocked=true` instead of surfacing as unhandled server errors. Transport, rate-limit, provider 5xx, and invalid-provider-response failures remain eligible for automatic retry after backoff. Unexpected service failures mark the attempt failed before propagating.

The picker disables sync while its mutation is pending, while an attempt is running, and until the server-provided sync availability time. It polls eligible stale/running integration state and stops automatic polling when a credential/configuration failure blocks retry.

The deterministic E2E fixture integration participates in create/update background triggers so stable product tests can verify the lifecycle without live provider credentials. This fixture support is not a production provider behavior.

System catalog sync is not user-triggered from the public picker. It is invoked by periodic execution infrastructure and can be operated separately from normal user reads. Admin model catalog operations can list system catalog states, refresh all supported system catalogs, or refresh one supported provider catalog, including the stable `xai` catalog. Every Admin model-catalog operation requires an authenticated Azents user bearer token with a live persisted `system_admin` assignment; no shared machine credential or unauthenticated mode is supported.

## Submit normalization

Agent creation/update and Workspace model settings update accept selectable model option entries. Each entry contains a label, a model selection input with an LLM provider integration id and provider model identifier, and optional model-scoped settings. During submit normalization, services resolve every option entry through the stored catalog read service. The resolved catalog entry is copied into the stored Agent or Workspace `AgentModelSelection` snapshot, then the option settings are defaulted and validated against that snapshot's implemented capabilities. Omitted built-in tool intent enables every supported implemented tool; an explicit empty list preserves all-off intent.

Transition compatibility direct model selection inputs use the same normalization path. If no selectable stored catalog entry matches a requested integration and model identifier, the service rejects the selection. Submit normalization must not refetch a dynamic provider listing as a fallback.

## Snapshot semantics

Agent and Workspace model selections remain snapshots. Catalog changes do not automatically mutate existing selections. UI can surface drift diagnostics between the stored selection snapshot and the current catalog, but runtime selection remains the saved snapshot unless the user changes it.

If an integration is deleted or disabled, runtime or configuration operations can still fail because the credential/config source is unavailable. That is an integration availability failure, not a catalog drift failure.

## Picker behavior

The web picker is integration-first. The form displays the current model summary and opens a model picker modal to change the selection. Forms and settings pages must not prefetch every integration catalog while rendering. The picker lazily reads the selected integration catalog only after the modal is opened and an integration is selected.

The picker shows catalog status and supports search plus infinite-scroll paged loading. It renders provider-independent catalog UI states for no integration selected, loading, never synced, syncing without snapshot, failed without snapshot, ready, ready with latest failed attempt, ready empty result, and loading next page. Failure state renders before empty result state.

For user-scoped integration catalogs, the picker can trigger integration sync. For providers backed by system catalogs, public users do not trigger system sync.

## Change History

| Date | Version | Change |
|---|---:|---|
| 2026-07-19 | 14 | Added direct account-scoped OpenRouter model projection with unrestricted valid model visibility and conservative capability claims |
| 2026-07-18 | 13 | Projected effective `image_generation` capability onto selectable function-calling xAI API-key and OAuth chat entries |
| 2026-07-17 | 12 | Restored trusted `image_generation` capability projection for supported OpenAI-family catalog entries |
| 2026-07-16 | 11 | Removed the Responses Lite capability and request-dialect metadata from ChatGPT OAuth catalog projections |
| 2026-07-16 | 10 | Completed create, configuration-update, explicit, and stale-refresh synchronization policy with atomic throttling, backoff, and picker status behavior |
| 2026-07-16 | 9 | Scoped selectable settings to catalog-resolved options and limited advertised built-in tools to implemented contracts |
| 2026-07-16 | 8 | Projected `web_search` for every selectable ChatGPT OAuth model under the Codex provider capability policy |
| 2026-07-14 | 7 | Removed the ChatGPT OAuth system catalog and made integration catalogs authoritative from integration creation |
| 2026-07-13 | 6 | Documented live system-administrator authorization for Admin model-catalog operations |
| 2026-07-12 | 5 | Added account-scoped ChatGPT OAuth integration catalogs and backend-authoritative Responses Lite capability projection |
| 2026-07-10 | 4 | Documented canonical LiteLLM reasoning-effort capability projection and strict empty-list semantics |
| 2026-07-10 | 3 | Added the separate xAI API-key system catalog projected from the shared LiteLLM xAI family |
| 2026-07-09 | 2 | Documented selectable model option submit normalization through stored catalog projection |
| 2026-06-21 | 1 | Initial model catalog domain spec |

## Current implementation notes

The current implementation does not use models.dev for model catalog source data. OpenAI and Anthropic provider API listing are not part of the current model catalog path. Current system providers use LiteLLM projection source data for the active lowerer target. ChatGPT OAuth has no system catalog; its account-scoped integration catalog is the only model-visibility source. OpenRouter also has no system catalog; its authenticated integration catalog is authoritative for model visibility and does not require LiteLLM metadata matching. The separate `xai` and `xai_oauth` system catalogs are both projected from LiteLLM provider family `xai`; provider-facing identifiers remove the `xai/` prefix, and runtime invocation reconstructs the LiteLLM `xai/` route prefix.
