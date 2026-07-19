---
title: "OpenRouter API Key Provider"
created: 2026-07-19
updated: 2026-07-19
implemented: 2026-07-19
tags: [backend, frontend, engine, security, api, testenv]
---

# OpenRouter API Key Provider

> Related decision record: [ADR-0169: Add OpenRouter as an Integration-Scoped LLM Provider](../adr/0169-add-openrouter-as-an-integration-scoped-llm-provider.md)

## Problem

Azents does not support OpenRouter as an LLM provider. Users who want to try models from many publishers must create separate provider integrations, and a model is not selectable until Azents' provider catalog path knows about it.

OpenRouter's primary value is different from a curated provider integration: one API key exposes a rapidly changing, account-available model catalog. Supporting only an Azents allowlist or only models already present in the LiteLLM metadata snapshot would remove that value.

OpenRouter also separates the hosting gateway from the model developer. A request can use provider `openrouter`, model identifier `anthropic/claude-*`, and model developer `anthropic`. Azents currently falls back to Anthropic when a catalog entry's developer cannot be recognized. That fallback is unsafe for OpenRouter because unknown publishers could receive Anthropic-specific cache and hosted-tool lowering.

## Goals

- Add a stable workspace-scoped `openrouter` API-key provider.
- Expose every account-available text-output model returned by OpenRouter without an Azents model, publisher, family, or upstream-provider allowlist.
- Refresh model availability through the existing integration-scoped catalog lifecycle.
- Keep catalog visibility independent from conservative capability projection.
- Reuse the existing LiteLLM Responses request, streaming, canonical transcript, usage, and provider-failure paths.
- Delegate upstream routing and data-policy configuration to OpenRouter account and API-key controls in the first release.
- Keep credentials and provider request details out of public responses, logs, events, and test evidence.

## Non-goals

- Add Azents-owned provider routing, fallback, zero-data-retention, or upstream allow/deny settings.
- Add a curated OpenRouter model allowlist.
- Require a matching LiteLLM catalog entry before exposing an OpenRouter model.
- Add a user-configurable OpenRouter-compatible base URL.
- Advertise unverified PDF, audio, video, image-output, image-generation, prompt-caching, or strict structured-output capabilities.
- Guarantee that every upstream route implements every OpenRouter-normalized feature identically.
- Validate live inference during integration CRUD.
- Introduce a generic custom OpenAI-compatible provider framework.

## Current Behavior

### Provider integrations

API-key providers reuse `ApiKeySecrets`, encrypt secrets before persistence, omit secrets from public responses, and use the generic integration CRUD and frontend API-key form. The public provider capability endpoint owns the list of creatable providers and their display names.

`LLMProvider` and the PostgreSQL `llm_provider` enum do not contain `openrouter`.

### Model catalogs

Azents separates system catalogs from integration-scoped catalogs. Integration creation for an integration-scoped provider transactionally creates its catalog and schedules an initial background sync. Normal model-picker reads use only stored projections and may queue a stale refresh; they never call the provider directly.

Bedrock and Vertex provider listings are intersected with the current LiteLLM source snapshot. Models missing from LiteLLM metadata are hidden. ChatGPT OAuth is the existing exception: its account-visible listing is projected directly without requiring a LiteLLM metadata match.

OpenRouter requires the direct-projection pattern because its account catalog changes more quickly than LiteLLM metadata and model visibility is part of the product contract.

### Runtime

Non-OpenAI providers use `LiteLLMResponsesLowerer` and `LiteLLMResponsesModelAdapter`. Runtime model identifiers include a LiteLLM routing prefix, while credential kwargs can supply an API key, API base, custom provider name, and extra headers.

Hosted-tool and prompt-cache behavior currently depends on provider and model developer. An unknown developer can currently fall back to Anthropic during catalog snapshot resolution. This must be removed before unknown OpenRouter publishers are selectable.

## Accepted Product Decisions

The following decisions are recorded in ADR-0169:

1. OpenRouter is an integration-scoped provider and exposes all authenticated account-available text-output models without an Azents allowlist.
2. Model visibility does not require a LiteLLM metadata match.
3. Missing or unverified capabilities disable only the capability, not the model.
4. OpenRouter account and API-key settings own upstream routing and data policy in the first release.
5. Azents does not add request-level provider routing or privacy overrides in this release.

## Proposed Design

## Provider Identity and Credential Contract

Add the following provider identity:

```text
LLMProvider.OPENROUTER = "openrouter"
```

Map it to:

