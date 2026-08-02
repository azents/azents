---
title: "External Channel Automatic Title Phase 3 Reconciliation and Lifecycle Execution Plan"
created: 2026-08-02
updated: 2026-08-02
tags: [external-channel, discord, title, backend, worker, lifecycle]
---

# Phase Execution Plan

- Phase: `3 — Title reconciliation and lifecycle`
- Branch/base:
  `feat/external-channel-title-reconciliation-lifecycle` →
  `feat/external-channel-title-admission-proof`
- PR boundary: Atomically arm the winning final automatic Session title, reconcile
  exactly one proven Discord thread title through GET-before-PATCH, and terminate or
  purge projection authority across every restrictive lifecycle boundary.
- Inputs:
  - approved `title-260802/REQ`;
  - accepted `title-260802/ADR-D1` through `ADR-D6`;
  - approved `title-260802/DESIGN` revision `5`;
  - Phase 1 candidate/projection persistence from PR #1093;
  - Phase 2 exact admission provenance, provider proof, and Worker provisioning
    reconciliation from PR #1094;
  - current Session-title and Session-lifecycle orchestration.
- Deliverables:
  - strict provider-compatible normalization that rejects an empty final title
    before any Session or projection mutation;
  - atomic `auto_initial -> auto_generated` Session replacement and exact
    projection arming in one transaction;
  - fenced title claim settlement for applied, retry, relinquished, and permanent
    or authority-revoked outcomes;
  - direct Discord thread-channel GET and name-only PATCH contracts;
  - GET-before-PATCH reconciliation that applies once, recognizes already-applied
    state, recovers ambiguous PATCH outcomes by GET, and preserves provider or human
    takeover;
  - bounded due-title drain in the existing provider-control Worker alongside the
    Phase 2 provisioning drain;
  - archive, route removal, connection disconnect or termination, Agent
    decommission, restore, and purge behavior that prevents later provider mutation;
  - restrictive purge ordering for projection, candidate, Binding-owned state, and
    Session finalization with explicit absence verification;
  - lifecycle participant policy version `2` plus a generated forward-progress
    migration that resets incomplete `session.external-channel@1` executions to the
    version-2 contract before old-version support is removed;
  - multi-Binding isolation and later-Binding non-inheritance.
- Non-goals:
  - deterministic Discord fake or product E2E changes;
  - Living Spec promotion or snapshot `implemented` marking;
  - a new schema shape, process, queue, Redis dependency, feature flag, Worker mode,
    API, frontend, Helm setting, environment variable, or fallback;
  - synchronization after the one terminal automatic title operation;
  - propagation of manual Session titles, later Agent names, or provider names back
    into Session authority.
- Interfaces:
  - the existing generated-title transaction strictly normalizes the model result
    once and rejects an empty result before replacing the exact `auto_initial` title
    or arming any projection; it arms only projections whose durable candidate was
    consumed by the same generation Event;
  - armed `desired_title` and `title_generation_event_id` are immutable and remain
    authoritative after a later manual Session title edit or clear;
  - title claims use the exact projection ID, attempt count, and claim timestamp;
  - every settlement re-locks and revalidates projection, Resource, creating
    Binding, candidate and consumed Event, Session, route, Agent, connection,
    credential, canonical target, and immutable thread identity;
  - provider reconciliation GETs the exact thread first, settles applied without
    PATCH when already desired, relinquishes without PATCH when the name differs
    from the expected provisional title, and PATCHes only the exact desired name
    after an adjacent authority check;
  - transient, rate-limited, transport, process, and ambiguous PATCH outcomes
    persist capped retry and begin the next attempt with GET; there is no fixed
    attempt exhaustion while complete authority remains current;
  - cancellation re-raises `CancelledError` without settlement so stale recovery
    reclaims the durable `attempting` row and begins with GET;
  - confirmed permanent target, permission, credential, or lifecycle failure
    terminalizes before another mutation;
  - every GET validates exact channel, Guild, parent, and immutable thread identity;
    PATCH changes only the `name` field, and generated or provider title content is
    absent from logs and persisted failure summaries;
  - archive and every Binding, Resource, route, Agent, or connection revocation or
    deletion terminalize nonterminal provisioning and title work in the lifecycle
    transaction without provider I/O; restore preserves terminal state and never
    re-arms;
  - purge deletes title projections before candidates and verifies both tables are
    empty before restrictive Session finalization;
  - the Session lifecycle participant advances to policy version `2`; a generated
    data migration converts every incomplete version-1 execution to version 2,
    resets its phase to `pending`, and clears phase checkpoints so idempotent
    prepare, cleanup, and verification rerun under the expanded ownership contract;
    completed and cancelled purge tombstones remain unchanged;
  - migration downgrade refuses while version-2 executions or durable title
    artifacts make the version-1 contract unsafe.
