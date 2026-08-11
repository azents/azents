---
title: "Runtime Profile Deletion Phase 2 Hard Delete"
created: 2026-08-11
updated: 2026-08-11
tags: [runtime, profile, deletion, permission, api]
---
## Phase Execution Plan

- Phase: `2 - Workspace Runtime Profile hard delete`
- Branch/base: `feature/runtime-profile-hard-delete` → `feature/runtime-configuration-current-state`
- PR boundary: Add owner-only permanent Workspace Runtime Profile deletion with one atomic transaction across default and Agent selection clearing, managed Runtime unconfiguration, recreation supersession, Profile deletion, bounded impact reporting, OpenAPI, and official public clients.
- Inputs: Confirmed `profile-260811/REQ`, accepted `profile-260811/ADR`, approved `profile-260811/DESIGN` revision 1, baseline PR #1258, and current-state cutover PR #1259.
- Deliverables:
  - `RUNTIME_PROFILES_DELETE` permission granted only to Workspace Owners;
  - exact `DELETE /runtime-profile/v1/workspaces/{handle}/profiles/{profile_id}` API with required `expected_version` and bounded result counts;
  - one PostgreSQL transaction that locks and deletes the Profile, clears matching Workspace default and Agent selections, advances versions, overwrites affected managed Runtime desired state to `unconfigured/runtime_profile_required`, and supersedes active Profile-targeted recreation;
  - retained applied configuration, Provider binding, lifecycle stop/observe/terminal-removal authority, and Agent Workspace storage for running Runtimes;
  - generated Python and TypeScript public clients for the delete contract.
- Non-goals: Web delete affordance or confirmation UX, E2E coverage, fallback Profile selection, Profile tombstone/archive, applied-state deletion, Runtime restart/recreation on delete, Living Spec promotion, deployment, or compatibility behavior.
- Interfaces:
  - only Workspace Owners receive `Permissions.RUNTIME_PROFILES_DELETE`;
  - request path owns Workspace/Profile identity and request body owns `expected_version >= 1`;
  - not-found and cross-Workspace identifiers both return `runtime_profile_not_found`; stale version returns `runtime_profile_version_conflict`;
  - response fields are `profile_id`, `cleared_workspace_default`, `cleared_agent_count`, `affected_running_runtime_count`, and `superseded_recreation_operation_count`;
  - each affected managed Runtime allocates the next configuration sequence and overwrites desired state as unconfigured while retaining applied state and Runtime binding.
- Approved Design mechanisms: `M1`, `M4`, `M5`, `M6`, `M8`
- Authority references: `profile-260811/REQ-1`, `REQ-2`, `REQ-4`, `REQ-6`, `REQ-7`; `profile-260811/ADR-D1`, `ADR-D3`, `ADR-D4`, `ADR-D5`, `ADR-D6`; `profile-260811/DESIGN` Runtime Profile Hard Delete, Runtime behavior after deletion, Reconciliation and Recreation, Failure/Retry/Recovery, API/Generated Clients/UI, Observability, Security and Privacy; current Agent, Workspace, Runtime Control, and Runtime Persistence Specs.
- Design delta: `None`
- Removal obligations:
  - remove Workspace/Agent foreign-key behavior that prevents Profile deletion while preserving scalar snapshot evidence in current configuration state;
  - provide no archive, tombstone, fallback selection, or soft-delete substitute;
  - ensure active recreation no longer depends on the deleted Profile row and Profile-targeted work is superseded as `target_deleted`.
- Absence verification: Schema and ORM inspection for blocking Profile foreign keys; active-source search for fallback/tombstone/archive delete paths; API/OpenAPI/client inspection for one hard-delete contract; transaction tests proving no residual default or Agent selection references.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Permission and role authority | `root` | `python/apps/azents/src/azents/core/auth/permissions.py`, `core/auth/roles.py`, permission tests | Existing Workspace membership resolution | Owner-only delete permission with unchanged read/write grants | Role/permission unit tests and route permission tests |
| Atomic deletion repository/service | `root` | `python/apps/azents/src/azents/repos/runtime_profile/`, Workspace/Agent repository helpers, `services/runtime_profile_workspace/` | Current-state sequence and desired/applied repository API | Locked exact-version deletion transaction, default/selection clearing, Runtime unconfiguration, recreation supersession, bounded result | Repository/service integration tests for success, counts, rollback, stale/not-found/cross-Workspace, running Runtime continuity |
| Recreation and reconciliation contraction | `root` | Runtime Profile recreation operation repository/service paths and focused tests | Atomic Profile target lock and current-state tuple | Active Profile-targeted operations superseded, undispatched items terminalized `target_deleted`, stale source work remains harmless | Pending/running/dispatched operation integration tests |
| Public API and errors | `root` | `python/apps/azents/src/azents/api/public/runtime_profile/v1/` and route tests | Service result/error contract and delete permission | DELETE route, request/response models, bounded error mapping | Route permission/error/model tests and OpenAPI dump |
| Generated clients | `root` | checked-in OpenAPI and official Python/TypeScript public-client generated artifacts | Stable public API schema | Generated delete operation and response/request types | Source generation, format, typecheck, build/import checks |
| Observability and absence | `root` | deletion service structured logging and phase tests/searches | Committed transaction result | One bounded deletion log with identifiers, actor, version, and counts; no policy documents or credentials | Log assertion where practical, payload inspection, active-source absence search |

