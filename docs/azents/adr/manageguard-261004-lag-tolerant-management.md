---
title: "Lag-Tolerant Management Decisions"
created: 2026-10-04
tags: [backend, concurrency, authorization, management]
document_role: primary
document_type: adr
snapshot_id: manageguard-261004
---

# Lag-Tolerant Management Decisions

Authority: [manageguard-261004/REQ](../requirements/manageguard-261004-lag-tolerant-management.md). The requester-fixed read/removal standard and existing security outcomes determine the boundaries below; local implementation details create no additional authority.

## D1 — Plain descriptive reads plus scoped conditional mutations

Replace ordinary parent/member/Agent/Toolkit locked loads with exact scoped ordinary reads. Use existing target identity, version and role predicates at actual updates/deletes, database expressions/RETURNING and constraints where adequate. Non-owner role update/delete includes the non-owner condition in the mutation itself, so a stale descriptive load cannot modify a newly assigned OWNER.

Ownership transfer, last-system-admin/credential removal and other dependent security-state writes keep only the narrow serialization/atomic mutation required by their existing invariant. Record every retained explicit fence by exact operation and guarantee. A broad helper/module exemption or ordinary grant/list gate is rejected.

## D2 — Registry and administration reads do not inherit claims

Ordinary registered Project CRUD and Profile/Provider/settings descriptions use plain scope/identity evidence. Actual worktree path claims, migration single-winner orchestration and generation-sensitive resource finalization remain separate operations. Existing version-conditioned administration and FK conflict mapping replace pre-read latestness locks where adequate. Do not weaken whole-policy replacement atomicity or invent a new required client version.

## D3 — Exact authentication issuance/consumption, not blanket security reads

Split Runtime Web/configuration and external-account/channel descriptions from final identity/ticket/credential admission. Same-mode configuration changes revoke identities; final issuance must remain excluded from the revocation transition or use an equivalent existing conditional mutation through commit. The current identity lacks a configuration fingerprint, so removing its final configuration fence without a replacement would violate the existing contract.

Retain the minimal ticket/binding one-time consumption and active-slot quota admission guard. Pure identity/configuration/route descriptions and ordinary settings reads do not inherit them. Do not add a new fingerprint schema, change hard quota to best-effort counting or classify all authentication methods as exceptions.

## Risks

Shared locked helpers have both management and deeper execution/admission callers. Migrate or split actual callers instead of deleting locks globally. Deferred FK failures must be classified at the completed transaction boundary. Deterministic security/concurrency evidence is required; historical low frequency or descriptive latestness is not a retained-lock justification.

## D4 — Preserve durable namespace allocation and exact configuration finalization

Concurrent shared Toolkit slug mutation and attachment allocate durable executable
namespace identities. Retain only the Toolkit-scoped allocation exclusion at
those actual claim mutations; ordinary Toolkit/Agent authorization descriptions
do not inherit it. Allowing a stale attach to allocate an inconsistent namespace
or weakening the existing namespace mismatch contract is not authorized.

Slack/Discord identity OAuth configuration publication participates in the exact
Section exclusion used by callback consumption and link finalization, including
environment-backed absent current rows. Their generation read alone is not an
atomic commit fence. Other ordinary Section writes use existing version CAS, and
pure state/candidate inspection does not inherit OAuth finalization locks.
Optional platform default initialization uses a conditional unset/default
mutation so a concurrent administrator value wins without a new conflict/retry
policy. No blanket Section lock or new configuration fingerprint is introduced.
