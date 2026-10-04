---
title: "Catalog and Memory Projection Decisions"
created: 2026-10-04
tags: [backend, concurrency, memory, model-catalog]
document_role: primary
document_type: adr
snapshot_id: readmodel-261004
---

# Catalog and Memory Projection Decisions

Authority: [readmodel-261004/REQ](../requirements/readmodel-261004-catalog-memory-projections.md). The requester-fixed read contract and existing model/Memory admission contracts determine these mechanisms; they do not add new product behavior.

## D1 — Single-statement current catalog evidence, not retained catalog history

Use scoped ordinary projections that obtain owner provenance and requested current rows/maxima from the same SQL observation wherever multi-query newest equality currently requires a read lock. Empty published sources remain distinguishable from missing publication. Picker count/page descriptions retain current-data offset semantics and may lag. Genuine malformed stored facts and canonical identity ambiguity remain errors.

Reintroducing catalog history, version/hash pointers, a process cache or pricing recapture would create discarded authority. Retaining shared owner locks merely to prevent publication interleaves would violate the confirmed read contract. Both are rejected.

## D2 — Descriptive capability capture and final acceptance use distinct boundaries

Descriptive capture uses independent read capability without integration/source/catalog read fencing. Actual consumed-input revalidation retains the existing sorted integration/source/catalog exclusion in the owner write transaction through the persisted acceptance/publication. Keep value/absence expectation comparison and existing captured capability DTOs. A stale descriptive capture may be rejected there rather than forcing a current locked preparation read.

Dropping shared helpers' locks indiscriminately would weaken current model-operation acceptance. An early comparison followed by an unguarded mutation is insufficient. This phase separates reader APIs from the existing critical guard rather than replacing that guard with a new protocol.

## D3 — Exact Memory revision plus its own manifest is the read reference

Use an ordinary correlated projection for exact unit/revision, current permitted consumer scope and the revision's complete manifest. Missing/denied dependencies count as unavailable, including SQL UNKNOWN. Content-only source advancement does not substitute a new revision's manifest or bytes; availability/grant discontinuity still denies the affected unit. Validate immutable rendered bytes against their declared artifact.

A collected reference can disappear after capture and before descriptive snapshot persistence; later admission/filtering treats that exact missing reference as unavailable. No new retention pin, cache or privileged fallback is introduced to preserve every description. The existing immutable artifact and next-admission privacy filtering determine this outcome.

## D4 — Producer reads retain receipt identity, not source read locks

Use a scoped joined ordinary read of exact source identity/bytes/version facts for inventory/work delivery. Keep the actual job/attempt owner, lease/deadline, exposure receipt, observation epoch and terminal commit validation in the existing write transaction. Final draft dependency/manifest validation and publication remain a separate guarded mutation path. Do not replace the shared publication helper globally with a permissive reader.

## Risks

Committed descriptions can lag and selection can become unavailable after collection. Read lag never grants privacy/side-effect authority. Single-statement predicates must preserve all tenant/Agent/root/User/grant/availability/hash identities, including null-denial semantics. Deterministic tests must prove both nonblocking description and unchanged critical acceptance; timing-only evidence is insufficient.