- public display name: `OpenRouter`;
- credential type: `api_key`;
- provider config: none;
- experimental: `false`;
- catalog scope: integration;
- LiteLLM model prefix: `openrouter/`;
- LiteLLM custom provider: `openrouter`;
- API base: `https://openrouter.ai/api/v1`.

A create request uses the existing shape:

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

CRUD does not call OpenRouter synchronously to validate the key. The initial background catalog synchronization provides the first credential and account-availability result. Name-only updates preserve the encrypted key and do not refresh the catalog. Key replacement or re-enable follows the existing integration-catalog synchronization triggers.

## Database and API Contract

Generate a new Alembic revision that additively appends `openrouter` to PostgreSQL enum `llm_provider`. Update `python/apps/azents/db-schemas/rdb/revision` to the generated revision. Downgrade keeps the enum value because PostgreSQL enum-value removal is not a safe rollback operation.

No new table, column, provider-specific config model, or row backfill is required.

Adding `openrouter` and `LLMModelDeveloper.OTHER` changes public OpenAPI enums. Regenerate the public OpenAPI specification and Python and TypeScript public clients; generated client files must not be edited manually.

## Neutral Model Developer

Add:

```text
LLMModelDeveloper.OTHER = "other"
```

`OTHER` is a semantic safety value for a model publisher that Azents does not recognize. It is stored in Agent and Workspace model-selection snapshots through the existing JSON contract. The current relational `llm_model_developer` enum is no longer an active stored column type, so this change does not require another PostgreSQL enum migration.

OpenRouter publisher aliases are derived from the first model-id segment:

| OpenRouter publisher segment | Azents developer |
|---|---|
| `openai` | `OPENAI` |
| `anthropic` | `ANTHROPIC` |
| `google` | `GOOGLE` |
| `x-ai` | `XAI` |
| `meta-llama` | `META` |
| `mistralai` | `MISTRAL` |
| any other segment | `OTHER` |

Catalog snapshot resolution must default to `OTHER`, not Anthropic, when no developer can be derived. Known non-OpenRouter provider defaults remain explicit in the existing provider-to-developer mapping.

## Integration-Scoped Model Listing

Add `LLMProvider.OPENROUTER` to `INTEGRATION_SCOPED_CATALOG_PROVIDERS`.

The listing adapter performs:

```http
GET https://openrouter.ai/api/v1/models/user?output_modalities=text
Authorization: Bearer <API key>
```

The adapter uses a fixed Azents-owned endpoint. Workspace users cannot supply a base URL. It validates that the response contains a `data` list and normalizes each dictionary independently.

A model is retained when:

- `id` is a non-empty string;
- the authenticated endpoint returned it for text output;
- its output modalities are absent or include `text`.

No model, publisher, family, pricing, popularity, moderation, benchmark, or upstream-provider allowlist is applied. Invalid entries are skipped with bounded diagnostic counts instead of failing the entire catalog. A missing or invalid top-level `data` list is an invalid-provider-response failure.

Normalized candidate identity is:

- provider: `openrouter`;
- provider model identifier: the exact OpenRouter `id`, for example `anthropic/claude-sonnet-4.6`;
- runtime model identifier: `openrouter/<provider model identifier>`;
- display name: OpenRouter `name`, falling back to `id`;
- developer: publisher alias mapping, otherwise `OTHER`;
- family: a display/diagnostic family derived from the model-id portion after the publisher segment.

Store a bounded catalog-relevant source metadata subset such as `canonical_slug`, `created`, `expiration_date`, `architecture`, `supported_parameters`, `top_provider`, `pricing`, and `reasoning`. Do not persist credentials, response headers, benchmarks, external links, or unbounded descriptions in catalog entries.

## Direct Catalog Projection

Add an OpenRouter-specific direct projection function, parallel to the ChatGPT direct projection path.

The projection:

- creates one selectable entry for every normalized candidate;
- never hides an entry because LiteLLM source metadata is missing;
- uses the exact provider model identifier from OpenRouter;
- stores runtime identifier `openrouter/<id>`;
- attaches the current LiteLLM source hash only for existing lowerer-target lifecycle diagnostics;
- records that no LiteLLM metadata match was required;
- preserves the standard freshness rank and integration id;
- reports skipped invalid listing records but does not report them as allow-policy exclusions.

The existing stored-snapshot publication, attempt fencing, cooldown, stale refresh, retry backoff, and last-successful-snapshot behavior remain unchanged.

The direct projection branch must be explicit. Passing OpenRouter through `project_integration_entries()` would create `missing_target_projection` hidden entries and violate ADR-0169.

## Conservative Capability Projection

