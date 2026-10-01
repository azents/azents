---
title: "Provider-Library Replacement Decisions"
created: 2026-09-30
updated: 2026-09-30
tags: [inference, engine, model-catalog, migration]
document_role: primary
document_type: adr
snapshot_id: inference-260930
---

# Provider-Library Replacement Decisions

- Snapshot: `inference-260930`
- Document reference: `inference-260930/ADR`
- Requirements: [inference-260930/REQ](../requirements/inference-260930-provider-replacement.md), confirmed on 2026-09-30 (KST).
- Mode: Collaborative. The requester owns unresolved material technical decisions.

## Context

The requester selected Pydantic AI as the replacement for LiteLLM. This ADR does not reopen that library choice. The approved scope removes the executable LiteLLM dependency, including non-inference uses, while preserving currently supported provider and conversation behavior. Abandoning LiteLLM's public metadata source is not a confirmed requirement.

Current behavior is established by the [Agent Execution Loop Spec](../spec/flow/agent-execution-loop.md), [Conversation Spec](../spec/domain/conversation.md), and [Model Catalog Spec](../spec/domain/model-catalog.md), checked against repository base `fd0093423a3b7ecf714a67603eabb339e1962bef`.

- OpenAI and ChatGPT OAuth use the official OpenAI SDK for sampling, title generation, and compaction. Their cost estimation still depends on LiteLLM.
- The remaining eight provider/credential variants use LiteLLM Responses for those conversation-model operations. xAI is a first-class provider identity with a shared transport dependency in the current implementation.
- Catalog authority is the latest validated remote metadata snapshot in the database, not the process-local package map or bundled diagnostic fallback.
- Native OpenAI cost estimation currently uses the installed package's process-local pricing map, not that authoritative catalog snapshot. Retaining a catalog source therefore does not automatically determine the new price-estimation authority.
- Provider/account model listing and optional enrichment have different authority across integrations. A pricing dataset or library model profile cannot silently replace account visibility or the saved capability contract.

## Fixed and Derived Outcomes

These are authority-grounded constraints, not new choices for the requester:

- Pydantic AI is the selected replacement. The executable LiteLLM package and all runtime imports must disappear under REQ-1.
- The Azents execution engine, tool execution, approval, Run retry, scheduling, and persistence ownership remain unchanged under the confirmed non-goals and REQ-4/REQ-5. Pydantic integration is confined to provider model interaction; it does not introduce a second agent execution engine.
- Already-independent OpenAI/ChatGPT SDK inference paths remain outside the replacement boundary. Their ancillary LiteLLM dependencies must still be removed under REQ-1. Existing HTTP/WebSocket and continuation behavior remains governed by the current execution-loop spec.
- Canonical history and exact native compatibility remain authoritative under REQ-3. Existing cross-adapter fallback supplies continuity; interpreting another adapter's opaque artifact or widening replay authorization is not an option.
- Existing credential variants, supported tools, timeout/Stop/failure contracts, conservative capabilities, unknown-cost semantics, and safe diagnostics remain required under REQ-2 through REQ-7.
- Direct dependency pins may change. Current pin values do not veto the selected direction.
- This is design-only. Requirements confirmation does not approve implementation, deployment, or the completed Design.

## Material Decision Map

The complete current map was briefed before opening an individual decision. A queued topic is not an accepted decision. Each topic must pass decision admission: at least two viable alternatives with materially different outcomes, no outcome already fixed by approved authority, and a choice needed for the Design. Evidence that eliminates alternatives is recorded as a feasibility finding instead of a redundant requester choice.

### Q1. Catalog metadata authority — accepted as D1

- Authority: `inference-260930/REQ-1`, `inference-260930/REQ-6`, and `inference-260930/REQ-8`.
- Question: retain the current external capability/context metadata source independently of its Python package, or replace it with an independently maintained equivalent source?
- Material difference: external source authority and schema maintenance versus ownership of capability data, its updates, publication, and parity verification.
- Existing validated-snapshot, provider visibility, last-good, conservative projection, and fencing behavior remain fixed. Neither a library profile nor a price-only dataset is assumed to supply equivalent catalog authority.
- The requester selected source retention for this snapshot and deferred source replacement to later work. See `inference-260930/ADR-D1`.

### Q2. Cost-estimation authority — current

