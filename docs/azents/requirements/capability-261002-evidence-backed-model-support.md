---
title: "Evidence-Backed Model Support Requirements"
created: 2026-10-02
tags: [model-catalog, backend, engine, metadata]
document_role: primary
document_type: requirements
snapshot_id: capability-261002
---

# Evidence-Backed Model Support Requirements

- Snapshot: `capability-261002`
- Document reference: `capability-261002/REQ`

## Problem

The current catalog can lose capabilities declared for an exact provider/model when a narrower generic compatibility profile replaces or intersects that evidence. Reasoning effort levels such as `xhigh` and `max` are affected, but the same authority problem also applies to tools, structured output, modalities, request parameters, and token limits. Missing listing fields can also be mistaken for explicit denials.

The earlier LiteLLM-backed catalog contained useful model facts, but restoring its identity heuristics or old persistence wholesale would recreate problems rather than establish reliable model support. The immediate pre-cutover collector was already independent of the execution library. The redesign must recover justified behavior while separating model facts from the selected execution path's actual limitations and consolidating capability and price data without retaining a second active pricing source.

## Primary Context

### Primary System Outcome

Azents publishes evidence-backed model support and truthful estimated prices from one maintained catalog data basis, and carries supported user choices to existing provider routes without metadata-induced loss, while retaining independent execution adapters, durable catalog operation, and stable saved selections.

## Supporting Scenarios or Effects

- Users can select supported reasoning levels and implemented model features without waiting for an unrelated model-profile update.
- Operators can refresh model metadata independently of application deployment and diagnose the source of a projected fact or a rejected update.
- Existing Agent and Workspace selections remain stable while new catalog projections become available.
- Historical behavior and prior regression repairs are explicitly accounted for instead of being lost during another source transition.

## Goals

- Restore source-supported model capability information across existing providers, rather than patching a few model names or effort values.
- Make model facts, account visibility, actual request support, and pricing responsibilities unambiguous.
- Preserve explicit negative evidence, missing evidence, and supported values without conflating them.
- Keep normal model selection and inference independent of remote metadata availability.
- Retain the operational and selection-stability guarantees of the current catalog.

## Non-Goals

- Reintroducing LiteLLM model execution, proxying, routing, or a runtime library dependency.
- Changing provider authentication, including ChatGPT sign-in or OAuth migration.
- Adding a new provider, changing the integration-first picker workflow, or transferring system-owned catalogs to account-owned discovery.
- Retaining a second active pricing source, adding a new billing product, or promising that absent source prices can be reconstructed.
- Replacing existing Pydantic-backed execution adapters solely to eliminate their transitive package dependencies.
- Automatically rewriting saved selections, substituting models, or downgrading user-selected reasoning effort.
- Treating another project's heuristics as authoritative model facts.
- Rewriting implemented Requirements, accepted ADRs, executed migrations, or historical model-selection evidence.

## Requirements

### REQ-1. General capability recovery

For the existing provider routes, new catalog projections must preserve supported model facts and expose the implemented capabilities justified by those facts.

**Acceptance criteria**

- The verification matrix covers reasoning and effort choices, function tools, parallel calls, strict function schemas, structured response output, configurable built-in tools, input/output modalities, supported request parameters, and token-limit semantics.
- An explicitly supported effort, including `xhigh` or `max`, is not lost solely because an unrelated or incomplete profile does not enumerate it.
- An explicit provider/account fact is not replaced by a weaker generic default for that same provider/model scope.
- A complete exact-model effort declaration is distinguished from a partial set of individual effort flags; incomplete evidence does not become an invented complete list.
- Recovery is based on general evidence interpretation and route contracts, not new model-name patches for individual regressions.

### REQ-2. Facts and execution support remain distinct

A model fact must not be confused with the ability of the selected Azents execution path to express or execute that feature.

**Acceptance criteria**

- Catalog support cannot enable a request field, content form, or tool execution path that the selected adapter does not implement.
- The absence of a model-specific entry in an execution library is not, by itself, an authoritative model denial.
- Function calling, strict function schemas, and structured response output have separately justified support rather than borrowing one another's meaning.
- Provider-hosted tools and Azents client-executed tools retain their distinct execution ownership and authorization.
- Conditional support is not advertised or sent as unconditional support; an omitted effort is not assumed to mean disabled reasoning.
- Native OpenAI model capability resolution does not depend on Pydantic-AI model profiles.

