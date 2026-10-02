---
title: "Evidence-Backed Model Support Decisions"
created: 2026-10-02
tags: [model-catalog, backend, engine, metadata, architecture]
document_role: primary
document_type: adr
snapshot_id: capability-261002
---

# Evidence-Backed Model Support Decisions

- Snapshot: `capability-261002`
- Document reference: `capability-261002/ADR`
- Requirements: [capability-261002/REQ](../requirements/capability-261002-evidence-backed-model-support.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

The source-authority cutover in `catalog-261001` replaced an already library-independent LiteLLM JSON collector with genai-prices metadata and runtime-profile-derived capabilities. The inspected current implementation can lose explicit provider effort levels when intersecting them with incomplete profile-derived sets. Other source/profile conflations affect strict function schemas, sparse listings, media and pricing-derived tool support.

The requester first selected LiteLLM catalog JSON without the execution library, then explicitly selected that same JSON for pricing and removal of genai-prices as the active Azents source and estimator. Requirements were amended before this decision record was created. This ADR does not rewrite the implemented predecessor snapshot.

## Fixed or Derived Outcomes

- One maintained external model dataset supplies catalog facts and estimated-price data: LiteLLM public catalog JSON. Provider/account listings and provider-reported charges retain their separate roles; they are not competing generic catalogs.
- Azents owns collection, validation, normalization, persisted snapshots, projection, cost evaluation and publication. No LiteLLM runtime library, routing layer or proxy is restored.
- genai-prices is removed from direct Azents dependencies and metadata/price-evaluation calls. Existing Pydantic-backed model adapters remain; their transitive genai-prices package and local bundled usage-counter extraction remain incidental runtime behavior, not Azents capability/context/pricing authority.
- Actual runtime adapters and the implemented tool registry constrain what can be sent/executed. Missing model knowledge in a library is not a model denial. Native OpenAI does not derive model capabilities from Pydantic-AI profiles.
- System-owned conversation catalogs remain system-owned. Integration visibility follows the existing provider/account/region/project boundary; optional source or price misses do not hide valid provider-visible entries.
- Saved Agent/Workspace choices are not reinterpreted or rewritten on refresh. Existing Tool Search call-time declaration limits remain the documented exception.
- Normal catalog reads and dispatch perform no remote metadata collection. Operation-local capture of stored context/price evidence remains allowed.
- Valid native charges win over estimates. Missing or unsupported required billing information produces an unavailable total rather than a fabricated or partial price.
- Source-specific provenance is truthful. Generic table/type names do not conceal the actual data producer.
- Historical documents, executed migrations, previously recorded prices and their provenance remain historical evidence.

## Material Decision Map

- [x] `capability-261002/ADR-D1` — one data-only catalog for capabilities and pricing; remove direct genai-prices authority. Accepted by requester on 2026-10-02.
- [x] `capability-261002/ADR-D2` — versioned source-contract interpretation for partial effort flags (Option B). Accepted by requester on 2026-10-02.
- [x] `capability-261002/ADR-D3` — one-release replacement, allowing unavailable optional metadata until refresh, with mixed-version writer fencing (Option B). Accepted by requester on 2026-10-02.

Evidence-envelope class names, equivalent internal record layout, fixture organization and helper boundaries are agent-owned. They do not authorize a new public unknown-state UI, permission, source, fallback, or migration mode. If implementing conditions requires a material interface or user-visible policy beyond Requirements, that consequence returns to the requester rather than being hidden as a local detail.

## Decisions

### capability-261002/ADR-D1. Use one data-only catalog for model facts and estimated prices

**Accepted:** 2026-10-02, requester.

**Authority:** `capability-261002/REQ-1`, `REQ-4`, `REQ-6`, `REQ-7`, `REQ-8`, and the explicit instruction to remove genai-prices after the single-LiteLLM-source proposal.

Use LiteLLM's public catalog JSON as the maintained data basis for system model inventory, descriptive model capabilities, limits, lifecycle information where supplied, and price facts. Integration models remain provider-visible candidates with source data as scope-correct enrichment. Azents converts the consumed source facts and prices into its own versioned, descriptive contract and computes estimates from captured local evidence.

Remove direct genai-prices fetching, model matching, snapshot reconstruction and pricing evaluation from Azents's metadata path. Do not add models.dev as a separate pricing producer. Do not import LiteLLM execution helpers or restore its old runtime model map, source-specific database tables, execution-prefixed identity, or raw request configuration.

The retained provider adapters still own protocol encoding and usage-counter normalization. The locked Pydantic-AI package depends on genai-prices and uses its local bundled provider rules in `RequestUsage.extract`. Preserving those stock adapters therefore permits that existing counter parser, but not genai-based Azents pricing, remote background updates, or implicit adoption of upstream computed costs. Zero installed dependency or zero invocation would require a broader adapter change and is not the meaning of this decision.

**Consequences**

- Capability and price provenance can refer to one captured source revision instead of joining independent generic catalogs.
- Azents must maintain a bounded source decoder and truthful estimator; removing a library does not remove that responsibility.
- Upstream dataset completeness is not guaranteed. An unavailable price is preferable to a wrongly complete total.
- Context thresholds, cache/reasoning inclusion, unit conversions and supported time-window rules require deterministic tests against the adopted data semantics.
- Arbitrary dated price schedules absent from the JSON are not reconstructed from deprecated genai rules. Previously captured estimates remain recorded; retrospective rate discovery is not introduced.
- Remote JSON data is descriptive. Endpoint overrides, executable expressions, instruction templates and family-regex fallback rules do not become trusted request configuration.

**Rejected alternatives**

- Keep genai-prices for prices alongside LiteLLM capabilities: the requester selected a single source and direct genai removal.
- Use models.dev only for prices: this retains a second generic dataset and cross-source reconciliation.
- Restore the LiteLLM runtime library: contradicts the data-only direction and existing execution adapters.
- Restore the old estimator unchanged: it lacks newer source fields and contains fallback behavior weaker than current missing-specialized-rate protections.
- Remove or fork stock Pydantic adapters merely to eliminate a transitive dependency: broader than the requested source/estimator redesign.

**Required evidence**

- Repository scans identify no direct Azents genai imports, price calculations, source fetches, updater invocations or direct dependency declaration after implementation.
- Dependency reporting distinguishes the retained transitive counter parser from removed authority; it must not claim a zero-genai dependency graph.
- Mock provider streams exercise usage extraction while genai pricing/updater entry points are poisoned; Azents uses only the selected captured estimator or valid native charge.
- New source/cost fixtures cover exact provider scope, explicit zero versus missing, inclusive/exclusive cache/reasoning, supported context/tier/time rules, unknown billable components and immutable captured provenance.
- No source refresh mutates an existing saved model choice or historical cost.

### capability-261002/ADR-D2. Interpret partial effort flags through a versioned source contract

**Accepted:** 2026-10-02, requester selected Option B.

**Authority:** `capability-261002/REQ-1`, `REQ-2`, `REQ-3`, `REQ-7`, and the requester's explicit selection of versioned source-contract interpretation.

Preserve explicit source effort arrays first. For flag-bearing exact records, apply documented producer flag polarity in an Azents-owned, versioned decoder, and identify the resulting values as contract-derived rather than explicit per-model facts. The decoder does not import or execute LiteLLM helper code.

The captured producer contract uses low/minimal opt-out and xhigh/max opt-in semantics, with rules for none and baseline medium/high. The primary Design must specify the applicable provider/endpoint scope and false/null/omission handling from the verified source contract, with deterministic fixtures. It must not generalize a rule beyond that scope.

**Boundaries**

- Exact account/provider effort arrays retain their scope and are not narrowed by an unrelated generic profile.
- An explicit source `reasoning_effort_levels` list takes precedence over per-level flags under its source contract; explicit empty is meaningful.
- A record with no effort evidence is not expanded from a model name or the SDK's global enum.
- Unknown effort support does not make an integration-visible model unavailable.
- No automatic clamping of a user's requested effort is introduced.

- Records without relevant flags or a complete list retain unknown effort support. Generic reasoning support alone does not authorize a complete list.
- Source helper namespace inheritance, model-name special cases, no-evidence defaults and nearest-effort remapping are excluded.

**Consequences**

- Source-contract defaults can preserve usable effort choices without adding a per-model exception table.
- Interpretation revisions are part of provenance and projection reproducibility. An upstream helper change is evidence for review, not an automatic runtime behavior change.
- Explicit source facts and contract-derived values remain distinguishable through normalization.
- Actual adapter support still bounds what can be sent, without treating an unrelated profile's missing model knowledge as a denial.

**Rejected alternatives**

- Option A, explicit per-model values only: it leaves producer-defined flag defaults uninterpreted and can unnecessarily omit ordinary selectable efforts.
- Restore the former decoder unchanged: its none/minimal opt-in rules, unconditional generic reasoning baseline and ignored explicit arrays do not match the selected producer contract.
- Execute the current LiteLLM helper wholesale: it would import excluded identity inheritance, model-specific policies and request remapping rather than retain an Azents-owned data interpretation boundary.
- Fill missing effort data from the SDK enum: transport representability is not model support evidence.

**Required evidence**

- Fixtures distinguish exact arrays, explicit empty, positive/negative flags, null, omission, no-effort-evidence records and applicable provider/endpoint scope.
- Explicit account/provider lists, including xhigh/max, survive projection and supported native request serialization.
- Tests record which values are explicit versus contract-derived and prove that interpretation-revision changes affect new projections without rewriting saved selections.
- No decoder path consults model-name heuristics, cross-host aliases, a live metadata endpoint or a LiteLLM executable helper.

### capability-261002/ADR-D3. Replace the source and evaluator in one release without a pre-collected source prerequisite

**Accepted:** 2026-10-02, requester selected Option B.

**Authority:** `capability-261002/REQ-4`, `REQ-5`, `REQ-6`, `REQ-8`, and explicit acceptance of temporary unavailable optional metadata before the first replacement collection.

Ship the new source reader and Azents evaluator while removing direct genai source and evaluation paths in the same release. Do not require a staged production shadow source or successful remote fetch as a deployment/migration prerequisite. Existing stored catalog projections, saved selections and recorded costs remain readable and are not rewritten during the switch.

New operations capture only the new source family. Before its first successful collection, estimates return source-unavailable and missing-limit enrichment follows the existing no-source fallback policy. This gap must not fail model execution, trigger a request-time metadata fetch, or silently consult genai/package-bundled data. Scheduled or administrator refresh establishes the replacement source; successful catalog projections then publish atomically under the existing ownership and generation rules.

The release must fence incompatible older collectors and publishers so they cannot restore the removed source as current authority or overwrite a new catalog after cutover. Historical source/projection records may remain inert for provenance and readability; they are not a second active reader or fallback. Already running requests retain their captured evidence under the existing request-lifecycle contract.

**Consequences**

- Deployment readiness does not depend on upstream catalog availability or customer provider credentials.
- There can be a visible interval of unavailable estimates and absent optional limit enrichment, which the requester accepted.
- Existing successful catalog snapshots remain usable until normal replacement publication succeeds.
- No runtime switch or automatic legacy-source fallback is introduced.
- The primary Design must specify mixed-version write fencing and explicit rollback compatibility. A binary-only rollback is not assumed safe after the new write contract is active.

**Rejected alternatives**

- Option A, prepared staged promotion: requires extra production preparation and readiness gates; the requester chose one-release replacement instead.
- Empty or delete all stored catalogs at deployment: violates stored-read continuity and saved-selection protections.
- Keep genai as an automatic fallback until the first successful fetch: violates the selected single-source destination and direct-use removal.
- Fetch the catalog from a database migration or normal inference request: introduces prohibited network prerequisites and request-time authority changes.

**Required evidence**

- Seeded migration/deployment tests start with populated old catalogs and no new source; stored reads and saved dispatch remain usable while prices report unavailable.
- Blocked/unavailable upstream collection does not block schema application or application startup.
- Older source publication and catalog-pointer writes are rejected after the new write contract activates, including in-flight/superseded attempts.
- First successful new collection and per-catalog publication transition out of the optional-metadata gap without mutating saved selections.
- Recovery and rollback tests cover retained historical rows, expected fence failures and the selected coordinated rollback procedure without automatic fallback.

## Historical Supersession Boundary

D1 replaces the active source/estimator selections in `catalog-261001/ADR-D3` and the source exclusion in its fixed outcomes. Confirmed Requirements replace the inappropriate native-profile capability ceiling from its D1 and the complete LiteLLM-data removal outcome. Existing durable refresh, last-good publication, ownership, saved-selection and provider-charge protections remain where not superseded. The old staged cutover ADR remains historical evidence; D3 above will define this new transition rather than silently rewriting or replaying its migrations.

## Design Readiness

Requirements and D1-D3 are confirmed. No material source or transition choice remains open in this map. The primary Design, authority/feasibility validation and revision-bound requester approval must still be completed before implementation.
