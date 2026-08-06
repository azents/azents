---
title: "session-260806 Phase 3 Owner Lifecycle Execution Plan"
created: 2026-08-06
updated: 2026-08-06
tags: [session, privacy, lifecycle, plan]
---

# session-260806 Phase 3 Owner Lifecycle Execution Plan

## Phase Execution Plan

- Phase: `3 — Owner lifecycle`
- Branch/base: `feature/session-260806-user-sessions-03-owner-lifecycle` → `feature/session-260806-user-sessions-02-backend-surface`
- PR boundary: Durable membership-loss archive and account-deletion purge coordinator with delayed User-row deletion
- Inputs: Phase 1 product mode/associated User; Phase 2 owner authorization and My Sessions surfaces
- Deliverables:
  - Durable `owner_lifecycle_jobs` persistence + repository claim/retry APIs
  - User `access_disabled_at` account-unavailable marker + auth rejection/revocation
  - Membership deletion enqueues workspace-scoped archive lifecycle immediately after membership removal
  - User deletion disables access immediately, enqueues account purge, and deletes User row only after owned User Session purge + private User Memory cleanup
  - Scheduler worker reusing SessionLifecycleOrchestrator archive and existing purge scheduling
  - Focused lifecycle unit tests
- Non-goals:
  - Frontend tabs/draft UX (Phase 4)
  - Full E2E matrix and living-spec promotion (Phase 5)
  - Changing Team Session, Agent Memory, or External Channel primary routing behavior
- Interfaces:
  - HTTP membership/user delete paths do not await Runtime/object-store cleanup
  - Private transcript content is never written into lifecycle error summaries
  - Team Sessions and Agent-scope Memory are out of owner purge scope
  - Membership archive reuses normal retention; account purge schedules immediate eligibility
- Approved Design mechanisms: `M7`
- Authority references: `session-260806/REQ-5`; `ADR-D2`; `ADR-D3`; Design §§7–8,12–14
- Design delta: `None`
- Removal obligations:
  - Direct User-row deletion without Session lifecycle coordination
  - Membership deletion that drops ownership without enqueueing archive lifecycle for owned User Sessions
- Absence verification:
  - UserService.delete leaves the User row until purge finalization
  - WorkspaceUser delete creates/reuses an owner-lifecycle job for `(workspace_id, user_id)`
  - Coordinator tests prove Team roots are not archived/purged by owner lifecycle

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Schema/enums | `/root` | `core/enums.py`, `rdb/models/user.py`, `rdb/models/owner_lifecycle.py`, alembic migration, `db-schemas/rdb/revision` | Phase 2 base | durable job + access_disabled_at | migration upgrade |
| Repos | `/root` | `repos/owner_lifecycle/**`, agent_session list helpers, memory delete-by-user, user disable helpers | schema | claim/create APIs | repo/unit tests |
| Coordinator | `/root` | `services/owner_lifecycle.py`, scheduler registry | repos | archive/purge worker | service tests |
| Delete integration | `/root` | `services/user/**`, `services/workspace_user/**`, `services/auth/**` | coordinator enqueue | delayed delete + auth deny | service tests |
| Tests | `/root` | matching `*_test.py` | above | focused coverage | pytest |

- Integration order: schema → repos → coordinator → delete/auth integration → scheduler → tests → PR
- Independent review: `hardtack` via PR review; criteria = ADR-D2/D3 fidelity, no sync external cleanup, Team isolation, delayed User deletion, not-found-safe public behavior preserved
- Final validation: focused pytest on owner lifecycle + user/workspace delete paths; ruff/ty on touched modules
- Scope-drift check: no frontend/spec promotion; no Design delta
- Context checkpoint:
  - Completed: durable owner_lifecycle_jobs + access_disabled_at migration;
    membership delete enqueues archive; user delete disables access/revokes
    sessions/system roles and enqueues account purge; scheduler worker archives
    via SessionLifecycleOrchestrator and finalizes User/Memory after purge;
    focused coordinator + system-admin delete tests pass.
  - Changed interfaces: UserService.delete is async-lifecycle (row retained);
    WorkspaceUser delete enqueues membership archive; auth login/refresh reject
    disabled accounts; scheduler task `owner_lifecycle`.
  - Evidence: owner_lifecycle_test 5 passed; system_user_role service tests
    updated and passed; ruff/ty clean on touched modules.
  - Remaining later phases: frontend, E2E/spec, plan cleanup.
  - Risks: short-lived JWT access tokens may remain valid until expiry after
    revoke; mitigated by refresh rejection + session revoke + access_disabled_at.

Design delta: `None`