- Integration order: Lock down permission and result/error contracts → add exact repository primitives for default/selection clearing, Runtime unconfiguration, recreation supersession, and Profile deletion → compose one service transaction → add public route/models/error mapping → regenerate OpenAPI and clients → run transaction and continuity tests → verify removal/absence obligations.
- Independent review: `hardtack` reviews the stable Phase 2 diff read-only against confirmed Requirements, accepted ADR, approved Design revision 1, current Specs, PR #1259 current-state interfaces, and this plan. Criteria are owner-only destructive authority, cross-Workspace non-disclosure, optimistic version fencing, one-transaction rollback, count accuracy, applied/Workspace continuity, recreation terminalization, audit/log privacy, generated-contract correctness, and absence of fallback/tombstone/archive mechanisms. Output is one consolidated review with required findings separated from optional polish.
- Final validation:
  - affected backend Ruff, format, `ty check --error-on-warning`, permission/role tests, repository/service integration tests, route tests, migration/schema checks, and focused Runtime lifecycle/operation continuity tests;
  - OpenAPI dump plus official Python and TypeScript public-client regeneration, format, typecheck, and build/import checks;
  - active-source and schema absence searches, `git diff --check`, and all pre-commit hooks on the stable diff.
- Scope-drift check: Confirm complete `M1`, `M4`, `M5`, `M6`, and `M8` coverage; confirm the diff adds no Web UX, E2E, fallback Profile, archive/tombstone, applied-state cleanup, automatic restart/recreation, compatibility mode, deployment action, or new material mechanism.
- Context checkpoint: PR #1259 provides bounded current desired/applied state, exact sequence fencing, terminal cleanup, and revision-free status contracts. This phase consumes those interfaces to delete one mutable Workspace Profile without deleting the current applied Runtime snapshot or physical Workspace. Remaining phases own Web/E2E, final validation and Living Spec promotion, and plan cleanup. Main risks are destructive authorization, transaction completeness, concurrent selection/deletion serialization, recreation terminalization, and foreign-key contraction; no material Design blocker is known.

## Execution Checkpoint

- Completed behavior: Workspace Owners have a distinct delete permission and Public DELETE contract. One repository transaction locks the Workspace and exact-version Profile, clears matching default and Agent selections with version advancement, overwrites affected managed Runtime desired state as `unconfigured/runtime_profile_required`, retains current applied state and Provider binding, terminalizes active Profile-targeted recreation items as `target_deleted`, and physically deletes the Profile row.
- Changed interfaces: Added `WorkspaceRuntimeProfileDeleteRequest`, `WorkspaceRuntimeProfileDeleteResponse`, the generated `runtime_profile_v1_delete_workspace_runtime_profile` Python/TypeScript client operation, and bounded service/repository deletion outcomes. Not-found/cross-Workspace identifiers remain undisclosed as `runtime_profile_not_found`; stale versions return current-version evidence.
- Validation evidence:
  - affected backend Ruff, format, and `ty check --error-on-warning`: passed;
  - permission, route, service, repository, Runtime lifecycle, Profile resolution, and recreation continuity tests: `72 passed`;
  - focused deletion suite: `20 passed`;
  - Python public client generation, wheel/sdist build, model import, and delete-operation import: passed;
  - TypeScript public client generation, Prettier check, typecheck, and build: passed;
  - active-code revision-authority absence, delete fallback/tombstone/archive absence, and `git diff --check`: passed.
- Defects corrected during validation: managed-Agent fixture constraint alignment; `RDBAgentRuntime` `init=False` fixture field assignment; non-frozen service exception required for Python 3.14 async-context traceback propagation; explicit service current-version and rollback-path tests.
- Removal and continuity evidence: No active Runtime configuration revision symbols remain outside historical migrations/tests; no fallback, tombstone, archive, or soft-delete mechanism was added. Repository integration proves the Profile/default/selections are absent while the running Runtime binding, applied document, and recreation terminal evidence remain.
- Authority and drift result: `M1`, `M4`, `M5`, `M6`, and `M8` are covered. Design delta: `None`.
- Remaining phase work: commit and open PR 3/6 against `feature/runtime-configuration-current-state`, request the assigned `hardtack` review, address required findings, and monitor CI after the complete planned stack is open.
