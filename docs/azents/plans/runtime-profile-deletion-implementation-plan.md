---
title: "Runtime Profile Deletion Implementation Plan"
created: 2026-08-11
updated: 2026-08-11
tags: [runtime, profile, persistence, api, frontend, testenv]
---
# Runtime Profile Deletion Implementation Plan

## Authority and Scope

- Requirements: [Runtime Profile Deletion Requirements](../requirements/profile-260811-runtime-profile-deletion.md) (`profile-260811/REQ`)
- ADR: [Runtime Profile Deletion](../adr/profile-260811-runtime-profile-deletion.md) (`profile-260811/ADR`)
- Approved Design: [Runtime Profile Deletion Design](../design/profile-260811-runtime-profile-deletion.md) (`profile-260811/DESIGN`, revision 1)
- Approved mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`
- Current Specs:
  - [Agent Domain](../spec/domain/agent.md)
  - [Workspace Domain](../spec/domain/workspace.md)
  - [Agent Runtime Control](../spec/flow/agent-runtime-control.md)
  - [Agent Runtime Persistence](../spec/flow/agent-runtime-persistence.md)
- Design delta: None.

## Objective

Replace permanent Runtime configuration revisions with bounded desired/applied current state and exact sequence fencing, then permit a Workspace Owner to permanently delete a Workspace Runtime Profile while preserving already running Runtime and Agent Workspace continuity. Deliver the coordinated schema, Runtime Control, backend, API, generated-client, Web, E2E, and Living Spec changes without a legacy protocol or fallback Profile mode.

## Delivery Stack

| PR | Branch | Base | Deliverable | Approved mechanisms | Dependencies |
| --- | --- | --- | --- | --- | --- |
| 1/6 | `design/runtime-profile-hard-delete-current-state` | `main` | Approved Requirements/ADR/Design baseline, implementation plan, and Phase 1 execution contract | `M1`–`M8` | Merged containment-removal PR #1257 |
| 2/6 | `feature/runtime-configuration-current-state` | PR 1 | Coordinated revision-to-current-state schema, repository, Runtime Control, Provider, Runner, receipt, recreation, and status-contract cutover | `M2`, `M3`, `M4`, `M6`, `M7` | PR 1 |
| 3/6 | `feature/runtime-profile-hard-delete` | PR 2 | Owner-only atomic Profile hard deletion, selection clearing, Runtime unconfiguration, recreation supersession, API, OpenAPI, and generated clients | `M1`, `M4`, `M5`, `M6`, `M8` | PR 2 |
| 4/6 | `feature/runtime-profile-deletion-web` | PR 3 | Owner-only permanent-delete UX, impact confirmation, result/error handling, recovery presentation, and primary Docker-backed E2E | `M1`, `M4`, `M6`, `M8` | PR 3 |
| 5/6 | `feature/runtime-profile-deletion-spec-validation` | PR 4 | Repository-wide validation, required E2E evidence, Living Spec promotion, and implemented snapshot metadata | `M1`–`M8` | PR 4 |
| 6/6 | `chore/runtime-profile-deletion-plan-cleanup` | PR 5 | Remove this implementation plan and all phase execution plans after validated spec promotion | None; cleanup only | PR 5 |

All branches form one linear stack. Each PR is opened before work begins on the next PR. The complete stack is created before CI monitoring begins.

## Workstreams and Integration Boundaries

### Current configuration state cutover

- Owns the forward Alembic migration, ORM/domain models, repositories, Runtime Profile resolution/reconciliation, lifecycle transitions, Runtime Control sinks/reconcilers, operation target qualification, recreation and Runtime-add fencing, protobuf contract, generated Runtime Control modules, Providers, Runner, and focused tests.
- Replaces revision UUID authority with the exact tuple of Runtime ID, desired generation, configuration sequence, digest, and current Provider or Runner generation.
- Migrates only current desired/applied and active operation authority, then drops the revision table and obsolete foreign-key columns.
- Must leave no active compatibility branch, revision alias, historical configuration catalog, or mixed-protocol acceptance path.

### Runtime Profile hard deletion

- Owns Workspace delete permission, owner role mapping, transactional Profile deletion, Workspace default and Agent selection clearing, selection-version advancement, Runtime desired-state unconfiguration, active recreation supersession, bounded impact counts, audit logging, public API, OpenAPI, and official generated clients.
- Must preserve current applied state, Provider routing, stop/observe/terminal removal, and Agent Workspace storage.
- Must not choose a fallback Profile, retain a tombstone, or expose cross-Workspace existence.

### Web and E2E

- Owns the Runtime Profile management delete affordance, owner gating, impact/name confirmation, optimistic-version conflicts, result feedback, unconfigured recovery presentation, and Docker-backed end-to-end coverage.
- Uses only generated public-client contracts and server-provided permission/status projections.
- Kubernetes coverage is added only through the existing qualified lane and follows its current prerequisite policy.

### Validation and Living Specs

- Runs focused and repository-wide Python, protobuf generation, TypeScript, migration, OpenAPI/client-generation, testenv, E2E, and absence checks on the stable integrated diff.
- Updates only current Living Specs after the implementation is proven.
- Adds the same `implemented: 2026-08-11` date to the Requirements and Design only after all required implementation and validation evidence passes.

## Data and Migration Checkpoint

- Add `agent_runtimes.configuration_sequence` as the monotonic high-water mark.
- Add one-to-one `runtime_configuration_states` with one desired slot and one applied slot.
- Replace receipt and recreation revision foreign keys with scalar sequence/digest/desired-generation evidence.
- Backfill only non-null current desired/applied pointers and active receipt/recreation fencing.
- Validate cross-Runtime ownership, ready-document/digest integrity, and convertible active operation evidence before destructive contraction.
- Remove revision pointers and duplicate desired-source columns, then drop `runtime_configuration_revisions`.
- Downgrade may reconstruct only current desired/applied rows and cannot restore superseded history or hard-deleted Profiles.
- Existing executed migrations are immutable; all schema work uses a new forward migration.

## API and Protocol Checkpoint

- Runtime Control field 1 retains its existing wire number and string wire type while the generated field name and validation become canonical positive decimal configuration sequence.
- Provider and Runner admission remains exact-version and generation fenced; no old-revision server acceptance branch is added.
- Public status models expose bounded desired/applied current state and configuration sequence instead of revision models.
- The delete route is `DELETE /runtime-profile/v1/workspaces/{handle}/profiles/{profile_id}` with required `expected_version` and bounded impact counts.
- Generated Python and TypeScript public clients are regenerated from the checked-in OpenAPI source.

## Removal Obligations and Absence Evidence

| Removed authority | Owning PR | Required absence evidence |
| --- | --- | --- |
| `runtime_configuration_revisions` table, ORM/domain models, and repository methods | 2/6 | Schema introspection, migration tests, active-source symbol search |
| Agent Runtime desired/applied revision pointers and duplicate desired source columns | 2/6 | ORM/OpenAPI/schema search and focused repository tests |
| Revision cloning, acknowledgement, equality, and promotion | 2/6 | Repository/service symbol search and sequence CAS tests |
| Recreation and Runtime-add receipt revision foreign keys | 2/6 | Migration, replay, recreation, and active-source search |
| Protobuf/shared-runtime `revision_id` terminology | 2/6 | Generated module inspection, protocol tests, active-source search |
| Public revision response models and Web revision labels | 2/6 and 4/6 | OpenAPI/client/UI search and rendering tests |
| Workspace/Agent foreign keys that prevent Profile deletion | 3/6 | Schema inspection and hard-delete integration tests |
| Profile archive/tombstone/fallback deletion substitutes | 3/6 and 4/6 | API/E2E behavior and active-source search |
| Temporary implementation and phase plans | 6/6 | `git ls-files docs/azents/plans` feature-prefix absence |

Historical Requirements, ADRs, Designs, and migration files remain searchable provenance and are excluded from active-code absence checks.

## Validation Matrix

| Area | Required evidence |
| --- | --- |
| Migration | Upgrade/downgrade tests for desired-only, applied-only, shared, divergent, blocked, active recreation, and Runtime-add receipt shapes |
| Current-state repository | Sequence allocation, idempotent same-target reuse, overwrite cleanup, A-to-B-to-A stale rejection, exact promotion, terminal cleanup |
| Runtime Control | Provider/Runner generation and tuple fencing, opaque field-1 wire continuity, canonical sequence validation, current applied continuity |
| Lifecycle and operations | Create/start/restart/reset/recreate blocking while unconfigured; stop/observe/terminal removal continuity |
| Profile deletion | Owner-only permission, version conflict, cross-Workspace not found, atomic default/selection clearing, count accuracy, rollback behavior |
| API and clients | OpenAPI dump, Python/TypeScript public-client generation, removed revision-model absence |
| Web | Owner affordance, name/impact confirmation, success, stale conflict, Profile-required recovery state |
| E2E | Docker-backed selected/default Profile deletion, running Runtime continuity, Workspace preservation, explicit replacement, stale evidence fencing, terminal cleanup |
| Quality | Affected Python Ruff/format/ty/pytest, protobuf generation checks, TypeScript format/lint/typecheck/build, docs validators, pre-commit |

Required Docker prerequisites fail the E2E lane when absent. Optional live Kubernetes prerequisites retain the existing qualified skip/fail policy.

## Rollout and External Actions

- The schema and Runtime Control authority cutover is one coordinated release boundary; old and new control-plane writers must not run concurrently through the migration.
- Updated Runtime Control, Providers, and Runner are built from the same stack. Existing physical Runtimes may reconnect across the bounded deployment transport interruption.
- No live Kubernetes resource, production database, deployment, restart, or merge action is part of these PRs.
- No permanent feature flag, compatibility mode, fallback, or dual-write period is introduced.

## Ownership, Review, and Context Checkpoints

- Primary implementation owner: `root`.
- Exact independent reviewer for every implementation phase: `hardtack`.
- Reviewer inputs: confirmed Requirements, accepted ADR, approved Design revision 1 and authority table, current Specs, current phase execution plan, stable diff, and focused validation evidence.
- Reviewer criteria: Requirements/Design coverage, security and destructive-operation authority, data-loss and migration correctness, generation/freshness fencing, interface consistency, removal completeness, and unauthorized mechanism absence.
- At every phase boundary, record completed behavior, changed interfaces, validation evidence, remaining scope, affected paths, risks, and blockers in the current phase plan before commit.

## Scope-Drift Rules

- A local implementation detail inside `M1`–`M8` may be planned and implemented without changing Design.
- A user-visible contract or product-scope change returns to Requirements.
- A new material mechanism, fallback, compatibility path, state authority, persistence model, failure behavior, or operational mode returns to Design approval.
- Missing approved behavior or removal work is fixed in the owning phase rather than deferred silently.
- Design delta: None.

## Plan Cleanup

After PR 5/6 has passed required validation and promoted Living Specs, PR 6/6 removes:

- `runtime-profile-deletion-implementation-plan.md`;
- every `runtime-profile-deletion-phase-*.md` execution plan.

The approved Requirements, ADR, Design, current Living Specs, code, tests, and GitHub PR evidence remain the durable record.