- Authority: `inference-260930/REQ-1` and `inference-260930/REQ-7`.
- Question: which source and calculation boundary replaces the package's cost calculator and process-local price map while preserving nullable, tier-aware, content-free estimates and provider-reported charges?
- Material difference: price source, refresh/provenance lifecycle, model matching, supported service tiers, and calculation maintenance.
- Independent of Q1: retaining a capability source does not require using it as the estimator's pricing authority.
- Unknown pricing must remain unknown. No broad alias match or unsupported tier fallback is authorized by choosing a calculator.

### Q3. Credential-specific provider transport boundaries — pending feasibility admission

- Authority: `inference-260930/REQ-2`, `inference-260930/REQ-4`, and `inference-260930/REQ-5`.
- Focus: xAI API-key versus OAuth transports, plus cloud/compatible endpoint variants where a generic model path cannot preserve the existing contract.
- Material difference, when alternatives prove viable: transport, SDK/client ownership, credential support, hosted-tool representation, timeout/cancellation, and operational dependencies.
- API-key documentation or offline mocks do not establish OAuth entitlement or authenticated transport viability. No supported credential route may be removed to simplify adoption.

### Q4. Native stream fidelity and maintenance ownership — pending feasibility admission

- Authority: `inference-260930/REQ-3`, `inference-260930/REQ-4`, and `inference-260930/REQ-5`.
- Focus: sufficient successful-terminal evidence and preservation of currently supported native data that the common model response does not expose.
- Material difference, when alternatives prove viable: maintaining provider-specific supported SDK observation/model extensions versus relying on an upstream-supported implementation; any maintained fork requires its own explicit decision.
- Logical completion, first content, final-result selection, and native successful termination must not be conflated. The existing durable admission and failure contract remains fixed.
- Current canonical hosted-tool source references and opaque native annotation retention are distinct preservation surfaces. This topic does not add a new canonical citation product feature.

### Q5. Persisted/public identity transition and removal boundaries — pending feasibility admission

- Authority: `inference-260930/REQ-3`, `inference-260930/REQ-6`, and `inference-260930/REQ-8`.
- Focus: runtime model identifiers, catalog lowerer target, public/generated representations, historical source provenance, and shared image-catalog state.
- Material difference, where needed: preserving still-correct source identifiers versus changing obsolete transport identities, and the operational/persistence boundary of that transition.
- Historical source and native artifact names do not imply executable package retention. Conversely, package removal does not authorize deleting historical state or relabeling provenance.
- No parallel legacy runtime mode, new compatibility alias, or destructive migration is silently introduced. Existing documented canonical fallback remains the continuity authority.

## Product Questions

None is currently blocking the confirmed scope. A proposed capability loss, new user reconfiguration requirement, additional mandatory external-source independence, or changed observable completion/cost behavior returns to Requirements before the affected decision proceeds.

## Agent-Owned Implementation Details

Equivalent helper boundaries, filenames, local type composition, fixture names, and direct-versus-convenience model-call wrappers are agent-owned when they add no new behavior, state, configuration, lifecycle, or authority. SDK/client settings needed to comply with existing timeout, credential isolation, retry, and privacy contracts are derived compliance work, not opportunities to renegotiate those contracts.

## Accepted Decision Log

Accepted choices are recorded below as `inference-260930/ADR-D1`, `inference-260930/ADR-D2`, and so on. Each entry records affected Requirements, selected outcome, rejected alternatives, consequences, and feasibility conditions. Accepted entries are append-only.

### D1. Retain the public catalog metadata source independently of its executable package

- Reference: `inference-260930/ADR-D1`.
- Accepted: 2026-09-30 (KST), by the requester.
- Authority: `inference-260930/REQ-1`, `inference-260930/REQ-6`, and `inference-260930/REQ-8`.
- Scope: catalog capability and context metadata authority. Price-estimation authority is outside this decision.

**Decision**

Retain the currently configured public LiteLLM JSON source for catalog metadata during this replacement. Azents owns the source parsing and validation boundary without importing or installing LiteLLM. Preserve validated remote-source ingestion and authoritative DB snapshots, provider/account visibility rules, conservative capability projection, alias handling, last-good retention, destructive-reduction safeguards, and publication fencing.

Remove all executable LiteLLM dependencies as required by REQ-1. Keeping the upstream dataset does not keep the Python package, its SDK constraints, its runtime transport, or its cost calculator.

Defer replacement of the public metadata source to a separate future development snapshot. This deferral is not a scheduled task, automatic transition, runtime switch, or approval to introduce another metadata authority in the current snapshot.

**Alternative not selected for this snapshot**

