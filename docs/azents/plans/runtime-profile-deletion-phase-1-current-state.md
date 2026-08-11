---
title: "Runtime Profile Deletion Phase 1 Current State Cutover"
created: 2026-08-11
updated: 2026-08-11
tags: [runtime, persistence, protocol, migration, backend]
---
## Phase Execution Plan

- Phase: `1 - Runtime configuration current-state cutover`
- Branch/base: `feature/runtime-configuration-current-state` → `design/runtime-profile-hard-delete-current-state`
- PR boundary: Replace immutable Runtime configuration revisions with bounded current desired/applied state and exact configuration-sequence fencing across persistence, backend, Runtime Control, Providers, Runner, receipts, recreation, operations, and status contracts.
- Inputs: Confirmed `profile-260811/REQ`, accepted `profile-260811/ADR`, approved `profile-260811/DESIGN` revision 1, and merged process-containment removal PR #1257.
- Deliverables:
  - one monotonic Runtime-owned configuration sequence and one desired/applied current-state row per Runtime;
  - exact sequence/digest/desired-generation/connection-generation fencing;
  - converted Runtime-add receipt, recreation-item, lifecycle, operation, Provider, and Runner authority;
  - forward migration of current authority only and deletion of all superseded revision data;
  - revision-free current Runtime status contracts and focused cutover tests.
- Non-goals: Workspace Runtime Profile delete permission/route/transaction, Web deletion UX, final Living Spec promotion, live deployment, fallback Profiles, tombstones, historical configuration retention, dual writes, or mixed protocol serving.
- Interfaces:
  - `agent_runtimes.configuration_sequence` is the monotonic high-water mark;
  - `runtime_configuration_states` owns one desired slot and one applied slot;
  - exact evidence is Runtime ID + desired generation + configuration sequence + digest + current Provider or Runner generation;
  - Runtime Control protobuf field 1 remains a string at the existing wire number and carries a canonical positive decimal sequence;
  - existing public Runtime status surfaces replace revision fields with bounded current-state sequence/status fields.
- Approved Design mechanisms: `M2`, `M3`, `M4`, `M6`, `M7`
- Authority references: `profile-260811/REQ-3..6`; `profile-260811/ADR-D1`, `ADR-D2`, `ADR-D4`, `ADR-D6`; `profile-260811/DESIGN` Data Model, Configuration State Transitions, Protocol and Operation Authority, Migration, Rollout, Removal and Replacement; current Agent Runtime Control and Persistence Specs.
- Design delta: `None`
- Removal obligations:
  - remove the `runtime_configuration_revisions` table, ORM/domain models, repositories, and tests whose only authority is revision history;
  - remove Agent Runtime desired/applied revision pointers and duplicate desired Profile/infrastructure columns;
  - replace revision creation, clone, acknowledgement, comparison, and promotion with current-state CAS operations;
  - replace recreation-item and Runtime-add receipt revision foreign keys with sequence/digest/desired-generation scalars;
  - replace active protobuf, shared-client, Provider, Runner, operation, API-status, and test revision terminology;
  - delete superseded historical configuration rows during migration.
