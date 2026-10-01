---
title: "Model Catalog Domain Spec"
created: 2026-06-21
tags: [backend, frontend, engine]
spec_type: domain
domain: model-catalog
code_paths:
  - python/apps/azents/src/azents/core/model_execution_options.py
  - python/apps/azents/src/azents/core/openai_client_config.py
  - python/apps/azents/src/azents/core/model_metadata_source.py
  - python/apps/azents/src/azents/core/model_pricing.py
  - python/apps/azents/src/azents/services/model_metadata.py
  - python/apps/azents/src/azents/services/model_metadata_source.py
  - python/apps/azents/src/azents/services/model_metadata_projection.py
  - python/apps/azents/src/azents/core/agent.py
  - python/apps/azents/src/azents/core/llm_catalog.py
  - python/apps/azents/src/azents/core/llm_catalog_sync.py
  - python/apps/azents/src/azents/core/image_generation_catalog.py
  - python/apps/azents/src/azents/core/image_generation_config.py
  - python/apps/azents/src/azents/services/llm_catalog/__init__.py
  - python/apps/azents/src/azents/services/image_generation_catalog/**
  - python/apps/azents/src/azents/services/llm_provider_integration/__init__.py
  - python/apps/azents/src/azents/services/chatgpt_oauth/__init__.py
  - python/apps/azents/src/azents/services/kimi_oauth/**
  - python/apps/azents/src/azents/repos/llm_catalog/__init__.py
  - python/apps/azents/src/azents/repos/llm_catalog/data.py
  - python/apps/azents/src/azents/repos/model_metadata_source.py
  - python/apps/azents/src/azents/repos/model_metadata_source_data.py
  - python/apps/azents/src/azents/rdb/models/llm_catalog.py
  - python/apps/azents/src/azents/rdb/models/model_metadata_source.py
  - python/apps/azents/src/azents/engine/providers/model_profiles.py
  - python/apps/azents/src/azents/scheduler/registry.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/097a97177350_create_operational_schema_baseline.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/4550a9c9083a_remove_catalog_execution_descriptors.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/91dd4bb71ef6_add_model_metadata_source_shadow_schema.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/d29225579621_remove_legacy_litellm_metadata_authority.py
  - python/apps/azents/src/azents/api/public/llm_provider_integration/v1/__init__.py
  - python/apps/azents/src/azents/api/public/llm_provider_integration/v1/data.py
  - python/apps/azents/src/azents/api/admin/model_catalog/v1/__init__.py
  - python/apps/azents/src/azents/services/agent/__init__.py
  - python/apps/azents/src/azents/services/workspace_model_settings/__init__.py
  - python/apps/azents/src/azents/services/model_listing/providers.py
  - python/apps/azents/src/azents/services/model_options.py
  - python/apps/azents/src/azents/core/builtin_tools.py
  - python/apps/azents/src/azents/engine/run/tool_budget.py
  - python/apps/azents/src/azents/engine/events/engine_adapter.py
  - typescript/apps/azents-web/src/features/agents/components/ModelCatalogPicker.tsx
  - typescript/apps/azents-web/src/features/agents/components/SelectableModelOptionsEditor.tsx
  - typescript/apps/azents-web/src/features/agents/containers/useAgentFormContainer.ts
  - typescript/apps/azents-web/src/features/agents/containers/useImageGenerationCatalogs.ts
  - typescript/apps/azents-web/src/features/llm-settings/containers/useLlmIntegrationsContainer.ts
  - typescript/apps/azents-web/src/features/llm-settings/containers/useWorkspaceModelSettingsContainer.ts
  - typescript/apps/azents-web/src/trpc/model-settings-input-schemas.ts
  - typescript/apps/azents-web/src/trpc/routers/llm-provider-integration.ts
  - typescript/apps/azents-web/src/trpc/routers/workspace-model-settings.ts
  - typescript/apps/azents-admin-web/src/features/model-catalog/containers/useModelCatalogPageContainer.ts
last_verified_at: 2026-10-01
spec_version: 33
---

# Model Catalog Domain Spec

## Purpose

The model catalog stores projected model choices for Agent and Workspace model selection. Normal picker and submit paths use stored catalog projections instead of request-time provider model listing.

## Catalog scopes

Catalogs have two ownership scopes and an explicit purpose. The catalog identity
includes `purpose = conversation | image_generation`, so one integration can own
independent conversation and image-generation snapshots without sharing entries,
attempts, or publication state.

- System catalog: managed by Azents for providers whose selectable models are not scoped to a customer integration. Current system catalogs cover OpenAI, Anthropic, and Google Gemini using the selected generic `genai_prices` source snapshot.
- Integration catalog: scoped to a provider integration for providers whose visible models depend on customer credential, account, region, or project. Current user-scoped integration catalogs cover AWS Bedrock, ChatGPT OAuth, xAI API key, xAI OAuth, Kimi OAuth, Google Vertex AI, and OpenRouter.

An integration-scoped catalog is created in the same transaction as its provider integration. Public reads for integration-scoped providers use only that catalog and never fall back to a system catalog. For providers with system-owned model visibility, the picker resolves the provider system catalog through the enabled integration.

Catalog identity is semantic rather than execution-library-specific. System catalogs are unique by
`(provider, purpose)` and integration catalogs by `(provider_integration_id, purpose)` within their
respective ownership scopes. Catalogs, conversation entries, public responses, active projection
metadata, and newly created selection diagnostics do not carry `lowerer_target` or a stored
`runtime_model_identifier`. Dispatch uses the saved provider and exact provider model ID.

Migration `4550a9c9083a` checks target-free identity collisions before removing the old dimensions;
it does not merge catalogs or recreate IDs. Existing catalog/source/snapshot/attempt links and
image-generation purpose separation remain intact. Historical Agent diagnostic snapshots and
native conversation artifacts remain historical evidence, not execution inputs.

The new catalog cutover follows current-main schema revision `43a0fbdc96fe`
directly, preserving one linear migration chain and leaving existing main
migrations unchanged.

## Stored projection entries

A catalog snapshot contains entries projected into Azents' canonical model contract. Each entry records:

- provider
- optional provider integration id
- provider model identifier
- display name
- normalized capabilities
- lifecycle status
- visibility status
- publisher and family when known
- source metadata
- projection metadata
- optional hidden reason

Only entries with selectable visibility are returned by the public picker list API.

The normalized context-window capability stores nullable
`default_input_tokens`, nullable `max_input_tokens`, and nullable
`max_output_tokens`. The default is the ordinary runtime input window, while the
maximum is the hard ceiling for an explicit Agent option cap. A maximum-only
capability, including historical catalog and Agent snapshots, resolves that maximum
as its default. The capability remains additive JSON and requires no relational
migration.

Runtime and Agent context displays supplement only a missing maximum from an exact model match in
the locally captured validated source. A known provider default is a floor for this fallback;
when default, maximum and source maximum are all missing, the resolved limit is 128,000 tokens.
Saved maximums win over source data and no SDK profile changes a saved capability. A paired
foreground/lightweight budget shares one source capture; an Agent list shares a capture across
all displayed Agents needing fallback instead of fetching one payload per candidate.

### Image-generation entries

Image-generation catalogs use a separate entry table because their reviewed
metadata and lifecycle do not represent conversation-model capabilities. An entry
records the provider integration, exact provider model identifier, display name,
description, recommendation rank, lifecycle, visibility, source metadata, and
projection metadata.

Explicit image-model selection is currently supported only for enabled OpenAI
API-key integrations. A code-owned reviewed registry is intersected with exact
credential-visible identifiers returned by the official OpenAI model-list SDK
operation. The initial registry contains `gpt-image-2.5-flare` at recommendation
rank 1 and `gpt-image-2.5-sunburst` at rank 2. Provider-visible identifiers absent
from the registry are not selectable, and registry entries absent from the
credential-visible response are not published.

OpenAI API key, ChatGPT OAuth, xAI API key, and xAI OAuth support a maintained
provider default while their integration is enabled. The default is synthetic
Azents behavior represented by omitting `config.model`; it is not stored as a
catalog entry or discovered provider identifier. ChatGPT OAuth and both xAI
providers are default-only and return no explicit image catalog entries.

## Switchable model execution options

Execution options are a separate class from static `ModelCapabilities` and built-in
tools. A code-owned definition registry assigns stable option IDs and boolean
control semantics. Catalog entries and saved `AgentModelSelection` snapshots carry
`supported_execution_options` independently of normalized capabilities; inference
profiles carry the user's `enabled_execution_options` independently of support.
Fast (`fast`) and Ultrafast (`ultrafast`) belong to the code-owned
`processing_speed` exclusivity group. A model may support both members, but an
enabled profile may contain at most one. Normal is the empty group selection,
not another persisted option ID. Support-list validation is separate from enabled
preference validation, so enumerating both supported definitions is valid.

OpenAI API support is projected from reviewed exact model identifiers grounded in
the provider's documentation. Ultrafast is reviewed for the exact `gpt-6-astra`
and preview-access `gpt-5.6-sol` IDs. Unreviewed aliases, suffix variants,
fine-tuned models, and other OpenAI-compatible providers do not acquire support
through a prefix match. ChatGPT OAuth support comes from the connected account's
current `service_tiers` declarations: `priority` or `fast` advertises Fast, and
exact `ultrafast` independently advertises Ultrafast. Missing, empty, malformed,
or unrelated declarations do not advertise an option. Support is not an account-entitlement, quota,
regional-availability, cost, or latency guarantee.

Public response projections expose code-owned option definitions separately from
persisted IDs, including display text, a qualitative provider-specific cost hint,
the `"boolean"` control discriminator, and required nullable `exclusive_group`
relationship metadata. Agent public selectable-option responses
include these definitions for the composer. Definition metadata is not written into
saved model selection JSON and does not become a second support authority.

Catalog projection and selection normalization explicitly copy supported IDs.
Existing catalog rows and historical saved selections without this field start with
no supported execution options. Catalog synchronization followed by model
reselection creates a support-aware Agent snapshot; reads and execution do not
upgrade old snapshots from raw metadata or refetch provider catalogs. Newly enabling
Fast or Ultrafast always requires explicit user intent and never changes built-in
tool settings. API-key hints describe additional API cost; OAuth hints describe
additional ChatGPT usage/credits. Ultrafast hints disclose unavailable cost
estimation without promising entitlement, billing multipliers, or latency.

## Source snapshots and sync attempts

The public `genai-prices` snapshot is the current projection, context, and
estimated-pricing metadata source. Azents calls the package's public fetch
operation, decodes its typed provider and model records through an isolated
adapter, and stores a canonical content-addressed generic source snapshot before
catalog projection. Each snapshot records source kind, fetch time, content hash,
model count, source schema version, dependency provenance, canonical provider and
model records, and the validated pricing payload required for isolated
request-time evaluation.

The latest explicitly selected generic DB snapshot is authoritative. Transport,
decoding, validation, supersession, or material-reduction failure records bounded
attempt diagnostics and leaves the previous successful snapshot authoritative.
The adapter never makes normal reads depend on package-global state or a remote
fetch. The previous metadata source schema, rows, configuration, and projection
code are absent from the active system.

The six-hour `model_catalog_system_projection` task calls the public
`genai-prices` fetch operation through the Azents-owned adapter, validates and
canonicalizes provider/model matching, context, lifecycle, and pricing rules, and
selects the current generic source snapshot. Failed, malformed, superseded, or
materially reduced collection retains the previous source and current catalogs.
Normal reads and dispatch never fetch metadata remotely or consult package-global
state.

System refresh resolves OpenAI, Anthropic, and Gemini through the same
credential-free runtime profile resolver used by model construction. It creates a
complete candidate with source, dependency, resolver, and policy provenance, then
publishes it atomically. A provenance mismatch or publication failure leaves the
current pointer unchanged. Superseded snapshots are deleted after successful
publication.

Integration sync retains provider listing as visibility authority, captures the
current generic source locally, and projects every provider-visible exact model
through the shared runtime resolver. A missing source match never hides a
provider-visible model. Publication records generic projection provenance and is
fenced by the claimed attempt, the current snapshot, and the integration's
`catalog_configuration_version`. The temporary migration reprojection task is
removed after every current conversation catalog carries generic provenance.

Runtime context fallback and estimated cost capture the same generic source
snapshot once per logical operation. Matching uses the persisted canonical source
rules, and price evaluation reconstructs an isolated typed source view at the
captured request time. Missing or unsupported evidence remains nullable; a
provider-reported charge continues to take precedence over a local estimate.

ChatGPT OAuth integration catalogs additionally fetch the authenticated account-visible model list from the ChatGPT Codex backend during sync. Backend metadata is authoritative for visibility, reasoning efforts, modalities, and context window. `context_window` projects to the default input window and `max_context_window` projects to the maximum; when the maximum is absent, the default also supplies the maximum. Request-dialect hints are excluded from normalized capabilities and stored projection metadata. Following Codex's provider-level capability policy, every API-supported and picker-visible ChatGPT OAuth model is projected with the semantic `web_search` built-in tool capability. `image_generation` is projected only from an explicit trusted source flag or the maintained OpenAI-family model support policy shared with OpenAI system catalog projection. ChatGPT entries do not require a matching generic source model record.

OpenRouter integration catalogs fetch the authenticated account-visible text-output model list from the fixed OpenRouter `/models/user` endpoint. Every valid returned model is eligible for direct projection without a model, publisher, family, upstream-provider, or generic metadata allowlist. Exact provider identifiers, including publisher paths, are preserved without an execution-library prefix. Recognized publisher aliases map to the canonical model developer; an unrecognized publisher maps to `other` and never falls back to Anthropic. OpenRouter capabilities remain conservative: missing or unverified metadata disables an individual capability rather than hiding the model. The initial projection can advertise text and verified image input, text output, function tools, reasoning, standard parameters, and semantic `web_search`; it does not advertise PDF, audio, video, image generation, prompt caching, or strict structured output.

xAI API-key integration catalogs call the configured developer API through the installed OpenAI-compatible SDK. xAI OAuth integration catalogs refresh the stored OAuth credential when required and then call the authenticated Grok CLI proxy model endpoint with the pinned CLI request identity. Each response is authoritative only for that integration, so API-key and OAuth integrations may publish different model sets. Every valid provider-listed model remains selectable without a generic source match. Provider-supplied context window, reasoning-effort, backend-search, and Responses-backend values narrow the shared runtime capability ceiling; an exact canonical `x-ai` source match may fill context and pricing evidence. Missing source authority and exact-match misses remain diagnostic and leave unknown capabilities disabled.

Reasoning capabilities and explicit effort levels come from the shared runtime profile resolver and provider-listing narrowing. Native OpenAI uses the deployed profile's `none` and `minimal` flags plus its supported baseline levels; Anthropic exposes explicit levels only when its exact profile supports effort; Gemini exposes only levels that have an Azents lowerer mapping. Vertex follows its resolved Google or Anthropic protocol rather than the hosting provider label. A model with no projected effort levels allows no explicit effort override; an empty list is not interpreted as unrestricted support.

Built-in tool capability projection is filtered through the implemented configurable registry. The current registry contains `web_search` and `image_generation`; unimplemented identifiers such as `web_fetch` are not advertised. Normalized support represents an effective selectable capability rather than only a provider-hosted feature. OpenAI API-key and ChatGPT OAuth GPT-6, GPT-5, GPT-4.1, GPT-4o, and o3 chat models expose client-executed image generation when function calling is not denied; trusted supported-tool lists can additionally establish support for another OpenAI model. Provider metadata that disables the hosted image tool does not disable this client tool. Other providers honor trusted `supports_image_generation: true | false` metadata before supported-tool lists. Selectable xAI API-key and xAI OAuth entries use chat mode plus function-calling support for client-executed Imagine. Generic image output modality alone is not evidence of image-tool support. Account credential validity, quota, and image-service entitlement remain runtime concerns. A future built-in tool becomes selectable only after capability projection, validation, runtime execution ownership, UI presentation, and deterministic coverage exist together.

Each catalog sync records an attempt with status, counts, failure metadata, action hint, and diagnostics. Failed syncs keep the last successful snapshot available when one exists.

Integration catalogs and their attempts carry the integration's positive
`catalog_configuration_version`. Credential/configuration changes advance that
version. An image sync publishes only when its claimed attempt is still latest and
its version still matches the integration. The last successful snapshot remains
diagnostic after a generation change or failed sync, but `generation_current =
false` prevents it from authorizing new saves or runtime dispatch.

## Local operation metadata and pricing

Context fallback and cost estimation read a locally captured validated source snapshot
through `ModelMetadataService`, never an installed model map, library profile or
request-time remote source fetch. Exact provider/source namespaces and expanded aliases
are distinct from execution encoding; publisher paths and cloud resource identifiers are
not stripped. Saved normalized capabilities retain their existing precedence and default
floor. Paired context calculations share one snapshot, and known maxima skip source reads.

Pricing normalization is separate from capability projection. It captures snapshot identity,
exact model/source key and the generic source's conditional token, cache, context-threshold,
tool, and media rules for the operation. The current generic contract has no provider
service-tier price dimension, so local Priority, Ultrafast, and other premium estimates
remain `null` rather than using Standard prices. Unavailable or unsupported required
pricing remains `null` rather than a zero, partial total, or execution failure.
Provider-returned charges and estimates retain distinct provenance. Optional
metadata/pricing misses do not change model visibility or saved selections.

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

The read path must not call provider listing APIs, models.dev, or the remote metadata source. It returns the stored response first. When an integration-scoped projection is stale, the route queues a best-effort background refresh whose synchronization policy rechecks eligibility before provider work begins.

The image-generation catalog read endpoint returns `default_available`,
`explicit_selection_supported`, generation/version state, the latest attempt, and
the ordered complete entry list for one integration. Standard Agent and Workspace
reads never perform image-model discovery. Default-only providers receive a
successful synthetic response without creating a discovery catalog.

## Sync API

The integration catalog sync endpoint refreshes the stored catalog for one integration.

The separate image-generation sync endpoint is available only to a Workspace Owner
for OpenAI API-key integrations. It applies the same running-attempt, integration
cooldown, workspace cooldown, retry backoff, stale threshold, recovery, and
superseded-completion policy as the conversation catalog. Enabled integration
creation and catalog-affecting updates trigger initial image sync in addition to
conversation sync; name-only updates and disable operations do not.

For AWS Bedrock and Google Vertex AI, sync fetches the provider-visible model list and projects it against the stored generic metadata source snapshot. For ChatGPT OAuth, sync refreshes the OAuth token when necessary, calls the account-scoped Codex model endpoint with the fixed compatibility client version, and projects backend-visible models directly. For xAI API key, sync calls the developer model endpoint with that integration's key. For xAI OAuth, sync refreshes the token when necessary and calls the Grok account model endpoint. Both xAI paths project provider visibility directly and use generic metadata only as optional fill-only enrichment. For Kimi OAuth, sync refreshes the token when necessary, calls the authenticated Kimi Code model endpoint with the encrypted device identity, and directly projects valid account-visible models. For OpenRouter, sync calls the fixed authenticated account-model endpoint and projects every valid text-output model directly without requiring a generic metadata match.

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

System catalog sync is not user-triggered from the public picker. It is invoked by periodic execution infrastructure and can be operated separately from normal user reads. Admin model catalog operations can list system catalog states, refresh all supported system catalogs, or refresh one supported system provider catalog. xAI catalogs are integration-owned and are refreshed only through the public integration lifecycle. Every Admin model-catalog operation requires an authenticated Azents user bearer token with a live persisted `system_admin` assignment; no shared machine credential or unauthenticated mode is supported.

## Submit normalization

Agent creation/update and Workspace model settings update accept selectable semantic labels with one
to five ordered physical candidates. Each candidate contains a model selection input with an LLM
provider integration ID and provider model identifier plus optional model-scoped settings. During
submit normalization, services resolve every candidate through the stored catalog read service. The
resolved catalog entry is copied into the stored Agent or Workspace `AgentModelSelection` snapshot,
then that candidate's settings are defaulted and validated against its implemented capabilities.
Omitted built-in tool intent enables every supported implemented tool; an explicit empty list
preserves all-off intent. The first candidate is Primary, and Primary capabilities alone define the
label's normal Composer effort and execution-option controls.

An enabled `image_generation` setting additionally validates its complete config
against the selected conversation snapshot and the selected integration. An
omitted image model accepts the maintained default only for supported enabled
providers. An explicit model requires an OpenAI API-key integration, an executable
reviewed registry entry, a current-generation catalog snapshot, and a matching
selectable entry. Agent and Workspace save paths share this validation, and
Workspace defaults copy the complete built-in configuration into newly created
Agents.

If no selectable stored catalog entry matches a requested candidate integration and model identifier,
the service rejects the candidate. Public mutation has no direct singular model-selection
compatibility field. Submit normalization must not refetch a dynamic provider listing as a fallback.

## Snapshot semantics

Agent and Workspace model selections remain snapshots. Catalog changes do not automatically mutate existing selections. UI can surface drift diagnostics between the stored selection snapshot and the current catalog, but runtime selection remains the saved snapshot unless the user changes it.

If an integration is deleted or disabled, runtime or configuration operations can still fail because the credential/config source is unavailable. That is an integration availability failure, not a catalog drift failure.

The effective provider-request tool declaration limit is the narrow exception to saved selection snapshot authority when the current Agent has Tool Search enabled. On that enabled path, runtime resolves a reviewed rule before each prepared model call from the current provider, adapter/native request path, runtime model identifier, model developer, and normalized family. The code-owned compatibility registry is authoritative for this transport constraint so a previously saved `AgentModelSelection` cannot freeze a stale hard limit. Exact-model rules take precedence over family rules and family rules over endpoint rules; an equally specific overlap is invalid configuration. When Tool Search is disabled, runtime preserves the complete legacy client-tool catalog and does not apply registry projection.

The current registry applies xAI's documented 200 total-tools request ceiling and a conservative 128 function-declaration ceiling only to Vertex AI request paths targeting Google/Gemini models. The Vertex rule records the conflicting official 128 and 512 sources and their verification date. Direct Gemini API requests and Vertex-hosted Anthropic or other non-Google models remain unmatched. When no verified rule matches, the limit is absent and runtime does not invent a product-wide fallback cap. All other normalized capabilities, supported built-ins, limits, and settings retain normal saved-snapshot semantics.

## Picker behavior

The web picker is integration-first. The form displays the current model summary and opens a model picker modal to change the selection. Forms and settings pages must not prefetch every integration catalog while rendering. The picker lazily reads the selected integration catalog only after the modal is opened and an integration is selected.

The picker shows catalog status and supports search plus infinite-scroll paged loading. It renders provider-independent catalog UI states for no integration selected, loading, never synced, syncing without snapshot, failed without snapshot, ready, ready with latest failed attempt, ready empty result, and loading next page. Failure state renders before empty result state.

Each model card displays the resolved default context value
`default_input_tokens ?? max_input_tokens`. When a distinct default and maximum
both exist, the badge displays both values. The Agent option settings modal
describes the default used when its cap is empty and the catalog maximum used for
runtime clamping. Maximum-only snapshots retain the existing concise single-value
presentation.

For user-scoped integration catalogs, the picker can trigger integration sync. For providers backed by system catalogs, public users do not trigger system sync.

The selectable-model settings modal reads stored image catalog state for each
selected integration without embedding a frontend model registry. When explicit
selection is supported, enabling image generation exposes the maintained default
first and then current stored entries in recommendation order. Default-only
providers retain the image-generation capability toggle but expose no image-model
selection controls. The UI preserves an unavailable saved explicit identifier,
blocks submission until it is recovered, and distinguishes loading, initial or
refresh failure, generation-changed, never-synced, stale, and empty catalog states.
Only Workspace Owners receive the explicit image sync action.

## Change History

| Date | Version | Change |
|---|---:|---|
| 2026-10-01 | 33 | Removed the former metadata source schema, rollback pins, temporary reprojection task, and compatibility code after validating generic provenance on every current conversation catalog. |
| 2026-10-01 | 32 | Cut over system publication, integration projection, runtime context fallback, and estimated pricing to generic genai-prices authority with rollback pins and bounded network-free integration reprojection. |
| 2026-10-01 | 31 | Added independent genai-prices source shadow collection, shared runtime profile resolution, generic source persistence, non-current replacement candidates, and inert rollback/projection provenance without changing current catalog authority. |
| 2026-09-30 | 29 | Removed active execution-library catalog descriptors and documented semantic identity, preserved historical/source links, and exact raw provider IDs. |
| 2026-09-25 | 26 | Projected OpenAI and ChatGPT image generation as a client-tool capability, including function-capable GPT-6 models without a provider-hosted image tool. |
| 2026-09-13 | 25 | Normalized every candidate in an ordered label-local chain, made Primary capabilities drive label controls, and removed singular public mutation compatibility. |

| 2026-09-10 | 24 | Hid image-model selection controls for providers that support maintained-default image generation only. |
| 2026-09-10 | 23 | Added purpose-separated image-generation catalogs, OpenAI registry-and-credential intersection, generation fencing, maintained-default semantics, owner sync, save/runtime authority, and stored-catalog UI behavior. |
| 2026-08-27 | 21 | Added provider-neutral default and maximum input context capabilities, maximum-only fallback, and split-aware picker and Agent settings presentation |
| 2026-08-18 | 20 | Replaced xAI system catalogs with credential-specific integration discovery and optional fill-only LiteLLM enrichment |
| 2026-08-18 | 19 | Made explicitly validated remote LiteLLM DB snapshots authoritative, quarantined fallback/malformed/materially smaller sources, and removed remote source fetching from integration sync |
| 2026-08-01 | 18 | Split Workspace model selection and LLM integration settings into focused routes and containers while preserving catalog query, sync, and submit authority |
| 2026-07-21 | 17 | Clarified that provider-request declaration limits apply whenever the Agent has Tool Search enabled, which is the default for newly created Agents |
| 2026-07-19 | 15 | Added the Agent-opt-in provider-request tool-limit registry as the narrow call-time exception to saved model-selection snapshot semantics |
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

The current implementation does not use models.dev for model catalog source data.
OpenAI and Anthropic provider API listing are not part of the system conversation
catalog path. OpenAI provider listing is used only for the purpose-separated
credential-visible image-generation registry intersection. Current conversation
metadata authority is the explicitly selected generic `genai_prices` source plus
the shared runtime profile resolver. No executable former-source compatibility dependency,
process-local price map, package-bundled fallback, or normal-read remote fetch
supplies catalog, context, or pricing authority.

ChatGPT OAuth, OpenRouter, xAI API key, and xAI OAuth have no system catalog; their
authenticated integration catalogs remain authoritative for conversation-model
visibility. Generic source matching is optional enrichment and never a visibility
gate. Provider-facing and runtime identifiers remain the exact raw provider IDs.
The former metadata source rows, schema, configuration, and code are absent.
Application-only rollback across the destructive cleanup boundary is unsupported;
restoration requires the matching database backup and prior release.