Replace the source with provider-authoritative discovery plus an independently maintained normalized capability feed and supplementary mappings. This remains a possible later direction, but establishing equivalent field/model coverage and taking on data maintenance/publication responsibility would expand this replacement's technical scope and verification burden.

**Consequences and boundaries**

- Preserve the current source of capability/context metadata rather than coupling the provider-library cutover to a second catalog-data migration.
- Azents-owned validation must cover the currently consumed fields and cloud/provider identifier mappings; a replacement library profile is not a second catalog authority.
- Source identifiers and historical provenance may truthfully continue to refer to LiteLLM data. Obsolete transport identities and package-derived diagnostic/version access still require the explicit removal boundaries covered by Q5 and the Design.
- Installed-package map, bundled backup access, metadata schema imports, and package-version lookup cannot survive as executable dependencies. Their replacement/removal must not silently publish diagnostic fallback as source authority.
- This decision does not select the pricing dataset, change tier-aware estimation, or authorize automatic use of the catalog snapshot for cost estimation. Q2 remains independent.

**Feasibility and verification**

The current ingestion/projection uses identifiable JSON fields and existing authoritative DB state, so retaining the source does not require retaining the executable package. Required verification covers package-free parsing and alias expansion, current capability/model coverage, source failure and destructive-reduction quarantine, last-good retention, read-without-fetch behavior, publication fencing, and integration-specific visibility. These are implementation verification obligations, not already-completed integration tests.

### D2. Normalize retained public-source prices and estimate costs in Azents

- Reference: `inference-260930/ADR-D2`.
- Accepted: 2026-09-30 (KST), by the requester.
- Authority: `inference-260930/REQ-1`, `inference-260930/REQ-7`, and `inference-260930/REQ-8`.
- Related decision: `inference-260930/ADR-D1`.
- Scope: price-estimation source, calculation ownership, and the boundary between reported charges and estimates.

**Decision**

Use explicitly normalized pricing data from validated snapshots of the retained public LiteLLM JSON source and an Azents-owned estimator. Separate source-specific price ingestion from the calculation contract so a later source replacement need not change provider interaction or usage normalization.

This deliberately replaces the installed package's process-local price map and cost calculator with a snapshot-backed pricing authority. The estimator must identify the applicable source snapshot, provider/model mapping, and service tier. It receives usage and necessary billing metadata, not model output content.

Preserve supported cache, tier, context-threshold, and other currently applicable billing rules through explicit normalization and verification. Do not reduce estimation to multiplying two standard token rates when the existing route requires additional rules.

Explicit provider-returned charges remain distinguishable from estimates. Choosing this estimator does not authorize silently replacing a reported charge with a calculated value or treating an SDK/library estimate as a provider-authored charge.

Unavailable, unmatched, invalid, or unsupported pricing remains unknown (`null`). An unsupported priority tier is not priced as standard, and missing pricing evidence alone does not turn a successfully completed provider response into a failed model operation.

**Alternative not selected for this snapshot**

Use `genai-prices` as a separate price-data and calculation authority, with explicit provider/model/tier supplementation. This would add a different pricing source and refresh lifecycle during the transport replacement, while still requiring verification of current tier/cache/threshold behavior.

The replacement library may depend transitively on a pricing package; that presence does not make its bundled data, automatic `cost()` result, model profile, or background price refresh an estimation authority for Azents.

**Consequences and boundaries**

- Reuse the retained validated-source lifecycle and last-good data rather than making a remote pricing lookup for each model response.
- Define a dedicated normalized pricing contract. Current catalog capabilities and xAI's bounded standard-price enrichment are not a complete tier-aware price schema.
- Azents owns price-rule maintenance and provider/model/tier mapping. Broad heuristic aliases, unknown premium-to-standard fallback, double counting reasoning/cache usage, or fabricated tool/image charges are not authorized.
- Price-source identity and calculation provenance must be explicit. Any needed durable/API representation is specified in the Design and the applicable Q5 transition boundary; this decision does not introduce a new cost-detail UI.
- Establish snapshot availability and bootstrap behavior without retaining installed-package fallback or silently promoting unvalidated data as price authority. Missing evidence is nullable and cannot become a model-execution prerequisite.
- Existing successful usage normalization remains independent of price availability. Programming/internal estimator errors retain their existing observability/error classification rather than being hidden by an unrestricted catch-and-return-zero path.

**Feasibility and verification**

