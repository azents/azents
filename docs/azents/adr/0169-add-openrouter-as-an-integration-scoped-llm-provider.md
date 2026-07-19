---
title: "ADR-0169: Add OpenRouter as an Integration-Scoped LLM Provider"
created: 2026-07-19
tags: [architecture, backend, frontend, engine, llm, security]
---

# ADR-0169: Add OpenRouter as an Integration-Scoped LLM Provider

## Status

Draft. Records decisions confirmed during design discussion.

## Topic

Define the catalog, runtime, routing, and data-policy boundaries for adding OpenRouter as an API-key LLM provider in Azents.

## Context

OpenRouter provides one account-scoped API surface for models from many publishers. Its primary product value is that users can try newly available models without waiting for Azents to add each model individually.

Azents already distinguishes system catalogs from integration-scoped catalogs and projects provider model metadata into a canonical capability contract. OpenRouter model availability depends on the API key and the account's provider preferences, while its catalog changes more quickly than an Azents release cycle or a bundled LiteLLM metadata snapshot.

A curated Azents allowlist would make OpenRouter behave like a small set of separately integrated providers and would remove the main reason to support it. At the same time, catalog visibility must remain separate from capability claims: exposing a model does not mean Azents can safely advertise every modality, parameter, hosted tool, or provider-specific optimization reported for that model.

## Goals

- Preserve OpenRouter's ability to expose arbitrary account-available models without Azents releases.
- Keep model availability scoped to the configured OpenRouter integration.
- Separate model visibility from conservative Azents capability projection.
- Reuse Azents canonical model selection and LiteLLM Responses runtime boundaries.
- Define explicit ownership for OpenRouter routing and data-policy controls.

## Non-goals

- Maintain an Azents-curated OpenRouter model allowlist.
- Guarantee identical capability behavior across every upstream model and provider route.
- Add a user-configurable OpenRouter-compatible base URL.
- Treat OpenRouter publishers as separate Azents credential providers.

## Constraints

- Agent model selection keeps existing snapshot semantics.
- Catalog reads use stored projections rather than calling OpenRouter on the normal read path.
- OpenRouter credentials remain backend-only and use the existing API-key secret contract.
- Unknown model publishers must not inherit another publisher's provider-specific lowering behavior.
- Unsupported or unverified capabilities must be hidden without hiding an otherwise usable text-output model.

## Decision Todo

- [x] Decide the OpenRouter model exposure policy.
- [x] Decide whether OpenRouter account preferences are the routing and data-policy control surface for the first release or whether Azents must own additional controls.
- [x] Define conservative capability projection and provider-specific lowering behavior.
- [x] Define catalog synchronization, failure, and stale-snapshot behavior within the existing integration catalog lifecycle.
- [x] Define rollout, E2E verification, and optional live-provider test requirements.

## Confirmed Decisions

### ADR-0169-D1. Expose all account-available text-output models without an Azents allowlist

OpenRouter uses an integration-scoped catalog populated from the authenticated account model endpoint, filtered to text-output models.

Azents exposes every returned model that has a usable provider model identifier and can be represented by the OpenRouter runtime path. Azents does not apply a curated model, publisher, family, or provider allowlist, and model visibility does not require a matching entry in the bundled or synchronized LiteLLM catalog.

OpenRouter account configuration and upstream availability may still determine which models the authenticated endpoint returns. Azents does not add a second product-level selection restriction on top of that result.

Capability projection is independent from visibility. Azents advertises only capabilities that can be mapped and lowered safely. Missing, unknown, or unverified capability metadata disables the affected capability rather than hiding the text-output model. Unknown publishers use a neutral developer classification and do not inherit Anthropic, OpenAI, Google, or other publisher-specific lowering behavior.

This preserves OpenRouter's core value: newly available models become selectable after integration catalog synchronization without an Azents code change or release.

### ADR-0169-D2. Delegate upstream routing and data policy to OpenRouter account controls in the first release

OpenRouter account and API-key settings are the routing and data-policy control surface for the first Azents release. Azents does not add integration fields for upstream provider order, provider allow or deny lists, fallback policy, zero-data-retention routing, or provider data-collection policy.

Runtime requests use the selected OpenRouter model identifier without an Azents-owned provider-routing override. OpenRouter therefore applies the account's provider preferences and guardrails. Azents does not weaken, duplicate, or attempt to infer those policies.

