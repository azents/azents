---
title: "Management Read and Mutation Boundary Verification"
created: 2026-10-04
tags: [backend, concurrency, authorization, testing]
document_role: supporting
document_type: supporting-verification
snapshot_id: manageguard-261004
---

# Management Read and Mutation Boundary Verification

## Scope

This report closes the operation-specific boundary of `manageguard-261004`, not the later execution/lifecycle residual audit. Ordinary descriptions and harmless management metadata do not earn exceptions merely because their module also owns security mutations. Normal PostgreSQL write locks, constraints and transactions are not explicit read locks.

## Exact Retained Guarantees

### Winning identity/resource claims (E1)

- Shared Toolkit slug replacement and attachment coordinate the exact Toolkit namespace claim. Missing/mismatched namespace allocation additionally fences the exact Agent and per-base sequence; matching active reuse does not. Competing distinct Toolkits and shared attach/slug tests preserve unique stable executable identity. The existing allocator has no schema-independent equivalent absent-row exclusion from a plain SELECT; it is not replaced by a weak early read.
- Project registry insertion versus destructive overlapping worktree cleanup uses the existing Runtime/path claim coordination. Exact-path uniqueness does not exclude ancestor/descendant cleanup overlap. BOUND registry inspection/list/deletion does not inherit that gate, and PENDING binding remains an exact-target mutation.
- Optional PLATFORM_RUNTIME initialization and candidate intent share their initialization claim. Ordinary current-state administrator mutation uses existing version CAS, not that claim. Tests cover both candidate/seed orders and both administrator/initializer orders without overwriting an administrator or rolling back Provider creation.
- Runtime Web quota scope protects only actual active-slot admission, preserving the hard concurrent limit. Service detail and revision-conditioned metadata/Off/reset/delete do not inherit it.

### One-time consumption (E2)

- Runtime Web ticket/binding settlement and identity issuance retain exact association, expiry and single consumption.
- OAuth callback attempt and Provider enrollment consumption remain existing exact operations. Ordinary account/Provider/binding descriptions do not inherit their guards.

### Critical security/obsolete-result mutations (E3)

- Initial OWNER creation and ownership transfer fence one Workspace's dependent security role writes. Ordinary non-owner update/delete uses `role != OWNER` at the actual statement. Membership removal owns its exact row transition and captures the old grant before recording denial and deleting; restored membership has a new grant identity.
- Actual Session and system-role grant retain exact active-User eligibility through commit. Grant/revoke also coordinate only the exact User/role assignment so conflict lookup cannot disappear into a new 500. Grant/list does not take the global final-admin removal gate. Final-admin revoke/User deletion retains its minimal administrator-removal exclusion and counts enabled Users, not legacy disabled assignments.
- Agent Memory enablement transition publishes denial continuity atomically; avatar replacement captures old-blob cleanup responsibility. These field-specific writes are not exemptions for ordinary Agent configuration reads.
- Final OAuth link and external model-setting apply retain exact User/auth-session/link, lifecycle and principal block/grant exclusion through the dependent commit. Ordinary inspection/edit authorization remains plain. Final model acceptance keeps the separately implemented captured-value/absence guard.
- Slack/Discord identity OAuth current-setting publication takes the same exact Section exclusion as callback/link finalization, including environment-backed absent rows. Other ordinary setting writers/readers do not inherit that fence.
- Runtime Web configuration-finalized identity issuance remains excluded from same-mode revocation sweep. Connection configuration replacement/disconnect uses explicit refreshed transition mutation, preserving generation and refusing DISCONNECTING replacement. Policy/status readers remain plain.
- Provider bootstrap/credential/contract/recreation mutation guards and exact Profile selection/generation finalization remain named operation boundaries. Ordinary Provider/binding/declaration/connection getters expose no lock flag. Profile delete conflict requery observes actual current Workspace Profile state rather than an ORM-synchronized failed-CAS image.

## Removed Read Serialization

Workspace/member/OWNER/Admin/Toolkit locked aliases and ordinary caller branches are removed. Ordinary registry context and already-BOUND folder checks use scoped retained reads. Provider policy/availability and service revision changes use atomic SQL mutation instead of pre-read freshness locks. Source/integration deletion does not lock Workspace/catalog parents; exact scope and FK cascade preserve cleanup, while concurrent publication cannot resurrect deleted catalogs.

Existing generic Agent/Runtime execution-tree and lifecycle primitives are deferred to the separate final phase, not renamed as blanket exceptions here. The final inventory must classify them by operation before removal or retention.

## Deterministic Evidence

Real PostgreSQL tests hold writers while descriptions complete, then independently test actual mutation ordering. Coverage includes namespace identity, OWNER transfer, grant/disable/revoke and Session issuance, old-grant denial continuity, BOUND/PENDING Project behavior, Settings candidate/current/initializer races, Profile CAS conflict, configuration replacement/disconnect, OAuth finalization and Runtime Web quota/reset races. Ordering uses events/authoritative lock attempts, not sleep assumptions.

Named owners requested independent scoped review and corrected material findings in one affected boundary at a time. Critical authorization guards accidentally removed from finalization, stale generation/reset writes, role grant races and Profile failed-CAS projection were repaired without restoring blanket descriptive locks. Full-suite results and latest-SHA CI are reported in the PR rather than inferred from overlapping focused reruns. No live resource changes, Agent merge or security-alert dismissal were performed.