The retained JSON contains pricing fields, but adopting snapshot-backed normalized prices and owned calculations is new work. Required verification includes content-free estimation, exact provider/model mapping, cache read/write and reasoning accounting, supported service tiers (including the current Fast-to-priority normalization), context-dependent rates, applicable tool/media billing, unknown/invalid price handling, reported-charge provenance, source failure/last-good behavior, and snapshot bootstrap. Compare supported calculations against explicit fixtures and current expected semantics; package-level mock probes are not proof of this estimator's correctness.

## Decision Progress After D2

- Q1: accepted as `inference-260930/ADR-D1`; public catalog-source replacement is deferred.
- Q2: accepted as `inference-260930/ADR-D2`; normalized retained-source prices and Azents-owned estimation.
- Q3: current evidence lane; credential-specific transport alternatives still require feasibility admission.
- Q4: pending evidence and decision admission; existing stream/fidelity contracts remain fixed.
- Q5: pending evidence and decision admission; no destructive identity/state migration is accepted.
- Primary Design, Design approval, implementation, and deployment remain pending or unauthorized.

### D3. Use HTTP for both xAI API-key and OAuth inference

- Reference: `inference-260930/ADR-D3`.
- Accepted: 2026-09-30 (KST), by the requester.
- Authority: `inference-260930/REQ-1`, `inference-260930/REQ-2`, `inference-260930/REQ-4`, and `inference-260930/REQ-5`.
- Scope: xAI API-key and xAI OAuth conversation-model transport, including sampling, title generation, and compaction.

**Decision**

Use HTTP for both xAI credential identities through the Pydantic model interaction boundary and supported official SDK APIs. Retain the existing Azents Responses request/response contract for the currently supported routes. Preserve provider-specific request conversion, explicit xAI model profiles, configured endpoint behavior, and typed output/failure handling rather than assuming a stock OpenAI-compatible model is a drop-in replacement.

Keep `xai` and `xai_oauth` as separate provider/integration identities with their existing credential refresh, account-visible models, billing, and entitlement semantics. An OpenAI-compatible SDK client configured for xAI is an xAI route; it does not select the OpenAI provider, send xAI credentials to OpenAI, or change integration ownership.

Do not introduce the xAI chat gRPC transport or a credential/endpoint-based HTTP/gRPC hybrid in this snapshot. There is no gRPC-failure-to-HTTP fallback mode. This decision does not remove existing Run retries or model-candidate recovery.

**Alternatives not selected**

- API-key gRPC for canonical endpoints with HTTP retained for OAuth/custom endpoints: adds another transport and its routing, lifecycle, native-output, and verification obligations during the dependency cutover.
- All-gRPC, including OAuth: no affirmative OAuth inference compatibility evidence was established. The latest inspected Grok Build public source uses HTTP JSON/SSE for its OAuth inference; that is not proof that developer gRPC rejects OAuth, but it is not evidence that it accepts it.

**Endpoint and credential boundary**

HTTP selection does not independently authorize changing Azents' current OAuth default endpoint to the latest CLI proxy or copying the CLI's authentication/retry policy. Preserve existing explicit endpoint configuration and supported credential behavior. The CLI's OAuth/session proxy default and Azents' existing default are a feasibility finding to verify, not permission for a silent endpoint migration.

No new OAuth connection flow, user reconnection requirement, automatic endpoint discovery, or extra provider capability is introduced. Any endpoint change needed to satisfy the confirmed behavior returns to its applicable authority/decision lane before implementation.

**Consequences and verification**

- The LiteLLM executable transport disappears while the existing xAI HTTP protocol remains the server-facing boundary.
- Explicit profiles and lowering must retain xAI system-input, hosted-search, cache-hint, generation-option, client-tool, and model-identifier semantics.
- Sampling, title generation, and compaction retain their credential resolution and bounded-operation lifecycle.
- Validate API-key and OAuth routes separately, including endpoint overrides, safe auth failures, refresh-before-dispatch, hosted-tool references, exact native compatibility, terminal proof, usage, watchdog, Stop, and cleanup.
- Q4 still determines how missing native observations are owned and preserved. This decision does not choose a library fork, private monkeypatch, raw-frame logging, or a particular observer implementation.
- Source inspection establishes a credible public Model/SDK implementation boundary; full Azents integration and authenticated provider verification are not already complete.

## Decision Progress After D3