OpenRouter metadata is the capability source for the first release. LiteLLM metadata may be retained for diagnostics when present but must not add capabilities or gate visibility.

### Context window

- `context_length` maps to `context_window.max_input_tokens` when it is a positive integer.
- `top_provider.max_completion_tokens` maps to `context_window.max_output_tokens` when it is a positive integer.
- Missing values remain `null`; Azents does not invent defaults.

### Modalities

- Output is projected as `text` only.
- Input `text` and `image` are projected when declared by `architecture.input_modalities`.
- If input modalities are absent, project `text` as the conservative compatibility default for a text-output chat model.
- PDF, audio, and video are ignored in the first release even when metadata lists them.
- Image output is not projected.

### Function tools

- `tools` in `supported_parameters` enables function tool calling.
- `parallel_tool_calls` is `true` only when explicitly present; otherwise it remains unknown.
- Strict JSON Schema remains unknown/disabled even when `structured_outputs` or `response_format` is listed, pending representative Responses-path verification.

### Reasoning

- `reasoning`, `reasoning_effort`, or `include_reasoning` enables reasoning support.
- When `reasoning_effort` is listed, expose normalized `low`, `medium`, and `high` effort levels.
- Do not infer `none`, `minimal`, `xhigh`, or `max` without an explicit stable OpenRouter contract.
- Reasoning summaries remain unknown unless verified by the Responses stream contract.

### Built-in tools

OpenRouter's Responses server-side web search is projected as an effective provider-level capability for selectable OpenRouter text-output models. As required by ADR-0064, this capability makes the semantic tool selectable but does not automatically enable it for an Agent; the Agent owner must opt in through model settings. The OpenRouter hosted-tool lowerer emits the current namespaced server-tool type:

```json
{"type": "openrouter:web_search"}
```

The selected upstream model does not need a native search implementation because OpenRouter can provide web search through its provider-owned search path. Capability projection remains limited to the currently implemented Azents semantic tool `web_search`.

`image_generation` is not projected for OpenRouter in the first release.

### Generation parameters

Map only parameters represented by Azents' current capability contract:

| OpenRouter `supported_parameters` | Azents parameter capability |
|---|---|
| `temperature` | `temperature` |
| `max_tokens` or `max_completion_tokens` | `max_output_tokens` |
| `top_p` | `top_p` |
| `top_k` | `top_k` |
| `stop` | `stop_sequences` |

Other OpenRouter parameters remain source metadata and are not added to Agent configuration in this feature.

## Runtime Model and Credentials

Add:

```text
PROVIDER_LITELLM_PREFIX[OPENROUTER] = "openrouter/"
```

OpenRouter remains on the LiteLLM Responses path. It must not enter the native OpenAI SDK path merely because its API is OpenAI-compatible.

For an OpenRouter API-key integration, credential resolution produces:

```python
{
    "api_key": key,
    "base_url": "https://openrouter.ai/api/v1",
    "api_base": "https://openrouter.ai/api/v1",
    "custom_llm_provider": "openrouter",
    "extra_headers": {
        "X-OpenRouter-Title": "Azents",
    },
}
```

`HTTP-Referer` is not sent by default because it would disclose the deployment domain. No request-level `provider` routing object is added. OpenRouter account and API-key settings remain authoritative for provider order, fallback, retention, and data-policy behavior.

The existing LiteLLM Responses transport passes unknown non-reserved kwargs such as `extra_headers` through to `aresponses`. Streaming, canonical output normalization, usage extraction, cost extraction, cancellation, timeout handling, and provider-failure classification remain shared.

## Request Lowering

OpenRouter uses the standard top-level Responses `instructions` field and full canonical transcript replay. It does not use OpenAI stored-response continuation and does not require a new continuation lifecycle.

Add explicit provider behavior:

- hosted tool target `openrouter`;
- `web_search` lowers to the OpenRouter Responses server-tool shape `{ "type": "openrouter:web_search" }`;
- Anthropic cache-control is always disabled for provider `openrouter`, including Claude models;
- OpenAI prompt-cache keys are not added;
- hosted image generation remains unsupported;
- model-developer-specific Google or Anthropic hosted-tool dialects do not override the OpenRouter gateway dialect.

This provider-first lowering rule is required because model developer identifies the content model, not the OpenRouter wire protocol.

## Frontend Behavior

Add `openrouter` to the provider values, labels, badge mapping, and all supported locale message files.

The existing `ApiKeyForm` handles create, edit, and secret replacement. Stored API keys are never redisplayed.

`SetupGuide` adds OpenRouter-specific copy covering:

