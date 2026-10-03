---
title: "Current Model Catalog and Embedded Pricing Requirements"
created: 2026-10-03
tags: [model-catalog, pricing, performance, backend]
document_role: primary
document_type: requirements
snapshot_id: catalogspeed-261003
---

# Current Model Catalog and Embedded Pricing Requirements

- Snapshot: `catalogspeed-261003`
- Document reference: `catalogspeed-261003/REQ`

## Problem

Model-call preparation obtains one selected model's price by restoring, validating, serializing, and hashing an entire catalog source. Repeated processing creates unnecessary execution latency. Catalog history and revision machinery also complicate the boundary between current selectable information and information already copied into a saved model selection.

## Primary Context

### Primary System Outcome

Agent execution uses the pricing information associated with its selected model without processing the whole catalog or performing catalog content hashing. Catalog maintenance retains only each scope's current successful data rather than historical catalog revisions.

## Supporting Scenarios or Effects

- Explicit model selection obtains coherent current model and pricing information together.
- A successful catalog refresh replaces current information without changing already saved model selections.
- A failed or concurrent refresh does not expose a partial model list, cross-scope information, or invalid selected-model metadata.
- Completed historical usage and cost records remain unchanged.

## Goals

- Remove unnecessary catalog work from model-call preparation.
- Keep only current model catalog data, including descriptive source data and conversation/image-generation catalog data.
- Carry normalized model prices with explicit model selection.
- Remove catalog hashing and hash-based identical-content checks.
- Preserve intended execution and authorization behavior.

## Non-Goals

- Changing the current model/foreground-tool completion boundary when ordinary input arrives.
- Combining or removing intentional Toolkit context, prompt, or admission checks merely because they repeat.
- Changing chosen models, reasoning settings, or model-output quality to reduce latency.
- Claiming that catalog processing caused the unclassified slow mailbox-promotion sample.
- Adding a replacement catalog revision system, content fingerprint, separate cache service, backward-compatibility runtime path, or new operational mode.
- Recalculating previously recorded costs.
- Implementing code or applying a migration during this design request.

## Requirements

### REQ-1. Current catalog data only

The model catalog retains the current successful data needed by each existing ownership and purpose scope, without historical model-catalog revisions or content-addressed snapshot history.

**Acceptance criteria**

- Refreshing a catalog or its descriptive source leaves only the current successful model data for that scope; prior catalog/source payload revisions are not retained as catalog history.
- Conversation and image-generation catalog purposes keep their existing separation and visibility rules.
- A failed refresh preserves the last successful current data rather than publishing an empty or partial replacement.
- Existing historical migrations and recorded conversation/usage artifacts are not rewritten to satisfy this requirement.

### REQ-2. Normalized pricing accompanies model selection

Relevant price information is normalized as part of the stored selectable catalog information and is copied together with model information when a model is explicitly selected or saved as a label candidate.

**Acceptance criteria**

- Every newly selected physical candidate, including Primary, fallback, and lightweight candidates, carries the price information required for its supported local estimate, or an explicit unavailable outcome.
- Price identity remains exact to the selected hosting provider and model; unrelated provider, alias, family, or account pricing is not borrowed.
- Selection obtains model and pricing information from a coherent current catalog view.
- Refreshing the catalog does not silently rewrite already saved model selection information. The treatment of pre-existing selections without embedded prices must be decided before implementation.

### REQ-3. Remove catalog content hashing

Catalog content hashing and hash-based identical-content checks are removed, not merely cached, reduced in frequency, or moved to a different executor.

**Acceptance criteria**

- Catalog collection/publication, selection, and model-call preparation do not compute hashes over catalog source bodies, normalized payloads, or catalog projection contents.
- Catalog persistence does not deduplicate or identify model-data revisions through content hashes.
- Runtime cost provenance does not require a recomputed catalog content hash or retained catalog revision history.
- Authentication, unrelated file integrity mechanisms, and protocol/schema interpretation are not weakened by removing catalog hashing.

### REQ-4. Selected-price execution without whole-catalog processing

Physical model calls use the pricing associated with their selected candidate rather than fetching and restoring the current whole-catalog pricing source.

**Acceptance criteria**

- Foreground, fallback, lightweight, title, compaction, and subagent model-call paths do not load, validate, serialize, or hash the entire catalog to obtain a model price.
- Usage received after a catalog refresh still uses the price information chosen for that physical call; it is not rematched to a newer catalog during completion.
- Cold process start and repeated calls do not require a catalog-wide price restoration path at dispatch.
- Missing or unsupported prices retain the existing unavailable-cost behavior without preventing otherwise valid model execution.

### REQ-5. Preserve cost and model behavior

The optimization preserves existing execution authority, saved-model capability semantics, and supported cost-calculation behavior.

**Acceptance criteria**

- Provider-reported finite nonnegative charges retain precedence over local estimates, including reported zero.
- Existing supported price units, service tiers, cache/reasoning/media partition rules, tool dimensions, and time/context conditions retain their behavior.
- Missing or unsupported required price dimensions yield an unavailable total, not zero or a partial token-only estimate.
- Existing recorded costs and completed usage artifacts remain unchanged.
- Model selection, enabled integrations, context-window precedence, execution-option validation, and admission-time authority checks are preserved.

### REQ-6. Verify the removed execution cost and safe replacement

Verification demonstrates the absence of the unwanted work and safe current-data replacement rather than assuming an improvement from code shape alone.

**Acceptance criteria**

- Tests observe zero whole-catalog pricing-source restorations and zero catalog content-hash computations during the supported physical model-call paths.
- Focused before/after measurements distinguish model preparation from provider stream generation and use equivalent selected models and catalog data.
- Refresh, failed refresh, concurrent publication, selection during refresh, and provider-purpose isolation receive deterministic coverage.
- Migration verification covers current data, existing selections, and historical usage preservation without retaining the removed runtime path as a fallback.

## Fixed Constraints

- This is a design-only request. Implementation, commits/PR shipping, migrations, or live deployment require a later explicit request.
- Intended current model/tool waiting, Toolkit preparation/check boundaries, and model-stream waiting are retained.
- The existing source/integration authorization and purpose separation remain authoritative.
- No new catalog history, revision, hash/fingerprint, or separate cache layer may replace the removed machinery.
- Existing unsupported-price and optional-context behavior must not be silently redefined by a performance refactor.

## Open Assumptions

- Persisted current model and selected-model data is expected to follow the repository's known contracts. Malformed data requires explicit migration failure/reporting, not silent model reselection or capability repair.
- Optional-context metadata is available only through the existing exact-source matching rules; its absence retains existing context defaults rather than creating new model identity or authority.
- Ordinary operational diagnostics may describe current synchronization outcomes, but cannot retain removed catalog payload history or act as a replacement revision system.

## Confirmation

The requester explicitly supplied the latest-data-only, embedded-pricing, and no-catalog-hashing outcomes in discussion on 2026-10-03. The requester then directed the Agent to record these requirements and produce the final design without pausing for a separate Requirements approval. This document records those outcomes as the confirmed scope for the bounded design task. Remaining material technical choices are delegated within this scope; new product behavior is not delegated. Implementation is not authorized.