- Q1: accepted as `inference-260930/ADR-D1`.
- Q2: accepted as `inference-260930/ADR-D2`.
- Q3: accepted as `inference-260930/ADR-D3`; xAI API-key and OAuth both use HTTP.
- Q4: current; native completion/fidelity preservation is required, but its maintenance boundary is not selected.
- Q5: pending; truthful persisted/public identities and shared catalog removal boundaries still require framing.
- Primary Design, Design approval, implementation, and deployment remain pending or unauthorized.

### D4. Reuse model assembly with supported native observation for fidelity gaps

- Reference: `inference-260930/ADR-D4`.
- Accepted: 2026-09-30 (KST), by the requester.
- Authority: `inference-260930/REQ-3`, `inference-260930/REQ-4`, `inference-260930/REQ-5`, `inference-260930/REQ-7`, and `inference-260930/REQ-8`.
- Scope: maintenance ownership of native completion evidence, supported native data, and request-boundary observation missing from the common model representation.

**Decision**

Reuse the existing Pydantic model message and event assembly where it preserves
the supported route contract. Supplement missing evidence and data through
Azents-owned observation at supported official SDK extension boundaries. Keep
the observed information and the common response associated with the same
physical dispatch and Azents operation attempt.

Azents remains responsible for the existing completion and durable-admission
policy. Common response state, result-selection events, partial content, or EOF
alone do not replace the successful-completion evidence required by the route.
Preserve currently supported native information and canonical hosted-tool
references without introducing new citation presentation or a second transcript
authority.

Where supported observation cannot preserve a route's existing contract, use an
owned implementation of the public `Model`/`StreamedResponse` extension boundary
for that route. This is a bounded contract-preservation obligation, not a default
rewrite of all provider translators or a parallel selectable runtime mode.
Exact xAI HTTP lowering remains independently required by ADR-D3.

**Alternative not selected**

Own the complete native-to-common translation for every route needing
supplementation, even when supported observation can preserve the required
evidence and data while retaining upstream assembly. That places more provider
thinking, tool, usage, and schema evolution under Azents maintenance during this
cutover.

A maintained fork or private stock-model monkeypatch is not selected. If a route
requires a materially different maintenance or interface boundary beyond the
accepted public extensions, return it to the decision owner rather than
silently weakening fidelity.

**Consequences and boundaries**

- The observer is adapter-owned, attempt-local supplementary evidence, not a
  durable source of truth independent of canonical history or an authorization
  to replay incompatible artifacts. Q5 and the Design specify truthful new
  representation identities and their transition boundaries.
- Preserve the existing parsed-event idle clock, connect and absolute deadlines,
  Stop precedence, close grace, and noncooperative cleanup. Provider transports
  require their own supported observation and lifecycle paths; an HTTP/SSE hook
  is not assumed to cover every cloud SDK.
- Physical dispatch observation and control must prevent SDK retries or model
  recovery re-requests from bypassing the current engine-owned retry, invocation
  reconstruction, or native-history constraints. Disabling SDK retries alone is
  not sufficient evidence.
- Observe a single unchanged stream with bounded buffering and correct
  backpressure. Do not independently consume the SDK body twice, log raw frames,
  expose opaque reasoning, or enable additional prompt/output tracing.
- Preserve required native information only within the existing authorized
  native-artifact and privacy boundaries. Untrusted provider errors remain
  bounded and redacted; observer implementation errors are not disguised as
  successful model responses or generic provider failures.
- Concrete equivalent middleware, client, and transport placements are local
  implementation details only while ownership, lifecycle, dispatch controls,
  and supported interface boundaries remain unchanged.

**Feasibility and verification**

Pinned-source inspection identifies supported SDK observation and public model
extension seams. Existing offline/mock probes establish common-completion and
native-data gaps, not a completed Azents observer integration.

Required verification covers valid completion, content-only EOF,
stop-reason-only EOF, explicit provider failure, supported annotation and opaque
data retention, split or malformed input, late final usage, parsed events with
no semantic delta, concurrent dispatch isolation, hidden re-request control,
Stop/deadline/close races, and absence of tracing/error leakage. Demonstrate
unchanged SDK input consumption and exact native compatibility in deterministic
fixtures, then exercise preserved behavior through the E2E-first strategy.
Authenticated provider verification remains a separate prerequisite.

## Decision Progress After D4

