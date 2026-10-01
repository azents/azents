---
title: "Runtime-Aligned Model Metadata Requirements"
created: 2026-10-01
updated: 2026-10-01
implemented: 2026-10-01
tags: [model-catalog, backend, engine, scheduler, migration]
document_role: primary
document_type: requirements
snapshot_id: catalog-261001
---

# Runtime-Aligned Model Metadata Requirements

- Snapshot: `catalog-261001`
- Document reference: `catalog-261001/REQ`

## Problem

Azents no longer executes models through LiteLLM, but the active model catalog, context fallback, and estimated-cost provenance still depend on a LiteLLM-owned metadata source and LiteLLM-named persistence and operational surfaces. This leaves model capability projection coupled to a retired execution target and creates a risk that selectable capabilities differ from the compatibility rules used by the deployed runtime.

## Primary Context

### Primary System Outcome

Azents independently refreshes and stores model metadata, then publishes model catalog snapshots whose execution capabilities agree with the compatibility rules used by the deployed runtime, without retaining LiteLLM as an active package, metadata, naming, or operational authority.

## Supporting Scenarios or Effects

- System administrators continue to observe and operate system catalog refresh independently of normal catalog reads.
- Integration catalog synchronization continues to combine account-visible provider models with locally stored metadata without introducing request-time external metadata calls.
- Model execution continues to capture one local metadata snapshot for context fallback and estimated-cost provenance.
- Existing saved Agent model-selection snapshots remain stable when later catalog metadata or runtime compatibility changes.

## Goals

- Align catalog capability claims with the same runtime compatibility authority used for model execution.
- Preserve Azents-owned background synchronization, durable source snapshots, projection snapshots, failure recovery, and stored read paths.
- Preserve current system- and integration-catalog ownership and synchronization behavior.
- Remove LiteLLM vocabulary and source semantics from active code, persistence, configuration, diagnostics, telemetry, fixtures, and served catalog metadata.

## Non-Goals

- Changing the integration-first model picker workflow or public catalog API behavior.
- Adding models.dev or another parallel model catalog authority.
- Changing provider credential, entitlement, or account-visible model discovery behavior.
- Fetching metadata or resolving provider availability during normal catalog reads or model dispatch.
- Rewriting factual historical Requirements, ADRs, Designs, change histories, or already executed migration records.
- Making missing optional metadata or estimated pricing fail model visibility or execution.

## Requirements

### REQ-1. Runtime-aligned capability authority

Every published model catalog entry must derive execution capability claims from the compatibility authority used by the deployed runtime for the same provider and model identity.

**Acceptance criteria**

- Tool calling, structured output, reasoning, native tools, modalities, and other execution-facing capability claims cannot be enabled solely by a metadata source that the runtime does not use for compatibility.
- Provider-specific and Azents-owned runtime compatibility overrides are reflected in catalog projection through the same authority rather than a duplicated rule set.
- When metadata and runtime compatibility evidence disagree, the published entry does not advertise a capability that the runtime compatibility authority denies.

### REQ-2. Independently refreshed durable metadata authority

Azents must own the model metadata refresh lifecycle independently of application process memory and normal request handling.

**Acceptance criteria**

- A scheduled or administrator-operated refresh can collect updated metadata without an application release.
- Each collection attempt records status, timing, counts, safe failure information, and diagnostics.
- A validated successful source snapshot is durable and identifiable by content and provenance.
- Failed, malformed, superseded, or materially suspicious collection does not replace the latest successful authority.
- Normal catalog reads and model dispatch do not fetch the remote metadata source.

### REQ-3. Durable catalog projection and publication

System and integration catalog projections must remain durable, replaceable snapshots derived from stored source authority and the current runtime compatibility authority.

**Acceptance criteria**

