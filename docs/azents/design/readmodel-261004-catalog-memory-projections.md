---
title: "Lag-Tolerant Catalog and Memory Projection Design"
created: 2026-10-04
tags: [backend, concurrency, memory, model-catalog]
document_role: primary
document_type: design
snapshot_id: readmodel-261004
---

# Lag-Tolerant Catalog and Memory Projection Design

## Design Authority

Revision: 1. [Requirements](../requirements/readmodel-261004-catalog-memory-projections.md) and [ADR](../adr/readmodel-261004-catalog-memory-projections.md) share snapshot `readmodel-261004`.

- M1 (derived): lock-free current catalog/source/maxima projections using exact scoped single-statement evidence where needed; `REQ-1`, `ADR-D1`.
- M2 (derived): independent descriptive capability capture with unchanged final consumed-input guard through acceptance commit; `REQ-2`, `ADR-D2`.
- M3 (derived): exact Memory revision/consumer/own-manifest foreground and VFS projection without descriptive authority locks; `REQ-3`, `REQ-4`, `ADR-D3`.
- M4 (derived): source/root byte projection separated from producer receipt/attempt/publication guards; `REQ-4`, `REQ-5`, `ADR-D4`.
- M5 (required): deterministic successful read/held-writer/interleave and critical admission/denial verification; `REQ-5`.

## Design Approval

Direct implementation of the explicitly requested technical phase. Requester owns the fixed lag-tolerant read/removal and unchanged privacy/model acceptance requirements. Date: 2026-10-04. Revision 1 authority set M1–M5 records their derived implementation boundary. No new user-visible recovery, persistence authority, retention mode or compatibility decision is introduced. Material departures return to Requirements/ADR before implementation.

## M1 — Current Catalog and Source Projections

`ModelMetadataSourceRepository.capture_for_context` selects only requested exact maxima with published/schema owner evidence in the same SQL statement. Optional missing facts remain `None`; preserve namespace/canonical ambiguity rules and empty-input no-I/O. Source `get_current` observes owner/count provenance and rows together, including successful empty publication, so a publication interleave cannot create the artificial cross-query count mismatch. Projection metadata and sync status are ordinary reads.

The internal typed source payload can represent zero observed current rows for a
coherent published owner. External collection still goes through
`decode_catalog_source`, whose existing bounded nonempty-record requirement
remains unchanged. This representation distinction adds no external empty-source
publication mode or validation bypass.

Catalog listing/exact-entry reads retain exact Workspace/integration/provider/catalog ownership predicates without shared owner locks. Where entry-to-owner association or newest count equality spans queries, use a joined observation; current offset page/count may lag as already defined. Keep catalog publication/producer methods unchanged except explicit separation of reader interfaces. No historical catalog revision, fallback to system visibility or saved-price recapture is added.

Completed descriptive operation repositories receive explicit read-only managers independently of their mutation manager. A mixed database composition may use `ReadSession` from its write scope without acquiring a new descriptive lock. Call sites and test doubles are updated together; no raw-session forwarding or optional locked-reader compatibility flag remains.

Image catalog description currently initializes a missing integration catalog
through `ensure_integration_catalog`; that hidden write is removed from the read
boundary. Existing actual refresh/begin-sync mutation owns initialization and
must still initialize and synchronize an absent supported-provider catalog.
Unsupported-provider/default-option behavior stays unchanged. Missing
description is not a reason to bypass the existing refresh indefinitely.

## M2 — Captured Capability Boundary

`ActiveModelCapabilitiesRepository` captures exact configured identities/current entries/source value-or-absence expectations through plain read helpers. Its completed read uses a read-only manager. Descriptive capture does not hold integration/source/catalog exclusion around model compilation or ordinary preparation.

`inputs_match_in_session` at actual profile/Worker/title/external-channel model-setting acceptance preserves the former sorted integration→source→catalog guard in the existing owner write transaction and retains exact consumed-fact comparison through mutation commit. Catalog publication source comparison likewise remains within its real publication authority. Keep existing captured candidate DTOs, raw support rules, retries, codecs and public conflict behavior.