The OpenRouter integration setup and model-selection surfaces must disclose that requests can be routed to upstream providers and that routing, retention, and provider data-handling policy are controlled in OpenRouter. Azents must not claim that an integration or model is zero-data-retention unless Azents can verify and enforce that property in a future design.

This boundary keeps the first release compatible with the widest account-available model set and avoids two independently configured policy layers. Azents-owned integration-level routing or privacy controls may be introduced later through a separate decision if customer demand requires centralized policy management inside Azents.

### ADR-0169-D3. Project OpenRouter account metadata directly with a neutral unknown-publisher classification

OpenRouter model listing is projected directly from the authenticated account catalog. A matching LiteLLM metadata entry is not required for visibility or selection. LiteLLM metadata may remain attached as lowerer-target diagnostics, but it does not add models, remove models, or override OpenRouter capability metadata.

Model developer remains separate from hosting provider. Recognized OpenRouter publisher segments map to existing Azents developer values. Every unrecognized publisher maps to a new neutral `other` developer value. Unknown publishers never inherit Anthropic or another known developer's cache, hosted-tool, or media behavior.

Capability projection is conservative and field-specific. Azents enables only metadata-backed capabilities that the current runtime can lower, while missing or unverified fields remain disabled or unknown. Capability uncertainty does not make an otherwise valid text-output model unselectable.

### ADR-0169-D4. Reuse LiteLLM Responses with OpenRouter-owned wire semantics

OpenRouter runtime requests use the existing LiteLLM Responses adapter with runtime model identifiers prefixed by `openrouter/`. OpenRouter does not enter Azents' native OpenAI SDK transport path.

Provider wire semantics take precedence over model-developer semantics. OpenRouter web search lowers to the Responses server-tool type `openrouter:web_search`, and Anthropic cache-control hints are disabled even when the selected OpenRouter model is developed by Anthropic. Hosted image generation and other unverified provider features remain unavailable in the first release.

Azents uses the fixed OpenRouter API origin and generic encrypted API-key integration contract. Workspace users cannot supply a custom API base. Optional application attribution does not include the Azents deployment domain.

### ADR-0169-D5. Reuse the existing integration-catalog lifecycle and verify product behavior E2E-first

OpenRouter uses the existing integration-catalog creation, background initial sync, explicit sync, stale refresh, attempt fencing, cooldown, backoff, failure-state, and last-successful-snapshot behavior. No OpenRouter-specific catalog lifecycle is introduced.

Credential-free product verification uses the existing deterministic integration-listing fixture through public product APIs. Live account catalog and inference checks are optional external E2E scenarios using an operator-provided credential and safe prerequisite snapshots. Tests do not write directly to the product database or retain credentials, prompts, or provider responses as evidence.

## Consequences of Confirmed Decisions

### Positive

- Users can try the full set of models available to their OpenRouter account.
- New model availability does not depend on Azents or LiteLLM catalog release timing.
- Azents avoids a high-maintenance allowlist that would drift quickly.
- Conservative capability projection can evolve independently from model visibility.
- OpenRouter routing and privacy configuration has one authoritative control surface.
- The first release does not require a new Azents routing-policy data model or UI.

### Trade-offs and Risks

- The model picker can contain a large and rapidly changing catalog.
- OpenRouter metadata quality and capability declarations can vary by model.
- Some selectable models may fail at runtime because of upstream entitlement, credits, provider availability, or route-specific behavior.
- Search, pagination, catalog diagnostics, and clear provider failure messages are required for a usable experience.

## Alternatives Considered

### Curate an Azents OpenRouter model allowlist

Rejected because it removes OpenRouter's primary value, requires continuous maintenance, and delays access to new models until an Azents release.

### Require a LiteLLM catalog match before exposing a model

Rejected because LiteLLM metadata can lag OpenRouter's live catalog. LiteLLM remains the runtime adapter in the first implementation, but its metadata snapshot is not an OpenRouter visibility gate.

## Related Documents

- [ADR-0030: Move LLM Model Catalog to External Sources and Local Overrides](./0030-llm-model-catalog-source.md)
- [ADR-0067: Model Catalog Projection and Sync](./0067-model-catalog-projection-sync.md)
- [ADR-0165: Make Model Provider Failures Transparent](./0165-make-model-provider-failures-transparent.md)
- [ADR-0166: Resolve built-in capabilities to model-specific executors](./0166-resolve-builtin-capabilities-to-model-specific-executors.md)
- [ADR-0167: Normalize Provider Tool Semantic Transcript Content](./0167-normalize-provider-tool-semantic-transcript.md)