- System catalog refresh publishes a complete stored projection for each supported system provider.
- Integration catalog refresh continues to use provider-visible models as its availability authority and stored local metadata only as projection input or optional enrichment according to provider policy.
- Publication does not expose a partial replacement snapshot.
- A failed refresh leaves the last successful catalog snapshot readable when one exists.
- Catalog projections record enough provenance to determine which source content and runtime compatibility revision produced them.

### REQ-4. Existing synchronization and read behavior remains stable

The source transition must preserve current catalog ownership, synchronization triggers, concurrency controls, and stored read behavior.

**Acceptance criteria**

- System catalog refresh remains scheduler- and administrator-owned rather than public-user-triggered.
- Integration creation, relevant configuration changes, explicit sync, and stale refresh retain their current eligibility, throttling, retry, fencing, and failure classification behavior.
- Public model picker reads remain stored-only and preserve their existing ready, stale, running, failed, and empty states.
- Existing public catalog response shapes and model-selection submit behavior remain compatible unless a separately confirmed requirement changes them.

### REQ-5. Operation-local context and pricing provenance

Context fallback and estimated model cost must continue to use an explicitly captured local metadata authority with truthful nullable outcomes.

**Acceptance criteria**

- Operations that need metadata capture one stored source snapshot and retain its identity in applicable provenance.
- Known saved context limits retain precedence and avoid unnecessary source reads.
- Missing model metadata, unsupported billing rules, or unavailable prices produce an unknown result rather than a fabricated value or execution failure.
- Provider-reported charges remain distinguishable from locally estimated charges.

### REQ-6. Saved selection stability

Refreshing source metadata or runtime compatibility must not silently rewrite existing Agent or Workspace model-selection snapshots.

**Acceptance criteria**

- Existing saved selections continue to execute from their stored semantic provider, model identity, capabilities, and settings subject to current runtime availability checks.
- Updated projections affect new selections and drift diagnostics rather than mutating prior selections in place.

### REQ-7. Complete active LiteLLM removal

The completed transition must leave no active LiteLLM package, metadata source, schema vocabulary, compatibility alias, or operational identity.

**Acceptance criteria**

- Active runtime and catalog code has no LiteLLM imports, loaders, source services, repositories, data types, environment variables, source keys, field names, error codes, log vocabulary, or scheduler descriptions.
- Current database schema and active persisted source/catalog records do not use LiteLLM-named tables, constraints, fields, source identifiers, or metadata keys.
- Newly generated API payloads, diagnostics, telemetry, and deterministic fixtures contain no LiteLLM-specific source vocabulary.
- No legacy runtime fallback or compatibility alias preserves LiteLLM source behavior after cutover.
- Historical documents and executed migration history may retain factual references to the former implementation.

### REQ-8. Safe source transition

The replacement metadata authority must be introduced without making normal catalog reads depend on migration timing or remote-source availability.

**Acceptance criteria**

- Deployment can retain the last successful catalog projection while replacement source collection and projection are established.
- The old active source authority is removed only through an explicit migration and cutover boundary.
- Rollback and recovery behavior is documented, and neither path reintroduces request-time metadata fetches.
- Completion includes repository and database absence evidence for active LiteLLM identities.

## Fixed Constraints

- The replacement must use the Pydantic AI runtime ecosystem's maintained model metadata and the compatibility rules used by Azents model construction; models.dev is excluded.
- Azents, not an imported library's process-global updater, owns background scheduling, synchronization attempts, durable snapshots, publication, and recovery.
- Provider-visible listing remains the availability authority for integration-scoped providers.
- The current stored-read architecture, Agent selection snapshot semantics, and nullable pricing behavior remain authoritative unless explicitly changed by this snapshot.
- Active LiteLLM compatibility aliases and fallback modes are not permitted.

## Open Assumptions

- The selected Pydantic ecosystem metadata source remains available in a machine-readable form that Azents can validate and persist independently.
- Runtime compatibility can be resolved without making provider network calls or requiring customer credentials.
- Existing public API response shapes can be preserved while internal source provenance changes.

## Confirmation

Confirmed by the requester on 2026-10-01 before ADR and design decisions began.