## M3 — Memory Foreground and VFS

Add an independent read manager to the context snapshot operation and preserve it across `with_owner`. `prompt_for_turn` loads/filter descriptions using that manager; snapshot refresh/publication keeps its current mutation manager. Snapshot consumer reads root Session/Agent/durable associated User without key-share/ancestor locking, retaining exact tenant and enabled/current scope checks. Real mutation/admission callers retain any required existing guard separately.

Foreground selection queries exact unit identity and selected `unit_id/revision_id` when supplied; initial/live selection uses the observed current pointer. Join the immutable revision to current Agent eligibility and personal grant where applicable and reject any invalid dependency using a correlated denial predicate over that revision's own complete manifest. Preserve root/source identity, corpus, availability generation, membership grant continuity, source generation regression and same-generation hash mismatch checks; SQL null/UNKNOWN is denial. No current pointer manifest borrowing or mid-run reselection occurs.

Return a detached entry only after immutable overview validation and exact selected-entry identity/bytes comparison. Missing/collected revision is unavailable. Keep next model/tool/live-VFS filtering and independent-unit omission. Do not pin GC or invent a new artifact authority to preserve a stale description.

## M4 — Producer Source Read Split

Source inventory/read/work-page delivery observes exact permitted source bytes and version facts in a scoped joined nonlocking query. Do not remove `consolidation_job_session` or job-owner claim/lease/attempt deadlines: these operations persist exposure receipts and observation epoch. The delivered work's requested identity/generation/hash/availability must match the observed facts before a receipt is stored; do not receipt replacement bytes under an old work identity.

Leave final draft/recovery dependency and publication guard compositions separate. Their current owner, expected draft revision/observation epoch, freeze/disposition, immutable revision/dependency creation and repeated final commit checks remain. Ordinary source/root reads no longer inherit shared NOWAIT locking merely because a later receipt writes.

## Removal and Replacement

- Catalog/source/integration descriptive shared locks: scoped plain/joined read projections; absent/stale outcomes replace only false newest-coherence assumptions.
- Capability descriptive capture locks: plain reads; actual consumed-input acceptance retains explicit sorted guard and exact comparison.
- Context consumer/tree and foreground Agent/grant/revision/manifest read locks: independent read manager and exact correlated own-manifest projection; real publication guard remains separate.
- Producer source/root shared read locks: exact joined byte/version read; receipt/attempt/publication mutation guard remains authoritative.
- NOWAIT-contention tests specific to discarded descriptive locking: successful held-writer read/denial tests replace them. Immutable artifact corruption, exact target, privacy denial and producer ownership tests remain.
- No database schema, generated client, configuration, cache, historical snapshot document or public contract is removed.

## Test Strategy

Existing required model catalog/support, current capability, context compaction and Memory suites form the E2E primary matrix. Preserve fixture prerequisites and credential skip policy; use the existing source publication variants and independent Memory units. Latest-SHA CI verifies backend, migrations/support and required E2Es. Missing external optional credentials do not turn structural database tests into skipped verification.

Real PostgreSQL deterministic tests hold producer source/integration/catalog rows while read-only exact maxima/picker/capture reads complete; retain a final guarded acceptance conflict after committed metadata change. Memory tests hold Agent/root/grant/revision/source rows while successful exact retained reads finish, verify selected old revision uses its own denied/valid manifest, collection/missing outcomes and archive/restore/disable/grant re-enrollment continuity. Producer receipt delivery keeps exact artifact identity and stale attempt/epoch/publication rejection. Use events or authoritative state, not sleep ordering. Capture SQL absence where success-path coverage needs it.

## Feasibility and Operations

Existing catalog current rows, captured input DTOs and Memory immutable revision/dependency tables provide all required evidence. No new migration or authority is needed. Actual acceptance and producer helpers are shared with reads today; split by caller operation instead of deleting lock tokens globally. Stale description can fail current admission under existing behavior. No deployment, live mutation, merge, rollout toggle or compatibility mode is part of this phase.