- Absence verification: New-schema introspection; migration assertions; active-source search excluding immutable historical docs/migrations; generated protobuf/OpenAPI inspection; no active `RuntimeConfigurationRevision`, `runtime_configuration_revisions`, desired/applied revision pointer, expected revision FK, or Runtime status revision label.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Schema and domain state | `root` | `python/apps/azents/db-schemas/rdb/migrations/versions/`, `python/apps/azents/src/azents/rdb/models/agent_runtime.py`, Runtime configuration domain/data modules | Approved state envelope and migration contract | Current-state table, sequence high-water mark, converted receipts/items, destructive revision contraction | Alembic upgrade/downgrade tests, model/schema tests |
| Repository and resolution CAS | `root` | `python/apps/azents/src/azents/repos/agent_runtime/`, `repos/runtime_profile/`, `services/runtime_profile_resolution/`, `services/runtime_profile_reconciliation/` | Schema/domain state | Desired overwrite, idempotent exact-target reuse, applied promotion, terminal cleanup, source/generation fencing | Focused repository/resolution/reconciliation pytest |
| Lifecycle, recreation, and operation authority | `root` | `python/apps/azents/src/azents/services/agent_runtime/`, `services/runtime_recreation/`, `runtime/`, operation-target consumers, Runtime-add receipt paths | Repository current-state API | Sequence-fenced lifecycle retargeting, recreation/receipt evidence, current operation qualification | Focused lifecycle/recreation/operation pytest |
| Runtime Control protocol and sinks | `root` | `proto/azents/runtime_control/v1/`, `python/libs/azents-runtime-control/`, `python/apps/azents/src/azents/runtime/control_protocol/` | Current-state tuple contract | Sequence-named wire/generated contract, canonical parsing, Provider/Runner acknowledgement and promotion | Proto generation, runtime-control library tests, sink/reconciler tests |
| Provider and Runner adoption | `root` | `python/apps/azents-runtime-provider-docker/`, `python/apps/azents-runtime-provider-kubernetes/`, `python/apps/azents-runtime-runner/` | Generated Runtime Control contract | Providers and Runner echo and validate current configuration sequence without revision aliases | Affected provider/runner Ruff, ty, pytest |
| Status/OpenAPI contract | `root` | `python/apps/azents/src/azents/api/public/agent_runtime/`, shared response/data modules, checked-in OpenAPI inputs | Repository current-state projection | Revision-free desired/applied current status consumed by later client/Web phase | Route/model tests, OpenAPI dump and schema search |
| Cutover fixtures and regression coverage | `root` | Affected backend/runtime-control/provider/runner tests and migration fixtures | All workstreams | Desired-only, applied-only, shared/divergent, blocked, active-recreation, receipt, stale-evidence, and terminal-cleanup evidence | Focused suites plus stable-diff integration checks |

- Integration order: Define canonical state envelope and sequence type → add migration/model → replace repository authority → replace lifecycle/recreation/operation consumers → cut protobuf and generated Runtime Control modules → update sinks/Providers/Runner → replace status models → run migration and focused integration tests → verify active revision absence.
- Independent review: `hardtack` reviews the stable Phase 1 diff read-only against `profile-260811/REQ`, `profile-260811/ADR`, approved `profile-260811/DESIGN` revision 1, current Runtime Control/Persistence Specs, and this phase plan. Criteria are migration safety, bounded state, A-to-B-to-A freshness, Provider/Runner generation fencing, running applied-state continuity, protocol wire correctness, removal completeness, and absence of compatibility or historical-state mechanisms. Output is one consolidated review with required findings separated from optional polish.
- Final validation:
  - affected `python/apps/azents` Ruff, format, `ty check --error-on-warning`, migration tests, and focused repository/service/runtime-control pytest suites;
  - affected Runtime Control library, Docker Provider, Kubernetes Provider, and Runner Ruff, format, ty, and pytest suites;
  - protobuf generation and checked-in generated-file cleanliness;
  - OpenAPI dump/model tests for current-state status;
  - repository active-source absence search and `git diff --check`;
  - pre-commit on the stable committed diff.
- Scope-drift check: Confirm complete `M2`, `M3`, `M4`, `M6`, and `M7` coverage; confirm no Profile delete endpoint or Web UX enters this PR; confirm no new historical state, fallback, alias, dual-write, mixed-protocol, credential, or deployment mechanism is added.
- Context checkpoint: Approved documentation and delivery plan are complete. Phase 1 begins from revision-based persistence and must end with current-state authority across the coordinated backend/protocol/runtime boundary. Later phases own destructive Profile authority, Web/E2E, final Spec promotion, and plan cleanup. Main risk is destructive migration and wide generated-contract cutover; no material Design blocker is known.
