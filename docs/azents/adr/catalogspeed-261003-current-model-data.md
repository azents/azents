---
title: "Current Model Catalog and Embedded Pricing Decisions"
created: 2026-10-03
tags: [model-catalog, pricing, performance, architecture]
document_role: primary
document_type: adr
snapshot_id: catalogspeed-261003
---

# Current Model Catalog and Embedded Pricing Decisions

- Snapshot: `catalogspeed-261003`
- Document reference: `catalogspeed-261003/ADR`
- Requirements: [catalogspeed-261003/REQ](../requirements/catalogspeed-261003-current-model-data.md)
- Mode: Autonomous technical design within the requester's explicitly delegated, bounded scope.
- Technical decision owner: dedicated catalog design review agent.
- Implementation authority: none; this snapshot is design-only.

## Context

The requester confirmed latest-data-only catalog behavior, embedded normalized selection prices, and removal of catalog content hashing. Existing model/tool waiting and Toolkit preparation/check boundaries are intentional and remain unchanged.

The current source path retains content-addressed source snapshots and restores the whole source for each physical call's pricing. Published conversation/image catalog replacements already remove the previous current projection, but still use snapshot/candidate/pointer machinery and hashes. A separate integration configuration counter is current credential/configuration authority, not catalog model-data history; stale-credential protection must survive.

## Fixed Outcomes

- Keep only current catalog source/model data per existing owner and purpose scope.
- Store normalized prices with model entries and explicitly selected candidates.
- Remove catalog source/payload/projection hashing and identical-content deduplication.
- Eliminate whole-source execution reads for prices, without a cache or revision replacement subsystem.
- Preserve exact identity, scope, model capability precedence, optional-price behavior, and historical recorded costs.
- Do not weaken existing credential/configuration or execution admission checks.

## Material Decision Map

- D1: latest-data persistence and publication ownership.
- D2: embedded price definition and call-local cost provenance.
- D3: existing selection conversion and optional context fallback.
- D4: migration/cutover and rollback boundary.

Accepted decisions are recorded below. No implementation authority is implied by technical Design approval.

## D1. Latest-only data with atomic publication

- Reference: `catalogspeed-261003/ADR-D1`
- Requirements: `catalogspeed-261003/REQ-1`, `/REQ-3`, `/REQ-5`, `/REQ-6`
- Accepted: 2026-10-03 by the delegated technical decision owner.

### Decision

Keep stable source and catalog owner identities. Store only current normalized per-model source rows and current conversation/image catalog rows. Replace current rows with atomic upsert plus deletion of removed keys; remove source/catalog snapshot history, pointers, persisted candidate bodies, and content hashes.

The source collector prepares validated data outside the publication transaction. Source replacement and affected system-catalog replacement commit together. Integration publication likewise keeps network/provider work outside the database transaction.

Retain one current synchronization status and one opaque active request identity for work ownership, not a catalog data revision. No token is exposed as a dataset identity or copied into selections/cost records. Final source-dependent publication locks the source owner and compares the exact relevant current typed values and presence/absence with preparation inputs. A system projection compares its complete relevant provider rowset; integration projections compare every adopted exact key that could affect the prepared entries. Changed inputs cause re-preparation outside the transaction. This equality check is concurrency validation, not identical-content deduplication or skipped publication.

Preserve the existing integration credential/configuration counter as current authorization, not catalog history. Invalidate current catalog usability in the same transaction as user credential/config/enabled changes; mark current entries usable only after an authorized publication. Selection and image execution recheck usable current entries and current integration authority.

Read catalog status and entry/pricing coherently using a shared owner-row lock or an equivalent single SQL projection. Use the common lock order: integration authority where applicable, source owners, catalog owners sorted by stable identity, then entry rows. System publication must not acquire integration locks after source/catalog locks.

### Alternatives and consequences

A single current source blob would remove history but retain whole-source restoration or JSON scans for exact optional metadata reads. Current indexed per-model source rows remove that execution cost without a separate cache.

An active request token cannot be a published-data freshness fence: absent-token ABA and capture during a refresh could authorize stale preparation. Exact relevant value/presence comparison is required instead; do not introduce a replacement source version/fingerprint.

