---
title: "Model Catalog Domain Spec"
created: 2026-06-21
tags: [backend, frontend, engine]
spec_type: domain
domain: model-catalog
code_paths:
  - python/apps/azents/src/azents/core/active_model_capabilities.py
  - python/apps/azents/src/azents/core/_legacy_model_capability_contract.py
  - python/apps/azents/src/azents/core/model_provider_declarations.py
  - python/apps/azents/src/azents/core/route_capability_constraints.py
  - python/apps/azents/src/azents/repos/active_model_capabilities.py
  - python/apps/azents/src/azents/repos/active_model_capabilities_data.py
  - python/apps/azents/src/azents/services/active_model_capabilities.py
  - python/apps/azents/src/azents/engine/events/effective_model_request.py
  - python/apps/azents/src/azents/repos/llm_catalog/capability_publication_test.py
  - typescript/apps/azents-web/src/shared/model-options/containers/SelectableModelOptionsEditorContainer.tsx
  - typescript/apps/azents-web/src/shared/model-options/containers/useSelectableModelOptionsEditor.ts
  - typescript/apps/azents-web/src/shared/model-options/model-option-editor.ts
  - typescript/apps/azents-web/src/shared/model-options/image-generation-config.ts
  - python/apps/azents/src/azents/core/agent_errors.py
  - python/apps/azents/src/azents/core/model_metadata_collection_data.py
  - python/apps/azents/src/azents/core/session_resource_authority.py
  - python/apps/azents/src/azents/repos/engine_event_repositories.py
  - python/apps/azents/src/azents/repos/engine_resolve.py
  - python/apps/azents/src/azents/repos/image_generation_catalog_operations.py
  - python/apps/azents/src/azents/repos/kimi_oauth_runtime/**
  - python/apps/azents/src/azents/repos/llm_catalog_operations.py
  - python/apps/azents/src/azents/repos/model_metadata_operations.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/1c42cc5ce89f_align_repository_index_names_and_source_.py
  - python/apps/azents/src/azents/core/model_execution_options.py
  - python/apps/azents/src/azents/core/openai_client_config.py
  - python/apps/azents/src/azents/core/model_catalog_source.py
  - python/apps/azents/src/azents/core/model_catalog_identity.py
  - python/apps/azents/src/azents/core/model_capability_contract.py
  - python/apps/azents/src/azents/core/model_capability_evidence.py
  - python/apps/azents/src/azents/core/model_capability_projection.py
  - python/apps/azents/src/azents/core/catalog_price_rules.py
  - python/apps/azents/src/azents/services/catalog_source_collection.py
  - python/apps/azents/src/azents/engine/events/model_support_contract.py
  - python/apps/azents/src/azents/core/model_pricing.py
  - python/apps/azents/src/azents/engine/events/model_usage_pricing.py
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
  - python/apps/azents/src/azents/repos/chatgpt_oauth_runtime/**
  - python/apps/azents/src/azents/repos/xai_oauth_runtime/**
  - python/apps/azents/src/azents/repos/kimi_oauth_runtime*.py
  - python/apps/azents/src/azents/repos/model_metadata_read.py
  - python/apps/azents/src/azents/repos/model_metadata_source.py
  - python/apps/azents/src/azents/repos/model_metadata_source_data.py
  - python/apps/azents/src/azents/repos/model_catalog_sync_state.py
  - python/apps/azents/src/azents/rdb/models/llm_catalog.py
  - python/apps/azents/src/azents/rdb/models/model_metadata_source.py
  - python/apps/azents/src/azents/engine/providers/model_profiles.py
  - python/apps/azents/src/azents/scheduler/registry.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/097a97177350_create_operational_schema_baseline.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/4550a9c9083a_remove_catalog_execution_descriptors.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/91dd4bb71ef6_add_model_metadata_source_shadow_schema.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/d29225579621_remove_legacy_litellm_metadata_authority.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/c8bc0a5dcab0_fence_data_only_catalog_source_writers.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/d9bff320245f_replace_catalog_revisions_with_current_.py
  - python/apps/azents/src/azents/api/public/llm_provider_integration/v1/__init__.py
  - python/apps/azents/src/azents/api/public/llm_provider_integration/v1/data.py
  - python/apps/azents/src/azents/api/admin/model_catalog/v1/__init__.py
  - python/apps/azents/src/azents/services/agent/__init__.py
  - python/apps/azents/src/azents/services/workspace_model_settings/__init__.py
  - python/apps/azents/src/azents/repos/workspace_model_settings/**
  - python/apps/azents/src/azents/repos/model_candidate_chain_cutover/**
  - python/apps/azents/src/azents/services/model_listing/providers.py
  - python/apps/azents/src/azents/services/model_options.py
  - python/apps/azents/src/azents/core/builtin_tools.py
  - python/apps/azents/src/azents/engine/run/tool_budget.py
  - python/apps/azents/src/azents/engine/events/engine_adapter.py
  - typescript/apps/azents-web/src/shared/model-options/components/ModelCatalogPicker.tsx
  - typescript/apps/azents-web/src/shared/model-options/containers/ModelCatalogPickerContainer.tsx
  - typescript/apps/azents-web/src/shared/model-options/model-selection.ts
  - typescript/apps/azents-web/src/shared/model-options/components/SelectableModelOptionsEditor.tsx
  - typescript/apps/azents-web/src/features/agents/containers/useAgentFormContainer.ts
  - typescript/apps/azents-web/src/shared/model-options/containers/useImageGenerationCatalogs.ts
  - typescript/apps/azents-web/src/features/llm-settings/containers/useLlmIntegrationsContainer.ts
  - typescript/apps/azents-web/src/features/llm-settings/containers/useWorkspaceModelSettingsContainer.ts
  - typescript/apps/azents-web/src/trpc/model-settings-input-schemas.ts
  - typescript/apps/azents-web/src/trpc/routers/llm-provider-integration.ts
  - typescript/apps/azents-web/src/trpc/routers/workspace-model-settings.ts
  - typescript/apps/azents-admin-web/src/features/model-catalog/containers/useModelCatalogPageContainer.ts
last_verified_at: 2026-10-04
spec_version: 46
---

# Model Catalog Domain Spec

## Purpose

The model catalog stores projected model choices for Agent and Workspace model selection. Normal picker and submit paths use stored catalog projections instead of request-time provider model listing.

## Descriptive read and acceptance boundary

Picker/exact-entry descriptions, source metadata/current rows and optional
context maxima use ordinary scoped reads without integration/source/catalog
shared read locks. Owner provenance and exact current rows are observed together
where multi-query publication interleaves would otherwise require a newest-count
check. Successful empty publication remains distinct from absent publication;
intrinsically malformed stored facts and genuine canonical identity ambiguity
remain errors. Offset page/count descriptions can lag under the current-data
contract; this adds no catalog revision or cache authority.

Completed descriptive operations use independent read-only managers. Active
capability capture uses the same exact local value/absence inputs without
descriptive fencing. Final new-operation/profile acceptance still acquires the
sorted integration, source and catalog guards in the existing owner write scope,
revalidates consumed inputs and keeps that exclusion through the persisted
mutation. Catalog publication retains its producer/input guard. Stale preparation
can be rejected at actual acceptance; it does not authorize a new operation by
itself, recapture saved prices or downgrade captured output capabilities.

## Catalog scopes

Catalogs have two ownership scopes and an explicit purpose. The catalog identity
includes `purpose = conversation | image_generation`, so one integration can own
independent current conversation and image-generation rows without sharing entries,
synchronization state, or publication authority.

- System catalog: managed by Azents for providers whose selectable models are not scoped to a customer integration. Current system catalogs cover OpenAI, Anthropic, and Google Gemini using the current data-only `litellm_catalog` source models.
- Integration catalog: scoped to a provider integration for providers whose visible models depend on customer credential, account, region, or project. Current user-scoped integration catalogs cover AWS Bedrock, ChatGPT OAuth, xAI API key, xAI OAuth, Kimi OAuth, Google Vertex AI, and OpenRouter.

An integration-scoped catalog is created in the same transaction as its provider integration. Public reads for integration-scoped providers use only that catalog and never fall back to a system catalog. For providers with system-owned model visibility, the picker resolves the provider system catalog through the enabled integration.

Catalog identity is semantic rather than execution-library-specific. System catalogs are unique by
`(provider, purpose)` and integration catalogs by `(provider_integration_id, purpose)` within their
respective ownership scopes. Catalogs, conversation entries, public responses, active projection
metadata, and newly created selection diagnostics do not carry `lowerer_target` or a stored
`runtime_model_identifier`. Dispatch uses the saved provider and exact provider model ID.

Stable catalog IDs retain their semantic ownership through replacement. Catalog data has
no snapshot pointer, data generation, content hash, fingerprint, candidate-publication
identity, or retained revision history. Historical Agent diagnostic JSON and native
conversation artifacts remain readable evidence, not current catalog lookup inputs.

## Stored projection entries

A catalog owns one current row per exact provider model identifier, projected into
Azents' canonical model contract. Each conversation entry records:

- provider
- optional provider integration id
- provider model identifier
- display name
- normalized capabilities
- a server-owned normalized available or unavailable pricing definition
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

xAI OAuth consumes its own account-model response. `context_window` supplies the
default input window; a supplied `context_windows` list supplies its maximum.
Absent maximum-list metadata retains the single-window declaration, while null
or empty declarations are preserved instead of inventing a maximum. A default
above an advertised maximum is an invalid provider response eligible for retry,
not a credential/configuration failure that permanently blocks automatic retry.
Supplied xAI input/output modalities and the OAuth top-level `reasoning_effort`
are captured with omission/null/empty distinctions. A conflicting advertised
default and preset declaration leaves the effective default unknown and records
bounded diagnostics. Typed fields are retained in provider provenance; opaque
provider instructions and unknown preset extensions are not adopted.

Runtime and Agent context displays supplement only a missing maximum through an indexed exact
current source-model read. A known provider default is a floor for this fallback;
when default, maximum and source maximum are all missing, the resolved limit is 128,000 tokens.
Saved maximums win over source data and no SDK profile changes a saved capability. A paired
foreground/lightweight budget shares one coherent exact-key capture; an Agent list groups only
the displayed selections needing fallback. These operations do not restore a complete source
dataset or fetch one dataset per candidate.

### ChatGPT web-search support

Account-visible ChatGPT OAuth conversation models use the reviewed Codex route's
native web-search contract alongside exact account declarations. The compiler
retains source presence and diagnostics separately and produces one final
built-in support list. Native OpenAI records, price fields and model-name
similarity do not establish ChatGPT permission.

Current exact local declarations supply active same-identity metadata even when
an existing selection carries an older compiled object. Configuration and native
dispatch consume the final support list; read projections preserve stored user
settings.

### Route-bounded support propagation

Eligible `chat` and `responses` conversation modes retain the same reviewed
client-image executor policy. Provider-hosted image permission is separate from
client execution. Google and Vertex Google use the implemented GenerateContent
image-output boundary for both the adopted explicit IMAGE output declaration and
the configurable native image tool. Final compiled support governs codec image
flags; declaration presence and route exclusions remain diagnostic inputs.

Explicit Google efforts are bounded by the installed scalar codec's lossless
level domain, including its documented sparse-profile floor. An omitted optional
codec level set is not an empty model effort declaration; absent model evidence
still advertises no efforts, budget-only or snapped mappings remain excluded.
Account effort-control denial overrides conflicting xAI OAuth presets/defaults.

Function calls, parallel calls, strict schemas and structured responses use
separate final fields. A conditional supported feature remains configurable;
actual request admission evaluates its captured effort/function conditions.
Configuration and profile controls read complete final lists without inventing
request dimensions or maintaining a second descriptor authority.

Two reviewed supplements have exact route/feature scope. Eligible authenticated
Kimi OAuth managed coding inventory establishes function-calling potential; it
does not establish parallel calls, strict schemas, structured responses, efforts
or hosted tools. The exact `grok-4.7` model on xAI API-key and xAI OAuth routes has
a hosted web-search supplement. That web rule does not predict support for
other model IDs or authentication routes.

For Kimi function calling and exact Grok web search, an own-provider null combined
with matching-source false denies the final feature while retaining the raw null
declaration. Explicit own-provider false remains a denial; own-provider true
retains support over matching generic false. These narrow supplement guards do
not extend to other features or convert original evidence into guessed facts.

Catalog diagnostics include applicable installed codec
dependencies. Native OpenAI/ChatGPT record the OpenAI SDK dependency and do not
stamp Pydantic as their native codec. These versions are reproducibility inputs,
not model-capability facts.

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

## Current source storage and synchronization

The stable source row stores collection provenance, last-success time, counts, and
one current synchronization state. Exact source models use the composite identity
`(source_key, provider, source_model_key)` and store validated descriptive model data,
normalized pricing, and collection time. The PostgreSQL source-kind ENUM retains
its historical labels, but current writes require `litellm_catalog`, `litellm_json`,
and schema `1`. Retired source owners and source revision tables are removed.

The active source is `litellm_catalog`, kind `litellm_json`, schema/interpreter
version `1`. The controlled `MODEL_CATALOG_SOURCE_URL` defaults to the public
LiteLLM JSON document. Azents downloads inert JSON through an injected bounded
HTTP collector; it does not import LiteLLM execution code or use its helpers,
regex matching, SDK profiles, aliases, or price calculator. The bounded response
is decoded transiently; raw/canonical dataset blobs, hashes, ETags, and fingerprints
are not persisted or used as authority. Strict decoding validates exact identities,
presence, numeric evidence, lifecycle dates, derived reasoning consistency and counts.

Absence, null, false and an explicit empty set are distinct. Exact provider/account
declarations own their scope and only absent fields may be enriched by an exact
source match. Native, OAuth and cloud namespaces are separate; literal publisher
paths are retained. No bare-name twin, alias stripping, model-family inference
or cross-host borrowing establishes capability, context or pricing authority.
System inventory uses descriptive mode/endpoint/lifecycle facts rather than
prices or name prefixes. Missing source matches never hide valid account-visible
integration models.

The six-hour `model_catalog_system_projection` task uses this collector and
stored source contract. Transport, validation, supersession and material-reduction
failures record bounded diagnostics and retain last-good source/catalog state.
Normal reads, model dispatch and integration enrichment do not fetch remote
metadata. Preparation normalizes prices and capabilities outside database transactions.
Source replacement and all affected system catalog entries commit together after
stable-owner locking and comparison of the prepared typed source values. Integration
publication compares consumed exact source-model values and absence states plus
descriptive source presence/provenance, then rechecks enabled integration ownership,
credential/configuration generation, and the active work token. Changed inputs
repeat local preparation; stale workers cannot publish. No hash, data revision, or
work token substitutes for source-value comparison.

Conversation projections carry `capability_schema_version = 3`. The final
boolean/list fields alone determine support: inclusion is support and omission or
false is absence. `structured_response` is independent of strict function schemas.
`request_constraints` contains a nullable known reasoning default and one
conjunction per supported conditional feature, not another support state.
Function calls, parallel calls, reasoning, summaries, parameters, modalities and
implemented built-ins retain distinct fields.

The compiler combines exact provider declarations, locally captured source facts
and reviewed route contracts. Source presence, completeness and unavailable-price
diagnostics remain typed evidence rather than final unknown capability states.
Native OpenAI/ChatGPT keep native codecs, while other routes retain SDK formatting
without making stock model profiles a second model-feature authority.

Explicit reasoning denial is terminal within a source record. A complete effort
array, including `[]`, takes precedence over flags. Only an absent array and a
valid per-level flag enable the versioned native OpenAI/ChatGPT flag convention:
none/minimal/low are opt-out, medium/high are derived baseline, and xhigh/max are
opt-in; null remains unknown. Generic reasoning true alone creates no effort set.
Defaults are independently declared, not inferred from order or none membership.
Every advertised effort must have lossless route encoding; the Google scalar codec does not
invent budgets or remap to a nearby level.

The selectable and directly dispatched effort domain remains `none`, `minimal`,
`low`, `medium`, `high`, `xhigh`, and `max`. Provider `ultra` declarations remain
original evidence and are excluded from canonical controls, matching the
pre-Pydantic parser. They do not become `max` or a new selectable level.

ChatGPT preserves exact account arrays/limits/tool declarations and its audited
provider policy; request hints/instructions do not become model options. OpenRouter
preserves complete parameter lists, empty/null evidence and literal publisher IDs;
only its exact structured-output declaration establishes response-schema support,
not a generic response-format flag or strict function support. xAI consumes
returned SDK/OAuth context, reasoning and search evidence while preserving omission
and explicit denial. Kimi internal reasoning does not create generic effort
controls. Bedrock/Vertex preserve account/region/project inventory and actual
protocol ownership; direct Anthropic/Gemini rows are not cloud evidence.

Built-ins remain the implemented `web_search` and `image_generation` settings.
Descriptive web facts plus implemented ownership authorize search, never a price
key or an unconditional compatible-transport assumption. Client and hosted image
evidence remain separate; the saved image row is projected for the provider's
existing execution owner. Hosted denial does not deny the maintained client
executor. Source audio/video flags do not implement a rich-file route, and strict
function schemas do not imply structured responses.

Configuration, selection, settings copy and image-catalog controls expose every
final supported built-in independently of a partially known request. Dispatch
checks membership and conditions after effective effort and actual function
declarations are known. Client and hosted execution use the same gate. Absent
support or an unmet condition fails before HTTP; explicit strictness, scalar
settings and effort are not silently removed to pass admission.

Conversation publication validates the raw schema-3 object and current
`capability_compiler_revision = "4"` before replacing current rows. Historical
read decoding does not satisfy this writer guard. These are application checks
using the existing owner/source integrity fences; this capability repair
introduces no database migration.

Each source or catalog owner retains only its current synchronization status, counts,
failure metadata, action hint, and diagnostics. An opaque work token exists only while
work is running and is cleared at terminal completion; it is not a model-data ID.
Failures preserve current source models, catalog entries, normalized prices, and
last-success time. Conversation synchronization/freshness does not add a selection gate.

A valid source can contain only a subset of system providers. Expected
provider-local projection failure preserves that provider's successful rows,
prices, counts, and last-success time and records its current failure facts.
Source data, successful provider replacements, and failed-provider status changes
commit in the same fenced transaction. Global collection, normalization, shrink,
or unexpected publication failure does not partially publish new data. Refresh
summaries report each provider's actual status and failure facts.

Conversation lazy-refresh eligibility compares the current successful owner's
procedural projection schema/resolver pair with the required code pair, as well
as age. The locked claim compares the same pair and preserves all existing
running/cooldown/backoff guards. Successful publication records these facts in
current owner `diagnostics.projection_version`; the one-time migration carries
the actual current procedural pair before deleting historical tables. This is a
code-compatibility hint, not a model-data ID, fingerprint, or execution/selection
authority. Image-purpose refresh remains age-only and uses its separate usability
authority.

The integration's positive `catalog_configuration_version` is credential/configuration
authority, not a catalog data revision. User credential/configuration changes advance
it. Runtime OAuth token rotation and connection-status persistence use the separate
runtime-state update path and preserve it, so a refresh initiated by synchronization
does not invalidate its own publication. This applies to ChatGPT, xAI, and Kimi OAuth.
Genuine concurrent user changes continue to fence stale conversation and image work.

ChatGPT and xAI refresh success and failure persistence lock the integration row
and compare the original catalog generation, complete typed credentials, and
`last_refreshed_at` before writing. A reconnect, user configuration change, or
newer refresh makes the result stale; persistence returns the current integration
without replacing its credentials or configuration. State-only failure
diagnostics within the same identity do not prevent a fresh success from
restoring the connected state.

Only image-purpose catalogs store a non-null usability boolean. Integration
configuration changes invalidate it transactionally. A matching successful image
publication sets it true; a failed refresh does not invalidate an otherwise usable
listing. Retained rows after invalidation remain diagnostic, but cannot authorize
new explicit image saves or runtime dispatch.

Image synchronization records its failed attempt before propagating the original
provider listing exception and cause. It does not return a successful projection
summary with a failed status. The failure retains provider diagnostics, retry
policy and recovery hints without replacing current image entries, changing
configuration authority or clearing an otherwise usable listing. Unexpected
failures likewise record their attempt and propagate; successful synchronization
and expected policy/precondition result variants keep their existing contracts.

### Coordinated data transition

Migration `d9bff320245f` follows `1c42cc5ce89f` in one linear chain. Old readers,
writers, and queued dispatch work must be quiescent; running catalog synchronization
fails preflight. The migration keeps stable owners and only current entries, expands
the current source into exact rows, and normalizes current prices. It initializes only
missing pricing in saved Agent/Workspace selections, current Session selections, and
future nonterminal operation candidates using exact existing scope. Unmatched or
unsupported evidence becomes explicitly unavailable; identities, capabilities, labels,
settings, and already present validated prices are preserved.

Already-started candidates and terminal operation/event/cost history are not rewritten.
Removed snapshot/history tables, pointers, hashes, fingerprints, and retired source rows
are not a compatibility fallback. Current-owner, purpose, source identity, and image
invalidation guards replace old pointer guards. Downgrade is irreversible; recovery
requires stopped writers and matching schema/data restoration.

## Local operation metadata and pricing

Context fallback reads only requested exact current source-model maxima through
`ModelMetadataService`, never an installed model map, library profile, complete source
restore, or request-time remote source fetch. Exact provider/source namespaces and adopted literal
producer address formats are distinct from execution encoding; aliases, publisher paths
and cloud resource identifiers are
not stripped. Saved normalized capabilities retain their existing precedence and default
floor. Paired context calculations share one coherent exact-key view, and known maxima skip
source reads.

Pricing normalization is independent of capability projection and occurs at source/catalog
publication. Explicit model selection copies that entry's compact typed pricing definition
into `AgentModelSelection`. Reselection adopts current prices; refreshes do not mutate
saved selections. Each actual physical call freezes its candidate's saved definition,
exact provider/model identity, descriptive source/model key, collection time, code estimator
version, and aware call time. Fallback candidates use their own definitions. Capture does
no pricing DB read, raw-price interpretation, source restore, hashing, or caching, and usage
completion never rematches a newer catalog. Typed rates are USD per named unit, including
per-token source amounts.
Normalized pricing JSON exposes USD rates as lossless decimal strings (or null),
including scientific notation. The API schema and generated clients accept that
same representation; rates are not converted to binary floats. Raw source
numeric validation remains a separate, strict ingestion boundary.
Decimal evaluation partitions cache/reasoning/media quantities using explicit
usage inclusion flags, honors TTL/context thresholds, trustworthy service tiers
and bounded off-peak windows, and requires every used specialized dimension.
Standard, Priority, Flex, Batches and Ultrafast tariffs are used only with actual
applicable billing evidence; missing premium prices never fall back to Standard.
Unsupported or missing required pricing makes the whole total `null`, not zero
or a token-only subtotal. Finite nonnegative provider charges, including zero,
take precedence. No direct genai fetch/matching/cost API supplies an estimate;
the retained transitive Pydantic counter extractor is not pricing authority.
Provider-returned charges and estimates retain distinct provenance. Optional
metadata/pricing misses do not change model visibility or saved selections. Historical
selected-model JSON without `pricing` decodes read-only as absent; dispatch without a
definition leaves local estimates unavailable. Ordinary reads do not enrich or save it.
New estimate provenance excludes snapshot IDs, hashes, catalog foreign keys, and archived
price payloads. Immutable old event/cost provenance remains readable without history lookup.

Google native modality receipts preserve directed input/output IMAGE and AUDIO
quantities. Prompt receipts partition native prompt counts; output receipts
partition candidate counts before inclusive reasoning normalization. Explicit
TEXT-only cache receipts keep media and cache disjoint. Malformed, duplicate,
contradictory, unknown positive modalities, uncertain cache/media overlap, cached
media without an adopted tariff, and unadopted tool-use quantities leave the whole
estimate unavailable. Valid reported charges still win, including zero; no
recorded historical cost is recalculated.

## Public read API

The public catalog entry list endpoint returns the stored catalog entries for one integration. It supports search, limit, and offset. The response includes:

- catalog id and ownership scope
- nullable last-success time
- current latest sync status, including failure metadata before the first success
- stale state, earliest explicit sync time, and automatic-retry-blocked state
- paged entries
- total count
- limit and offset

A catalog before its first successful publication still returns a successful status-aware
response when the catalog exists. Entries are empty and latest sync state distinguishes
never synced, running, and failed-before-success states. Public/admin status and generated
clients expose no snapshot IDs, hashes, fingerprints, cutover/candidate commands, or catalog
data generations. Active work tokens are not public model-data identifiers.

Selectable entries are ordered by a stored or derived freshness rank before display name and model identifier tie breakers so newer model generations appear first.

The read path must not call provider listing APIs, models.dev, or the remote metadata source. It returns the stored response first. When an integration-scoped projection is stale, the route queues a best-effort background refresh whose synchronization policy rechecks eligibility before provider work begins.

The image-generation catalog read endpoint returns `default_available`,
`explicit_selection_supported`, `usable`, last-success time, latest sync status, and
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

For AWS Bedrock and Google Vertex AI, sync fetches the provider-visible model list and projects it against current exact generic metadata source rows. For ChatGPT OAuth, sync refreshes the OAuth token when necessary, calls the account-scoped Codex model endpoint with the fixed compatibility client version, and projects backend-visible models directly. For xAI API key, sync calls the developer model endpoint with that integration's key. For xAI OAuth, sync refreshes the token when necessary and calls the Grok account model endpoint. Both xAI paths project provider visibility directly and use generic metadata only as optional fill-only enrichment. For Kimi OAuth, sync refreshes the token when necessary, calls the authenticated Kimi Code model endpoint with the encrypted device identity, and directly projects valid account-visible models. For OpenRouter, sync calls the fixed authenticated account-model endpoint and projects every valid text-output model directly without requiring a generic metadata match.

Integration catalog synchronization has four triggers:

- enabled integration creation or successful OAuth connection;
- credential/configuration update or re-enable;
- explicit user sync;
- stale lazy refresh while the integration catalog is actively viewed.

Name-only updates and disable operations do not trigger synchronization. Create/configuration-change triggers bypass cooldown and failure backoff because they represent new provider state, but they do not replace an active attempt. Explicit sync bypasses the credential-failure automatic block while respecting cooldown and transient backoff. Stale refresh respects all policy guards.

Explicit and stale requests use a 30-second integration cooldown and a 5-second workspace cooldown. Retryable provider failures use a 5-minute backoff. Current catalog data becomes stale 15 minutes after its last success. Running synchronization older than 15 minutes is marked failed and recovered by the next eligible request.

Synchronization claim locks the workspace and stable catalog rows before evaluating policy and recording running work. This makes duplicate-running and workspace/integration throttle decisions atomic. Completion locks the catalog again and publishes only when the active work token still matches, fencing workers superseded after running-lease recovery. Running work or superseded completion returns conflict; cooldown or backoff denial returns HTTP 429 with `Retry-After` for explicit requests.

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
reviewed registry entry, a usable current image catalog, and a matching
selectable entry. Agent and Workspace save paths share this validation, and
Workspace defaults copy the complete built-in configuration into newly created
Agents.

Workspace default current reads, empty-row get-or-create and final writes finish
inside completed repository operations. Stored-catalog and image-option
normalization remain outside Workspace database transactions, between the
completed current read and final write. The existing model-chain downgrade
marker commits or rolls back with the final settings columns.

This ownership boundary preserves current WorkspaceMember authorization,
configured-options clear rejection, empty-row behavior, omission and label-null
fallback, option order/labels/subagent flags, and exact saved source/catalog and
capability/execution snapshots. It adds no Workspace revision/CAS, enabled-user
or stronger conversation selection predicate, provider fetch or auto-reselection.
The adjacent catalog/image services retain their own separate ownership scope.

If no selectable stored catalog entry matches a requested candidate integration and model identifier,
the service rejects the candidate. Public mutation has no direct singular model-selection
compatibility field. Submit normalization must not refetch a dynamic provider listing as a fallback.

## Snapshot semantics

Saved integration/model IDs, labels, candidate order and settings are user
configuration. Active Agent detail/list and Workspace responses compile metadata
for those exact authorized local choices and return detached copies. Capture uses
current catalog declarations, including legitimate older raw entries, exact local
source rows and reviewed route rules. Failed sync preserves usable last-good
declarations. Missing scope, exact entry or required evidence retains the
configured identity with an explicit metadata diagnostic and empty final support.

Normal reads and unrelated PATCH/label saves preserve stored user settings. A
new Agent inheriting Workspace defaults captures compiled metadata for the same
ordered choices. Existing selection prices remain independently captured pricing.

Historical capability JSON is decoded read-only for captured operations and
history. That boundary is separate from compilation of current raw declarations
and cannot authorize a new schema-3 catalog publication. Final API support has
one representation; source evidence diagnostics keep their separate typed shape.

A NEW model operation captures final capabilities before effective-profile
normalization and revalidates local inputs within the existing owner write fence.
Retries, quota progression, takeover and history use its captured candidates;
newer metadata cannot reinterpret an existing operation. Lowerers receive that
snapshot and perform no current metadata lookup or provider/source discovery.

If an integration is deleted or disabled, runtime or configuration operations can still fail because the credential/config source is unavailable. That is an integration availability failure, not a catalog drift failure.

The effective provider-request tool declaration limit is the narrow exception to saved selection snapshot authority when the current Agent has Tool Search enabled. On that enabled path, runtime resolves a reviewed rule before each prepared model call from the current provider, adapter/native request path, runtime model identifier, model developer, and normalized family. The code-owned compatibility registry is authoritative for this transport constraint so a previously saved `AgentModelSelection` cannot freeze a stale hard limit. Exact-model rules take precedence over family rules and family rules over endpoint rules; an equally specific overlap is invalid configuration. When Tool Search is disabled, runtime preserves the complete legacy client-tool catalog and does not apply registry projection.

The current registry applies xAI's documented 200 total-tools request ceiling and a conservative 128 function-declaration ceiling only to Vertex AI request paths targeting Google/Gemini models. The Vertex rule records the conflicting official 128 and 512 sources and their verification date. Direct Gemini API requests and Vertex-hosted Anthropic or other non-Google models remain unmatched. When no verified rule matches, the limit is absent and runtime does not invent a product-wide fallback cap. This is a transport constraint; compiled active metadata and frozen operation capabilities retain their separate ownership boundaries.

## Picker behavior

The web picker is integration-first. The form displays the current model summary and opens a model picker modal to change the selection. Forms and settings pages must not prefetch every integration catalog while rendering. The picker lazily reads the selected integration catalog only after the modal is opened and an integration is selected.

Optional controls read final support fields and exact effort lists. Conditions
constrain actual requests rather than removing configurable potential. Concrete
model changes retain the existing ordered effort adaptation; explicit null stays
null and a valid selected value stays unchanged. The final capability surface has
no unknown/unverified badge or additional configuration mode.

The picker shows catalog status and supports search plus infinite-scroll paged loading. It renders provider-independent catalog UI states for no integration selected, loading, never synced, syncing before first success, failed before first success, ready, ready with latest failed sync, ready empty result, and loading next page. Failure state renders before empty result state. Pages are current-data offset reads, not revision-pinned views.

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
refresh failure, unusable-after-configuration-change, never-synced, stale, and empty catalog states.
Only Workspace Owners receive the explicit image sync action.

## Change History

| Date | Version | Change |
|---|---:|---|
| 2026-10-03 | 42 | Replaced catalog/source revisions with current exact rows and sync state, embedded normalized saved prices, exact context reads, image usability, and destructive history-free transition. |
| 2026-10-03 | 41 | Completed existing top-k request transport and sampling codec preservation without changing model support authority. |
| 2026-10-03 | 40 | Preserved route-bounded image/effort/refinement support, complete Google directed billing and truthful codec dependency provenance through audited correction paths. |
| 2026-10-03 | 39 | Restored contract-derived ChatGPT web-search support through final v2 catalog entries and saved native requests without generic source or price dependence. |
| 2026-10-03 | 38 | Replaced active genai authority with inert exact-scoped JSON, self-contained v2 support and typed pricing; preserved historical selections and added SQL writer/pointer fences. |
| 2026-10-02 | 37 | Moved Workspace model default reads/get-or-create/writes into completed repository operations while preserving detached normalization, current policies and atomic downgrade marking. |
| 2026-10-02 | 36 | Fenced ChatGPT and xAI refresh success and failure against original generation and credential identity under one row lock. |
| 2026-10-02 | 35 | Kept ChatGPT and xAI OAuth runtime refresh persistence on the generation-preserving path while retaining user-update and publication fences. |
| 2026-10-02 | 34 | Restored effective Grok client-image, native-search, and function-tool support despite omitted listing facts or missing tool prices. |
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
metadata authority is the explicitly selected data-only JSON plus exact listing
evidence and implemented route bounds. SDK codecs retain protocol formatting,
not native model capability authority. No direct genai/LiteLLM execution import,
process-local price map, package-bundled pricing fallback or request-time remote
fetch supplies catalog, context or estimated-pricing authority.

Selected sampling controls are admitted against captured final support and actual
encoded-request conditions. Google/Anthropic/Bedrock top-k encoding is a transport bound, not a
positive model capability fact. Runtime profiles preserve accepted controls
through the actual codec; missing canonical top-k mappings fail before dispatch.

ChatGPT OAuth, OpenRouter, xAI API key, and xAI OAuth have no system catalog; their
authenticated integration catalogs remain authoritative for conversation-model
visibility. Generic source matching is optional enrichment and never a visibility
gate. Provider-facing and runtime identifiers remain the exact raw provider IDs.
Retired genai source data and nullable provenance remain inert history, while its
active collector/matcher/evaluator/dependency/configuration are replaced. Stock
Pydantic usage-counter extraction remains transitive. Release preparation drains
old read/save/dispatch producers before exposing the new contract and application
publication guard. This is operational coordination rather than a new runtime
mode. Existing database integrity and historical operation/provenance are
preserved; no new database migration is part of this capability correction.