- where to create an OpenRouter API key;
- that the model catalog and available routes depend on the OpenRouter account and API-key settings;
- that requests may be routed to upstream providers;
- that retention, training, and zero-data-retention requirements must be configured in OpenRouter;
- that Azents does not independently claim or enforce ZDR in the first release;
- that changing OpenRouter account policy requires a catalog refresh before the picker reflects the new available set.

The model picker requires no OpenRouter-specific layout. It already supports large integration catalogs through search, pagination, status, stale warnings, and explicit sync.

Add or update colocated Storybook stories for the provider option and setup-guide disclosure states.

## Error Handling

### Catalog synchronization

Use the existing listing failure policy:

- `401`: invalid or revoked API key; automatic retry blocked until credential change or explicit retry;
- `402`: account credit or payment requirement; automatic retry blocked;
- `403`: account, API-key, provider-policy, or permission restriction; automatic retry blocked;
- `404`: invalid fixed endpoint or unsupported account surface; automatic retry blocked and visible as catalog failure;
- `408`, `409`, `425`, `429`, transport failures, and `5xx`: retryable after existing backoff;
- malformed JSON or invalid top-level response: retryable invalid-provider-response failure.

A failed initial sync does not roll back integration creation. When no successful snapshot exists, the picker shows the existing failed-without-snapshot state. Later failures preserve the last successful snapshot.

### Model execution

Reuse the common `ModelProviderFailure` classifier. Authentication, payment, permission, model-not-found, rate-limit, and provider-unavailable responses keep their existing bounded, redacted user presentation and Run retry budget. Provider-authored messages are never allowed to include request headers or raw credentials in Azents diagnostics.

A selectable model can still fail because of account credits, upstream route availability, account policy changes, or model retirement after the last catalog sync. That is an explicit provider failure, not a reason to reintroduce an Azents allowlist.

## Security and Privacy

- API keys use the existing encrypted provider-secret storage and redacted public response contract.
- The catalog and runtime use fixed Azents-owned OpenRouter URLs; no workspace-controlled URL reaches the server network boundary.
- API keys, authorization headers, raw provider responses containing request data, and routing details are excluded from logs and test evidence.
- Only `X-OpenRouter-Title: Azents` is added for attribution; deployment-domain disclosure is avoided.
- Azents does not duplicate OpenRouter routing or data-policy settings and does not claim that a model or request is ZDR.
- Setup copy makes the external policy boundary visible before users rely on the integration for sensitive data.

## Migration and Rollout

1. Generate and apply the additive `llm_provider` enum migration.
2. Deploy backend provider identity, credentials, provider capability API, listing adapter, projection, and runtime lowering.
3. Regenerate OpenAPI specifications and public Python/TypeScript clients.
4. Deploy frontend provider selection, labels, setup disclosure, and stories.
5. Create or update OpenRouter integrations; the existing initial sync trigger builds their first account-scoped snapshots.
6. Run deterministic E2E and backend/runtime checks.
7. Run optional live verification with a dedicated low-privilege OpenRouter key before declaring representative Responses features verified.
8. Update living specs in the implementation PR.

Rollback hides OpenRouter from the provider capability list and can disable existing integrations. The PostgreSQL enum value remains. Existing Agent snapshots referencing OpenRouter remain readable but cannot run successfully if their integration is disabled or the runtime implementation is rolled back.

## Test Strategy

### E2E Primary Verification Matrix

| Scenario | Expected result | Execution |
|---|---|---|
| Provider discovery | Capability API exposes stable `openrouter` with credential type `api_key` | Deterministic API E2E |
| Create integration | Owner creates an OpenRouter integration; response omits the API key and creates an integration catalog | Deterministic API E2E |
| Direct catalog projection | Deterministic integration listing publishes every candidate without LiteLLM-match hiding | Deterministic API E2E and backend projection test |
| Large picker behavior | OpenRouter integration catalog uses search, pagination, sync state, and stale-state UI without provider-specific layout | Web Surface E2E or component/story coverage |
| Model selection snapshot | A projected OpenRouter model is saved with exact provider id and `openrouter/` runtime id | Deterministic API E2E |
| Unknown publisher | Unknown publisher becomes developer `other` and receives no Anthropic cache/tool dialect | Backend catalog and lowerer tests |
| Function tool lowering | Supported model sends standard function tools through LiteLLM Responses | Backend adapter test |
| Web search lowering | OpenRouter capability lowers to `{ "type": "openrouter:web_search" }` | Backend lowerer test |
| Prompt cache safety | OpenRouter Claude model receives no Anthropic `cache_control` hints | Backend lowerer regression test |
| Provider errors | OpenRouter 401/402/403/404/429/5xx and malformed listing responses map to catalog or runtime failure state correctly | Backend adapter/service tests |
| Routing boundary disclosure | Setup guide explains external routing and data-policy ownership | Component story and Web Surface E2E |
| Live account catalog | Authenticated `/models/user` returns account-filtered text-output models and publishes a snapshot | Optional live external E2E |
| Live Responses smoke | Representative OpenAI-, Anthropic-, Google-, and unknown-publisher text models stream text; supported cases exercise tools/reasoning/web search | Optional live external E2E |