- Approved Design mechanisms: `M3`, `M5`, `M6`, `M7`, lifecycle portion of `M8`
- Authority references:
  `title-260802/REQ-2`, `REQ-4`, `REQ-5`, `REQ-6`, `REQ-7`;
  `title-260802/ADR-D1`, `ADR-D2`, `ADR-D3`, `ADR-D4`, `ADR-D6`;
  `title-260802/DESIGN` revision `5`
- Design delta: `None`
- Removal obligations:
  - replace the creation-only prohibition only for the one proven automatic title
    projection while retaining later Session, Agent, and Discord rename
    independence;
  - replace unfenced title mutation and settlement with exact claim and full-owner
    revalidation;
  - keep ordinary delivery in the existing at-most-once ledger while projection
    title retries remain isolated in the projection aggregate;
  - add projection and candidate cleanup before restrictive Binding and Session
    finalization.
- Absence verification:
  - tests prove no PATCH for unmanaged, unarmed, mismatched, taken-over, revoked, or
    later-Binding projections;
  - actual ordinary delivery readers and enums remain unchanged;
  - grep and behavior tests prove no title synchronization after terminal success,
    no manual-title propagation, and no new runtime/configuration surface;
  - lifecycle verification and finalization directly prove no projection or
    candidate remains before Session purge finalization;
  - migration tests prove incomplete version-1 jobs resume under version 2 and no
    unsupported active participant snapshot remains.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Atomic arming and title repository settlement | `/root/title-persistence-owner` | `repos/external_channel/title.py`; `services/session_title.py` integration contract; focused title repository and Session-title tests | Phase 2 candidate/Event and provider-readiness contracts | Strict non-empty provider-normalized immutable arming and exact fenced applied/retry/relinquished/failed settlements | Repository DB tests; Session-title empty-result, transaction, manual-edit, retry, stale-claim, authority, and multi-Binding tests |
| Discord title reconciliation and Worker drain | `/root/title-runtime-owner` | `services/external_channel/{discord_delivery.py,discord_projection.py,provider_control.py}` and focused tests | Stable title settlement and authority-loader interfaces | Direct thread GET/PATCH, GET-before-PATCH convergence, takeover fence, ambiguous recovery, bounded Worker title drain | Discord client/reconciler/provider-control tests; cancellation and permanent/transient outcome tests |
| Restrictive lifecycle and purge | `/root/title-persistence-owner` | generated Phase 3 migration and revision pointer; `repos/external_channel/{lifecycle.py,repository.py}`; `services/external_channel/lifecycle.py`; `services/session_lifecycle/registry.py`; lifecycle/repository/decommission/purge focused tests | Stable projection terminalization contracts | Policy-v2 forward progress, archive, Resource/route revocation, disconnect/termination, decommission, restore, and projection-before-candidate purge semantics | Migration upgrade/downgrade guards; lifecycle repository/service, Chat archive/restore, Agent decommission, archived purge, manifest, and absence tests |
| Plans and integration | `/root` | phase plan, shared composition, cross-workstream fixtures, branch/PR metadata | All workstreams | Integrated Phase 3 diff, scope audit, final validation, PR | Combined Ruff, Pyright, focused/full Pytest, diff and forbidden-surface audits |
| Independent review | `/root/title-feature-reviewer` | Read-only complete Phase 3 diff | Stable implementation and evidence | Prioritized findings or PASS | Review against M3/M5/M6/M7/M8, immutable arming, provider takeover, claim fencing, lifecycle order, and phase boundaries |

- Integration order:
  1. Persistence owner completes provider normalization at the atomic Session-title
     handoff and defines exact title claim settlement contracts.
  2. Runtime owner adds direct Discord thread GET/PATCH contracts and the title
     reconciler against those stable repository interfaces.
  3. Runtime owner wires bounded title reconciliation into the existing
     provider-control drain without changing ordinary delivery.
  4. Persistence owner generates the policy-v2 forward-progress migration,
     terminalizes provisioning and title authority in shared lifecycle repository
     boundaries without provider I/O, and adds projection-before-candidate purge
     and verification.
  5. Owners add multi-Binding, manual-edit, stale-recovery, provider-takeover,
     ambiguous-PATCH, archive, disconnect, decommission, restore, and purge tests.
  6. Each owner runs focused checks and requests read-only review from
     `/root/title-feature-reviewer`.
  7. Primary orchestrator integrates, audits both directions of scope drift, runs
     the combined matrix, commits, and opens the stacked PR.
