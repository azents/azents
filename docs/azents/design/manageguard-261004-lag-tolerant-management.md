---
title: "Lag-Tolerant Management Design"
created: 2026-10-04
tags: [backend, concurrency, authorization, management]
document_role: primary
document_type: design
snapshot_id: manageguard-261004
---

# Lag-Tolerant Management Design

## Design Authority

Revision: 2. [Requirements](../requirements/manageguard-261004-lag-tolerant-management.md) and [ADR](../adr/manageguard-261004-lag-tolerant-management.md) share snapshot `manageguard-261004`.

- M1 (derived): unlocked scoped identity/CRUD authorization with conditional non-owner/security mutations and narrow durable namespace claim; `REQ-1`, `REQ-2`, `ADR-D1`, `ADR-D4`.
- M2 (derived): ordinary registry/administration reads separated from path claims and existing version-conditioned mutations; `REQ-1`, `REQ-3`, `ADR-D2`.
- M3 (derived): descriptive external/configuration reads separated from exact final identity/credential issuance, OAuth configuration publication, one-time consumption and quota admission; `REQ-4`, `ADR-D3`, `ADR-D4`.
- M4 (required): actual shared caller audit, retained-exception register and deterministic security/read-only verification; `REQ-5`.

## Design Approval

Direct implementation of the expressly requested ordinary-management phase. Requester owns fixed lag-tolerant read/removal and unchanged public security constraints. Date: 2026-10-04. Revision 2 authority set M1–M4 records the derived implementation boundary, including the existing durable namespace claim and exact OAuth configuration-finalization outcome. No new user-visible recovery, required version, schema, persistence authority, mode or quota/permission policy is introduced. Material departures return to Requirements/ADR before implementation.

## M1 — Identity and CRUD Boundary

Workspace, membership, Agent/Admin, Toolkit and integration descriptions use `ReadSession` with existing exact identity/Workspace/actor predicates. Ordinary operation repositories use completed read or mixed write scope as appropriate, but never acquire parent/member/key-share locks merely to force the newest permission projection. Remove ordinary locked aliases and constructor/caller flags with their tests; shared critical callers receive an explicitly named narrow mutation guard instead of an optional locked-read fallback.

Non-owner membership UPDATE/DELETE conditions include role-not-OWNER at the actual statement and preserve existing result classification using scoped post-result descriptions when needed. Ownership transfer remains one coherent multi-row security mutation; narrowly serialize that operation where its existing rows/constraints cannot express the guarantee alone. Final-admin revocation/User deletion and last-credential removal preserve existing security rejection. Plain role inspection and unrelated grants use uniqueness/idempotence without inheriting a global revoke gate.

Keep tenant/permission/exact-target checks for chat/input/Project/model-profile callers of membership/Agent helpers. Execution owner claims and lifecycle result finalization are not ordinary management reads and remain explicitly separate for the later phase.

Shared Toolkit slug changes and attachment perform a durable namespace allocation.
Their actual Toolkit-scoped identity claim retains minimal mutual exclusion
through commit; ordinary Toolkit reads, unrelated metadata and authorization do
not acquire it. Concurrent attach/slug mutation must converge without a stale
namespace reservation or a new mismatch policy.

## M2 — Project and Runtime Administration

Ordinary Project registry mutation validates exact Agent/Session/context/role using plain reads and existing structural constraints. Runtime/path advisory serialization belongs only to actual competing worktree claims/resource operations, not generic registration/status reads. Do not change selected filesystem paths or delete Runner folders during registry deletion.

Runtime Provider/Profile administrative fields use existing scoped version predicates, database increment expressions and RETURNING where adequate. Whole availability/policy replacement remains transactional; exact reference/version/FK outcomes are preserved at the completed owning scope. System Settings changes retain existing candidate/current expected versions at the write; ordinary reads remain unlocked. Single-winner migration orchestration and actual enrollment consumption/connection-generation publication retain narrowly classified guards, not general binding/status locks.