- Q1: accepted as `inference-260930/ADR-D1`.
- Q2: accepted as `inference-260930/ADR-D2`.
- Q3: accepted as `inference-260930/ADR-D3`.
- Q4: accepted as `inference-260930/ADR-D4`; reuse assembly with supported native observation and bounded public model extensions where required.
- Q5: current framing lane; saved-selection continuity, immutable provenance, exact native compatibility, and shared image-catalog behavior remain fixed.
- No new product behavior, primary Design approval, implementation, or deployment is authorized.

### D5. Separate catalog identity from execution-library descriptors

- Reference: `inference-260930/ADR-D5`.
- Accepted: 2026-09-30 (KST), by the requester.
- Authority: `inference-260930/REQ-1`, `inference-260930/REQ-2`, `inference-260930/REQ-3`, `inference-260930/REQ-6`, and `inference-260930/REQ-8`.
- Scope: active catalog persistence and API identity, dispatch-time model resolution, and the shared conversation/image catalog transition.

**Decision**

Remove implementation-specific execution descriptors from the active catalog
contract. Catalogs retain semantic provider/model identity, purpose, ownership,
capabilities, account visibility, lifecycle, and source/projection evidence.
Adapters resolve the supported SDK/model dispatch from the selected provider,
exact provider model identifier, and authorized integration at call time.

Remove the persisted `lowerer_target` dimension from logical catalogs and
conversation entries, together with their obsolete enum and target-dependent
uniqueness. Remove stored `runtime_model_identifier` from active conversation
entries and the corresponding public catalog response field. Remove both
descriptors from newly created selection diagnostic snapshots. Coordinate the
repository, service, API, generated client, fixture, and test contracts in the
same cutover.

Keep the existing saved selection's provider, integration, raw model identifier,
and capability snapshot as the execution authority. Historical diagnostic
`model_snapshot` JSON need not be rewritten and must not become a legacy
dispatch input. No re-selection or reconnection is required solely for this
replacement.

**Alternative not selected**

Retain implementation-specific catalog descriptors with truthful route-specific
SDK/model targets and derived runtime identifiers. This preserves the public
runtime-ID field but continues coupling stored catalog data and its consistency
maintenance to SDK/adapter changes. A blanket replacement of `litellm` with
`pydantic_ai` would additionally misrepresent already-native and image routes.

**Migration and removal boundaries**

- Preserve catalog IDs, source references, current/latest snapshot and attempt
  links, capabilities, visibility, configuration-generation eligibility, and
  purpose separation. Change schema and active projection representation using
  a new migration; do not edit the executed baseline.
- Before removing the uniqueness dimension, verify that each existing semantic
  catalog identity has at most one catalog. Unexpected collisions fail
  migration with bounded diagnostics; do not silently merge or delete data.
- Preserve image-generation entries and SDK execution. Their shared logical
  catalog key changes structurally, not their supported providers, selection,
  default behavior, permissions, discovery, or publication policy.
- Retain still-authoritative public LiteLLM JSON provenance and historical
  content-addressed source snapshots under ADR-D1. Package-version evidence
  recorded historically is not relabeled as a newly installed version.
- Leave historical conversation artifacts and native representation identities
  unchanged. New adapter-native formats receive truthful identities; existing
  exact compatibility and canonical fallback remain governed by REQ-3.
- Resolve SDK inputs through explicit provider-aware lowering. Do not strip
  arbitrary slash prefixes from provider IDs, cloud resource names, or
  publisher-qualified identifiers.
- This cutover adds no legacy executable adapter, compatibility alias, optional
  transport selector, request-time catalog refresh, or new user setup flow.

**Feasibility and verification**

Current code stores semantic selection separately and derives execution strings
at dispatch, so removing catalog descriptors does not require rewriting user
selections. The public entry response exposes `runtime_model_identifier` but
not `lowerer_target`; service and diagnostic snapshots contain both. Image
entries share the logical catalog row but not the conversation runtime-ID field.

Required verification covers an existing-database upgrade without remote model
or source fetches, new-database migration, uniqueness and foreign-key preservation,
last-good reads, concurrent publication fencing, old selection continuation,
exact cloud and publisher-qualified model lowering, public schema/client
regeneration, descriptor absence on new output, and unchanged image-generation
behavior. Source inspection is not an executed migration or authenticated
integration test.

## Decision Progress After D5

- Q1 through Q5: accepted as `inference-260930/ADR-D1` through `inference-260930/ADR-D5`.
- Current product questions: none blocking the confirmed scope.
- Complete primary Design, authority and feasibility validation, and
  revision-bound requester Design approval are next.
- Implementation and deployment remain outside this design-only snapshot.