### REQ-3. Truthful evidence and identity boundaries

Metadata must preserve the distinction between unknown information, explicit denial, explicit emptiness, and positive support for the relevant provider/model identity.

**Acceptance criteria**

- Omitted listing fields do not overwrite previously applicable source facts as false.
- An explicit false or empty supported set is not replenished by a generic fallback for the same fact.
- Missing optional metadata does not hide an otherwise provider-visible integration model or alter its execution identity.
- Direct-provider facts are not transferred to Bedrock, Vertex, OAuth, or another host by an unverified name match.
- Source-declared identity relationships are distinguishable from locally guessed aliases; model execution continues to use the exact saved provider identifier.
- Context window, ordinary input window, independent input maximum, and output maximum are not silently treated as interchangeable source facts.

### REQ-4. Preserve catalog ownership and durable operation

Metadata redesign must retain the existing system/integration ownership and synchronization guarantees.

**Acceptance criteria**

- OpenAI, Anthropic, and Gemini conversation catalogs remain system-owned; currently integration-owned catalogs retain provider/account/region/project visibility authority.
- Optional price availability is not a prerequisite for publishing an otherwise eligible capability record.
- Scheduled and administrator-operated source refresh remain independent of normal catalog reads and model dispatch.
- Each refresh records identifiable source evidence and bounded diagnostic outcomes; malformed, suspiciously reduced, failed, or superseded updates do not replace the last successful authority.
- Catalog replacement is atomic, and integration configuration-generation fencing, retry eligibility, cooldown, and credential-failure behavior remain intact.
- Image-generation catalog purpose and reviewed explicit-image-model selection remain separate from conversation capabilities.

### REQ-5. Preserve saved selection and request semantics

Refreshing metadata or publishing a corrected catalog must not silently change an existing saved Agent or Workspace choice.

**Acceptance criteria**

- Saved provider/model identity, capabilities, enabled options, and user settings are not rewritten by collection or reprojection.
- Ordinary dispatch continues to use saved semantic selections, subject to the existing current integration/availability checks.
- The existing call-time tool-declaration limit when Tool Search is enabled remains a narrow transport-safety exception to saved-selection authority; this redesign neither removes it nor broadens it to unrelated saved capabilities.
- A saved selected effort is not silently clamped to another level or disabled to satisfy a newly introduced metadata rule.
- Corrections become available through the existing explicit selection/save flow and drift diagnostics.
- Native and other provider request tests verify that accepted selected settings reach the intended request fields without lossy projection.

### REQ-6. Snapshot-local context and truthful pricing

Operations must continue to obtain context fallback and estimated prices from explicitly captured local evidence without introducing remote metadata work.

**Acceptance criteria**

- Known saved token limits retain their current precedence and skip unnecessary fallback lookup.
- Existing behavior for supplementing a missing saved context maximum from a local captured source remains explicit; redesign does not claim that all local metadata reads are forbidden.
- Price data comes from the same maintained catalog basis as model facts; genai-prices is not an active alternate source or estimator.
- Estimated totals preserve correct token inclusion accounting for cache and reasoning, source-declared units, and applicable supported context, service-tier, time-window, and separately billable component rules.
- Missing, ambiguous, or unsupported required prices or billing rules produce an unavailable estimate, not a partial total, fabricated zero, silent standard-tier substitution, or execution failure.
- Previous source-specific matching, historical-date rules, or package defaults are not silently recreated when the replacement source lacks equivalent evidence.
- Provider-reported charges retain precedence over local estimates.
- Capability refresh does not install mutable package-global pricing or metadata state.
- Relevant source identities are sufficient to explain and reproduce the model facts and estimates used by one operation.
- Already recorded costs and their historical provenance are not retroactively rewritten by the source transition.

### REQ-7. Data-only source use

Azents may use maintained catalog data without adopting the producer's execution implementation or exposing its internal schema as the product contract.

**Acceptance criteria**