### Deterministic Fixture and Seed Requirements

Use the existing testenv deterministic model-listing integration-name fixture so product APIs create the integration and catalog through normal paths without calling OpenRouter. No direct database writes are added.

The deterministic listing must include at least:

- one known publisher model;
- one unknown publisher model;
- image-input metadata;
- function-tool and reasoning metadata;
- a candidate absent from the LiteLLM source snapshot.

If the shared deterministic fixture cannot express the source metadata needed for OpenRouter capability assertions, extend its provider-specific candidate construction rather than adding a direct repository or database setup path.

### Live Prerequisite Snapshot

Optional live tests require an operator-provided OpenRouter API key. Testenv prerequisite preparation records only safe readiness metadata such as present/missing and preparation time. It must not store or print the key.

Live evidence is limited to:

- provider and model identifiers;
- catalog counts and bounded skipped-reason counts;
- normalized capabilities;
- terminal status and redacted provider-failure category;
- token and cost usage when returned.

Prompts, responses, credentials, headers, and account routing settings are excluded from durable evidence.

### CI and Skip/Fail Policy

- Backend enum, credential, listing, projection, sync, mapping, lowerer, output-normalization, and failure tests run in normal CI.
- OpenAPI generation and generated-client checks run in normal CI.
- Frontend format, lint, typecheck, build, and component/story tests run in normal CI.
- Credential-free deterministic API and Web Surface E2E must pass.
- Live OpenRouter tests are marked `live_external` and do not run in required credential-free CI lanes.
- Optional scheduled live verification skips with a prerequisite-not-ready summary when no key exists.
- Explicitly requested live verification fails when the prerequisite is missing or a required representative smoke scenario fails.

## Required Living Spec Updates

Implementation updates:

- `docs/azents/spec/domain/model-catalog.md` — add OpenRouter integration catalog source, direct projection, capability mapping, and sync behavior;
- `docs/azents/spec/flow/openrouter-api-key.md` — document provider identity, credentials, catalog, runtime, UI, security, and verification behavior;
- `docs/azents/spec/domain/agent.md` only if implementation changes generic model-selection snapshot behavior beyond adding enum values;
- `docs/azents/spec/flow/agent-execution-loop.md` only if shared Responses behavior changes rather than remaining an OpenRouter provider-dialect branch.

## Alternatives Rejected

### Curated OpenRouter allowlist

Rejected because it removes OpenRouter's primary value and requires an Azents release for each model addition.

### LiteLLM metadata intersection

Rejected because metadata lag would hide valid account-available models. LiteLLM is the runtime adapter, not the OpenRouter visibility authority.

### OpenAI SDK with a custom base URL

Rejected because Azents' native OpenAI path owns OpenAI-specific transport, storage, continuation, and WebSocket behavior. OpenRouter belongs on the existing generic LiteLLM Responses path.

### Azents-owned routing and privacy controls in the first release

Rejected because they duplicate OpenRouter account policy, introduce conflicting control layers, and can reduce route and model availability. They can be designed later as centralized workspace policy if required.

### Unknown publisher fallback to Anthropic

Rejected because it can add invalid cache-control hints and hosted-tool dialects to unrelated models.

### User-provided base URL

Rejected because it expands the server-side request trust boundary and is a separate custom-provider feature.

## Risks and Follow-ups

- OpenRouter's Responses surface and metadata may evolve independently from the pinned LiteLLM adapter. The implementation must pin tests to the repository's LiteLLM version and use optional live verification to detect drift.
- Model metadata can overstate route-specific capability. Runtime provider failures remain possible even when a capability is advertised.
- Provider-level web search can add external cost and data flow beyond the selected model route; setup and capability UI should identify it as an OpenRouter-hosted capability.
- Strict structured outputs, additional media, prompt caching, image generation, and Azents-owned routing/privacy policy require separate verification and design before activation.
- The model picker can contain hundreds of entries; existing search and pagination are required, and observed usability may justify additional provider-neutral filters later without introducing an allowlist.