Removing the integration authority check would permit old-credential results to authorize the new configuration. Keeping the existing current authority counter adds no catalog history. Atomic row replacement, stale-work rejection, credential invalidation, and consistent read tests are required before implementation can be considered verified.

## D2. Embedded normalized prices and cheap physical-call capture

- Reference: `catalogspeed-261003/ADR-D2`
- Requirements: `catalogspeed-261003/REQ-2`, `/REQ-3`, `/REQ-4`, `/REQ-5`
- Accepted: 2026-10-03 by the delegated technical decision owner.

### Decision

Reuse the existing typed `CatalogPriceRules` and estimator. Normalize raw price evidence at collection/publication, retain unsupported/invalid issues, and persist a compact definition: typed rules or an explicit existing unavailable reason, descriptive source key, exact source model key, and aware collection time. Provider/model identity remains owned by the current entry and selected candidate.

Explicit server-side model selection copies the matched definition into the common `AgentModelSelection`; client mutation input remains integration/model identity and cannot supply authoritative rates. Candidate/inference propagation uses the existing full selected-model contract.

Physical dispatch creates only a call-local pricing envelope from the actual candidate definition and a new aware request timestamp. Price capture performs no DB read, whole-source restore, raw-price interpretation, hashing, or cache access. Existing integration/admission reads and validation of compact saved typed data remain necessary.

Preserve every Decimal exactly in normalized JSON persistence, along with nullable amounts, ordered/duplicate tariffs, issue metrics and invalid flags, tiers, context thresholds, search dimensions, off-peak windows/weekdays/timezones, and overrides. Missing definitions remain unavailable; they do not become zero, partial totals, or a current-source fallback. Provider-reported finite nonnegative charges, including zero, retain precedence.

New estimate provenance records method, exact provider/model, applied tier, descriptive source/model key and collection time, and the existing code estimator version. It contains no source snapshot ID, content hash, or catalog foreign key. It is not a new price-history subsystem. Existing recorded event JSON/costs remain unchanged; historical opaque provenance is never execution authority. Do not add title billing.

### Alternatives and consequences

A process cache of whole-source captures would preserve the unnecessary authority/restore boundary. Thread offload would preserve repeated source interpretation. Neither meets the requested removal. Persisting compact normalized rules with selected models eliminates the work instead.

Deleting only hash fields would make the existing `normalize_model_pricing` authority check classify all prices as unavailable. Publication normalization and call-local capture must replace that unit together, preserving exact identity and unavailable semantics. Calculator parity and lossless round-trip tests are mandatory.

## D3. One-time price-only initialization and exact optional context reads

- Reference: `catalogspeed-261003/ADR-D3`
- Requirements: `catalogspeed-261003/REQ-2`, `/REQ-4`, `/REQ-5`, `/REQ-6`
- Accepted: 2026-10-03 by the delegated technical decision owner.

### Decision

Initialize only missing embedded-price fields once during the migration, using exact current catalog entries in the saved candidate's existing provider/integration/purpose scope. Cover canonical Agent options, existing primary/lightweight mirrors, Workspace defaults, current Session inference selections, and nonterminal durable operation candidates needed for future dispatch. Do not alter model identity, capability contracts, settings, labels, or existing valid prices.

Initialization uses migration-time current collected prices; it does not recover the historical rate at the original selection time. Missing/deleted/unmatched scope or price evidence receives an explicit unavailable outcome, without network fetch, alias inference, source-price fallback, lazy runtime fill, or new execution permission. Retain partially supported normalized rules/issues for the existing estimator to evaluate against actual usage.

Do not overwrite an already-started physical attempt's frozen price or any terminal operation, event, or recorded cost. After transition, ordinary reads and non-selection edits preserve the embedded definition; explicit model selection/save captures current catalog pricing.

Replace optional whole-source maximum lookups with grouped, indexed exact current source-model reads only where saved maximums are missing. Preserve saved maximum precedence, known default floor, maximum-as-default, explicit caps, and the existing 128,000-token fallback. A paired operation uses one coherent view; it does not merge unrelated Toolkit/check/wait boundaries or rewrite saved capability fields.