- Independent review:
  - Reviewer: `/root/title-feature-reviewer`.
  - Scope: complete Phase 3 diff against `title-260802/REQ-2`, `REQ-4`, `REQ-5`,
    `REQ-6`, `REQ-7`, ADR D1/D2/D3/D4/D6, M3/M5/M6/M7/M8, and this phase contract.
  - Criteria: exact atomic arming, provider-compatible immutable snapshot, complete
    title claim fences and final authority checks, GET-before-PATCH takeover
    preservation, safe ambiguous recovery, non-blocking ordinary behavior,
    restrictive lifecycle terminalization and purge order, multi-Binding isolation,
    policy-v2 forward progress for incomplete version-1 snapshots, and Phase 4/5
    exclusion.
  - Inputs: Requirements, ADR, approved Design revision 5, current Specs, PR #1093,
    PR #1094, this plan, implementation diff, and validation evidence.
  - Output: grounded Critical/Warning findings or explicit PASS.
- Final validation:
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`
  - `cd python/apps/azents && uv run pyright`
  - focused Session title, title repository, Discord delivery/projection,
    provider-control, lifecycle repository/service, archive/restore, decommission,
    purge, registry, migration, and multi-Binding Pytest
  - full backend Pytest because lifecycle ownership and purge ordering cross shared
    Session finalization
  - production title-PATCH and lifecycle call-site audits
  - `python -m pytest scripts/tests/test_gen_docs_index.py`
  - pre-commit snapshot/frontmatter/index validation during commit
  - `git diff --check`
- Validation evidence:
  - Ruff format and check passed for all 20 changed Python files.
  - Full backend Pyright passed with `0 errors, 0 warnings`.
  - Primary integrated title, Discord, lifecycle, management, migration, archive,
    decommission, and purge matrix passed: `218 passed`; the only warnings were
    three existing testcontainers deprecation warnings.
  - Full backend Pytest passed: `3925 passed`, with six existing non-blocking
    dependency or SQLAlchemy warnings.
  - Documentation index tests passed: `14 passed`.
  - Alembic reports one head, `b00cf0366fa3`. The focused migration regression
    proves incomplete version-1 External Channel participant executions reset to
    version 2, completed and cancelled tombstones remain unchanged, and unsafe
    downgrade is refused.
  - Real two-session PostgreSQL regressions execute the actual archive and
    connection-disconnect lifecycle transactions. Title settlement yields
    immediately with `NOWAIT`, lifecycle commits, no false settlement is recorded,
    and stale `attempting` work remains recoverable.
  - Independent review found and verified corrections for canonical target races,
    exact consumed-Event authority, same-Resource multi-Binding isolation,
    lifecycle lock contention, and all audited Discord connection or credential
    revocation paths. Final complete-diff review reported PASS with no remaining
    Critical or Warning finding.
- Scope-drift check:
  - verify every Phase 3 outcome and removal obligation is implemented;
  - verify Session execution and ordinary at-most-once delivery remain independent
    from title readiness and retry;
  - verify manual Session titles, later Agent names, provider takeover, existing
    threads, later Bindings, or restored Sessions cannot create new title authority;
  - verify no schema expansion beyond the policy-version data migration,
    deterministic fake/E2E, Spec promotion, API, frontend, configuration, new
    queue/process, Redis dependency, or fallback was added;
  - return any new material mechanism to feature design.
- Context checkpoint:
  - Phase 2 provides durable exact admission provenance, direct/adopted provider
    readiness, stored provisional title authority, and a provisioning Worker drain.
  - Existing M3 repository methods already support the atomic generated-title
    handoff and existing title claims support skip-locked due/stale recovery.
  - Phase 3 fills only the missing title settlement, provider GET/PATCH, Worker title
    drain, and lifecycle cleanup contracts.
  - No schema shape change is required. Existing immutable participant snapshots
    require policy version `2` and a generated forward-progress data migration that
    safely replays incomplete version-1 External Channel cleanup.
  - Final-title reconciliation now verifies canonical Resource/thread equality and
    exact consumed-Event authority before every provider operation and settlement.
    Discord authority revocation terminalizes both phases transactionally, including
    callback reset, activation failure, reconnect-required transitions, and single
    or Multi configuration replacement.
  - Lifecycle settlement uses fail-fast `NOWAIT` owner locking. Contention rolls
    back without inventing authority loss and leaves durable stale work for
    GET-first recovery.
  - Phase 4 still owns deterministic fake/E2E and integrated product validation.
    Phase 5 still owns Living Spec promotion, implementation marking, and plan
    cleanup. Design delta: `None`.