Project creation that may bind PENDING context retains the existing exact-target
binding mutation, while already-BOUND inspection/registration/deletion uses
ordinary retained context. Registry insertion participates in the narrow
Runtime/path claim exclusion required to prevent overlapping destructive cleanup;
plain registry descriptions do not. Exact path uniqueness alone is not proof
against parent/child cleanup overlap.

## M3 — External and Runtime Web Read Boundary

External connection/binding/model-setting/account descriptions use plain exact actor/resource/route reads. Final settings/credential publication preserves existing target/revision/attempt predicates. Interaction/OAuth callback claim and obsolete credential finalization remain explicit operations, not exemptions for all surrounding configuration methods.

Runtime Web pure identity/configuration/service descriptions are already ordinary reads where applicable; do not churn them. Final identity/ticket/binding issuance retains the minimal exact configuration exclusion through commit so configuration revocation cannot be followed by a stale same-mode identity insert. Ticket redeem retains one-time ticket/binding consumption and exact association/expiry checks. Quota scope remains only active-slot admission protecting the existing hard limit; detail/UI/status reads and revision-conditioned service metadata changes do not inherit it. Route ownership/nonce/generation operations remain lifecycle/claim/consumption boundaries.

Slack/Discord identity OAuth current-configuration writes join the existing
Section fence held by actual callback claim/link finalization. Version CAS alone
on the setting row cannot protect environment-backed absence or another row's
dependent auth mutation. Other Section writes remain version-conditioned;
ordinary candidate/state reads do not acquire this fence. Bootstrap optional
platform default initialization is an existing unset-only conditional mutation,
so a concurrent administrator value is retained rather than overwritten or
converted into a new public retry policy.

## Removal and Replacement

- Ordinary parent/member/Agent/Toolkit locked loads and hidden lock flags: exact scoped reads plus actual mutation predicates.
- Non-owner read-before-write role protection: non-owner conditional UPDATE/DELETE, coherent transfer mutation.
- Generic Project path/read serialization: structural scoped registry mutation; actual worktree claim/resource coordination remains separately classified.
- Profile/Provider/settings pre-read freshness locks: existing version/source-conditioned write or shortest required replacement transaction.
- External management blanket authority loads: scoped ordinary reads; exact claim/consumption/finalization guards remain.
- Lock-order assertions for discarded defensive reads: successful held-writer read and public concurrent outcome tests.
- No schema/client/configuration changes, compatibility aliases, cache, relaxed quota or filesystem deletion behavior is introduced.

## Retained Exception Register

For each remaining explicit fence in this phase record precise caller/operation, E1 winning claim or E2 consumption or E3 critical obsolete-result/security mutation, exact outcome, rows/shortest scope, simpler conditional-write alternative and deterministic test. Initial operation candidates are ownership transfer, final-admin/last-credential removal, Runtime Web configuration-finalized issuance, ticket/binding consumption, active quota slot admission, and real worktree/migration claims. These candidates are not module-wide exemptions; ordinary consumers must not inherit them. The final implementation report closes this register from actual changed paths.

## Test Strategy

Primary API/E2E matrix uses existing Workspace/member/Agent/Toolkit/Project/profile/provider/settings/external/Runtime Web suites, unchanged credentials and prerequisites. Real database tests establish held-writer ordinary reads without FOR UPDATE/SHARE/advisory acquisition; deterministic interleaves cover transfer versus non-owner mutation, last-admin revoke/delete, credential retention, expected-version competition, reference/FK conflict, refresh versus delete, configuration revocation versus same-mode issuance, quota competition and capability replay. Preserve typed existing failure outcomes and exact tenant filtering. Use events/barriers or authoritative state, not sleeps. CI runs complete backend quality and applicable required E2Es for each delivered head; optional live credentials retain their explicit current skip rules.

## Feasibility and Operations

Existing scoped predicates, constraints, version fields and operation-level guard rows support this separation. A currently required final fence may remain only for a documented existing security/claim/consumption outcome; ordinary read-lag is never its justification. Missing constraints cannot be replaced by invented API/schema during this phase. No Agent merge, deployment, live mutation, rollout toggle or compatibility mode is authorized.