### Alternatives and consequences

Leaving all old selections unpriced until manual reselection is smaller but unnecessarily removes usable estimates for exact matchable candidates. A one-time price-only initialization completes the already-required embedded-price transition without selecting a new model or introducing a workflow.

Per-turn fill or reading the current source for missing prices would recreate the removed authority and execution work. General automatic refresh of saved model information would violate existing selection semantics. Neither is authorized. Migration coverage must include every executable saved-selection mirror and resumable candidate while excluding completed history.

## D4. Coordinated destructive cutover without replacement history

- Reference: `catalogspeed-261003/ADR-D4`
- Requirements: `catalogspeed-261003/REQ-1`, `/REQ-3`, `/REQ-5`, `/REQ-6`
- Accepted: 2026-10-03 by the delegated technical decision owner.

### Decision

Use one new linear migration generated through the established migration workflow. Transfer only the current authoritative source/projection data to latest-only rows and initialize only missing selected-price fields under D3. Preserve current projected capabilities even where source matching is unavailable; do not revive a retired source family as pricing authority.

Replace obsolete snapshot/current-pointer foreign keys, indexes, and database guard functions, including the guards installed by `c8bc0a5dcab0`, before dropping snapshot/source history, non-current candidates, raw/canonical hashes, fingerprints, and append-only source/catalog synchronization attempts. Replacement enforcement retains owner/purpose, allowed source kind/contract, and current credential authority. One current diagnostic state retains separate last-success information and latest-attempt failure/backoff/cooldown/automatic-block facts, without produced-snapshot references. Generic Job Runtime operational history remains outside catalog data history and must not contain a retained catalog payload archive.

Initialize catalog usability from actual pre-cutover authorization, not blanket true. Update current APIs/DTOs/CLI commands to expose current counts, last success and latest synchronization status; remove snapshot/generation/hash/fingerprint and candidate/cutover interfaces. Regenerate public/admin Python/TypeScript clients and update equivalent UI status labels without changing layout. Historical event/cost JSON remains readable; opaque historical selected-model diagnostics never resolve deleted pointers.

Stop/drain old catalog readers/writers and obsolete queued/claimed publication work before destructive schema change. Run only matching new code after cutover. Add no dual writer, compatibility runtime source path, separate cache service, or new operational mode.

Verify a normal database backup before destructive migration. If invariants fail, abort atomically; do not stamp a partial migration as complete. Removed history cannot be reconstructed by a nominal downgrade. Emergency rollback requires stopped writers, a matching full schema/data backup, and the previous release, or a tested forward fix. Backup restoration may lose post-cutover writes and must be disclosed as an operational risk.

### Alternatives and consequences

Keeping old snapshot tables or an old reader/writer fallback would retain the prohibited revision/authority graph. A new revision or hash-based cache would reintroduce the same mechanism. Neither is authorized.

A coordinated cutover is necessary because database guards cannot revoke already captured old in-memory source objects. Quiescence, guard replacement, current-data validation, stale authorization initialization, queue cancellation, and migration/rollback tests are release prerequisites. This decision authorizes a design, not execution of any live migration.

## D1 Scope Clarification — Preserve Purpose-Specific Selection Predicates

- Reference: `catalogspeed-261003/ADR-D1`.
- Clarified: 2026-10-03 during complete Design authority review.
- Authority: `catalogspeed-261003/REQ-5` and unchanged current conversation/image selection behavior.

The accepted current-usability substitution applies to the existing image-generation generation-current save/runtime checks. It does not add a stronger conversation selection, saved-model execution, or client-side save predicate. Conversation selection retains existing current-entry, exact identifier, selectable visibility and integration/Workspace predicates, including its existing stale-readable behavior. Conversation status is diagnostic, not an additional authorization gate.

Stale-credential publication remains fenced for both conversation and image purposes. This clarification narrows ambiguous wording to existing authority rather than authorizing new product behavior. Historical stored selections lacking pricing decode read-only as absent; new selections provide a typed definition, and an actual missing-price call remains unavailable without any source lookup or data rewrite.