- No LiteLLM Python package, proxy, completion API, routing code, process-global model map, or executable updater is required in production.
- Azents removes its direct genai-prices dependency declaration, source adapter, active source selection, and price-evaluation calls. The retained Pydantic-backed adapters require genai-prices transitively and use its bundled provider rules for local usage-counter extraction. That existing parser behavior remains separate from Azents capability, context, catalog, and price authority; it does not authorize a remote updater or competing estimator. Removal does not mean zero installed packages or zero library-internal invocations.
- LiteLLM-specific data fields are confined to an explicit ingestion/interpretation boundary; persisted semantic capabilities and public selections remain Azents-owned contracts.
- Source provenance truthfully identifies LiteLLM where it is used as a data producer; generic names must not conceal the source.
- The catalog is not rebuilt by scraping OpenAI HTML, JavaScript, or prose documentation as its primary producer.
- A change in source shape or semantics is detected rather than silently interpreted as unsupported models or capabilities.

### REQ-8. Evidence-backed transition and regression accountability

The redesign must explicitly compare the former implementation, current behavior, and the intended replacement before implementation begins.

**Acceptance criteria**

- A commit-pinned historical audit identifies former source collection, provider projection, reasoning interpretation, tool/media/parameter handling, context behavior, pricing coupling, selection persistence, and verification coverage.
- Each material historical behavior is classified as preserved, restored with justification, deliberately replaced, or excluded; old code is not restored wholesale.
- Unmerged provider-parity repairs are evaluated individually, preserving justified behavior and tests without copying unsupported model-specific assumptions.
- The eventual implementation plan includes deterministic end-to-end selection-to-request coverage, source failure/publication tests, provider-specific projection cases, and saved-selection non-mutation checks.
- Transition and recovery retain readable successful catalogs and do not introduce an automatic legacy-source fallback or runtime source fetch.
- The requester accepts a replacement deployment becoming active before the first successful replacement-source collection. During that interval, stored catalogs and saved selections remain readable, while optional price estimates and missing-limit enrichment may be unavailable under their existing fallback rules.

## Fixed Constraints

- The requester selected LiteLLM's public catalog JSON as the redesign's maintained model-data basis, without the LiteLLM execution library. This choice is fixed and is not an open source-selection question.
- The requester also selected LiteLLM catalog data for prices and removal of genai-prices as Azents's direct metadata/pricing authority. LiteLLM capability and price data are one source, not competing estimators; provider-returned actual charges remain separate evidence.
- Existing native/provider execution adapters remain in use. No LiteLLM execution target is restored.
- Azents owns refresh, validation, publication, observability, and durable source/catalog lifecycle.
- Model-name heuristics and blanket effort sets do not establish new authoritative support facts. A documented source-contract default, if any, must be identified as such rather than represented as an explicit per-model declaration.
- The data-only and pricing-source decisions supersede the conflicting source and estimator requirements in the implemented [catalog-261001/REQ](catalog-261001-runtime-aligned-model-metadata.md), including its exclusive-source constraint and complete-data-removal REQ-7. That historical document remains unchanged; its operational, nullable-cost, and saved-selection protections continue where not replaced by this snapshot.

## Open Assumptions

- The source audit will establish which LiteLLM fields have sufficient semantics for lossless interpretation and which remain partial or unknown. Adoption of the data source is not a claim of complete provider coverage.
- Existing public response shapes should be retained where they can truthfully represent the confirmed behavior. Any necessary material interface change must be exposed during design rather than silently added.
- The requester selected versioned source-contract interpretation for partial effort flags and replacement without a pre-collected source prerequisite. Detailed mechanisms must preserve those decisions and the confirmed unknown, publication and saved-selection boundaries. The former two-source pricing/capability composition question is removed by the single-source decision.
- The current locked Pydantic-AI distribution transitively requires genai-prices. Removal means no direct Azents use or authority, not a claim that the entire installed dependency graph is free of that package.

## Confirmation

Confirmed by the requester on 2026-10-02 after presentation of the complete Requirements, with the explicit amendment to remove genai-prices and use LiteLLM catalog data for both capabilities and prices. The amendment replaces the earlier pricing-retention assumption. It does not approve unresolved technical decisions, a complete Design revision, implementation, or deployment.

On 2026-10-02 the requester also explicitly accepted the temporary optional-metadata availability gap of immediate replacement while retaining stored catalog readability and saved selections. This confirms the corresponding transition acceptance criterion, not a production deployment.
