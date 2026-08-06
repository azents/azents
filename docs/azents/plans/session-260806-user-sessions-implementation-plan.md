---
title: "Private User Sessions Implementation Plan"
created: 2026-08-06
updated: 2026-08-06
tags: [session, privacy, memory, frontend, authorization, backend, plan]
---

# Private User Sessions Implementation Plan

## Feature summary

This plan implements approved Private User Sessions for snapshot
[`session-260806`](../requirements/session-260806-user-sessions.md).

Sources of truth:

- Requirements: [`session-260806/REQ`](../requirements/session-260806-user-sessions.md)
- ADR: [`session-260806/ADR`](../adr/session-260806-user-sessions.md)
- Design: [`session-260806/DESIGN`](../design/session-260806-user-sessions.md) revision `1`
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`
- Design delta: `None`

The feature adds root Team/User product mode with associated-User ownership, separate
Team and My Sessions projections, owner-only public boundaries, atomic first-message
User Session admission, Agent + associated User Memory capability projection, and a
durable owner-lifecycle archive/purge path. Existing Team Session behavior remains
unchanged.

## Delivery shape

The work uses a six-PR stack because it crosses persistence constraints, public
authorization, durable lifecycle orchestration, generated clients, web navigation, and
E2E verification.

Stack prefix: `session-260806 user sessions`

| Order | Branch | Base | PR boundary |
| --- | --- | --- | --- |
| 1 | `feature/session-260806-user-sessions-01-foundation` | `main` | Feature docs, this multi-phase plan, root product-mode/associated-user persistence, domain/repo constraints, Team list exclusion |
| 2 | `feature/session-260806-user-sessions-02-backend-surface` | PR 1 branch | Owner authorization, Team/My list APIs, User Session admission, Memory capability resolver, OpenAPI + generated clients |
| 3 | `feature/session-260806-user-sessions-03-owner-lifecycle` | PR 2 branch | Membership-loss archive and account-deletion purge durable owner lifecycle |
| 4 | `feature/session-260806-user-sessions-04-frontend` | PR 3 branch | Team/My Sessions tabs, private draft route, client wiring and pure UI stories |
| 5 | `feature/session-260806-user-sessions-05-validation-specs` | PR 4 branch | E2E matrix, remaining focused tests, living-spec promotion |
| 6 | `feature/session-260806-user-sessions-06-cleanup` | PR 5 branch | Remove this plan and all phase execution plans |

Every implementation PR adds its own phase execution plan under `docs/azents/plans/`
before code changes begin. No later phase starts before the preceding phase PR exists.

## Sources of truth and fixed boundaries

### Requirements trace

| Requirement | Implementation obligation |
| --- | --- |
| `session-260806/REQ-1` | Separate Team and current-user User Session list projections and tabs. |
| `session-260806/REQ-2` | Side-effect-free private draft; atomic first-message User Session admission; no primary; multiple owner sessions. |
| `session-260806/REQ-3` | Owner-only access at every public Session/resource boundary with not-found-safe denials. |
| `session-260806/REQ-4` | User Sessions project Agent Memory plus associated User Memory; Team Sessions remain Agent-only. |
| `session-260806/REQ-5` | Preserve Team primary, Team list/creation, shared access, External Channel routing, and Userless generic execution. |

### ADR trace

| Decision | Behavior |
| --- | --- |
| `session-260806/ADR-D1` | Root product mode Team/User + required associated User for User mode; subagents derive from root; User sessions have null primary. |
| `session-260806/ADR-D2` | Membership loss revokes access immediately and archives; account deletion purges owned User Sessions. |
| `session-260806/ADR-D3` | Durable retryable owner-lifecycle workflow; final User-row deletion only after owned purge completes. |

### Approved mechanisms

| ID | Mechanism | Owning phases |
| --- | --- | --- |
| M1 | Root Team/User product mode with associated User constraints; subagents derive from root | 1, 2 |
| M2 | Separate Team and current-user User Session list projections and tabs | 1 (repo predicates), 2 (API), 4 (UI) |
| M3 | Atomic User Session first-message admission without primary role | 2, 4 |
| M4 | Owner-only authorization at all public Session/resource boundaries | 2 |
| M5 | User-capability resolver for associated User Memory without generic User context | 2 |
| M6 | Existing Team Session behavior retained without routing changes | 1–5 |
| M7 | Durable owner lifecycle for membership-loss archive and account-deletion purge | 3 |
| M8 | Forward migration, deterministic Team backfill, coordinated rollout, E2E-first verification | 1, 5 |

### Removal obligations

| Existing unit or behavior | Owning phase | Replacement |
| --- | --- | --- |
| Single Team-only Session list projection | 1–2, 4 | Separate Team and current-user User projections |
| Team-only root Session classification | 1 | Explicit root mode + associated User |
| Workspace-membership-only authorization for private-capable boundaries | 2 | Mode-aware owner authorization |
| Team-only Memory toolkit projection | 2 | User Session resolver projecting Agent + User Memory |
| Direct User deletion with no Session lifecycle coordination | 3 | Durable owner-lifecycle archive/purge before final User deletion |

### Non-goals

- User Session primary or automatic per-user default Session
- User-brought Tools, personal OAuth, External Channel DM routing to User Sessions
- Filesystem-level Runtime isolation
- Sharing/transfer/delegation of User Sessions
- Changing Team primary, Team External Channel routing, or generic Userless Engine contexts
- Live cluster apply/sync/restart or direct main push

## Ownership and review

| Role | Owner | Responsibility |
| --- | --- | --- |
| Primary implementation and integration | `/root` | Plan, branch stack, cross-phase integration, PR orchestration, CI green |
| Independent reviewer | `hardtack` via `/root/session-260806-reviewer` | Read-only review of each phase contract and diff against REQ/ADR/DESIGN, security/privacy, data-loss, migration, and API correctness |
| Backend workstreams | `/root` or phase assignees | RDB, repos, services, public API, lifecycle, Memory tools |
| Frontend workstream | `/root` or phase assignee | Agent shell/sidebar/draft containers, pure components/stories, generated client consumption |
| Testenv/E2E workstream | `/root` or phase assignee | Deterministic E2E matrix and sanitized evidence |

The primary owner gives every implementation owner the exact reviewer identity and phase
contract. Each owner runs focused checks and requests one read-only review. Required
findings are corrected in one batch. Targeted re-review is limited to
requirements/design, security/data-loss, or material convention/interface corrections.

## Phase 1 — Persistence foundation

### Deliverables

- Track Requirements, ADR, Design, and this multi-phase plan.
- Add PostgreSQL enum-backed root product mode (`team` / `user`) and nullable
  `associated_user_id` on `agent_sessions`.
- Enforce root/subagent and Team/User/associated-user/primary constraints in schema and
  domain mapping.
- Deterministically backfill all existing rows as Team roots/subagents with null
  associated User.
- Restrict the existing Team primary unique index to Team mode.
- Add list index for `(agent_id, associated_user_id, status)`.
- Update repository/domain create/list mappings so Team list queries exclude User mode
  roots and create paths set mode explicitly.
- Repository/migration tests for constraints, backfill, and Team list exclusion.

### Stable interfaces

- `session_kind` remains root/subagent classification.
- `primary_kind` remains Team primary role only.
- Existing Team create/ensure APIs continue to produce Team mode roots.
- No public User Session API surface yet beyond schema readiness if unavoidable; prefer
  keeping external contracts Team-compatible until Phase 2.

### Validation

- Migration upgrade/downgrade or invariant checks on representative fixtures.
- Repository tests for invalid mode/owner/primary combinations.
- Focused Python lint/type/tests for touched modules.
- Docs index regeneration via pre-commit.

## Phase 2 — Backend product surface

### Deliverables

- Mode-aware Session access helper applied to all public Session/resource boundaries.
- Separate Team and current-user My Sessions list service/API projections.
- Atomic `create_user_session_with_buffered_input` path with authenticated associated
  User, null primary, idempotency, and membership race safety.
- Public OpenAPI schema updates and generated Python/TypeScript public clients.
- User-capability Memory resolver projecting Agent + associated User Memory for User
  Sessions only; generic Engine/Run/Worker/Toolkit contexts remain Userless.
- Focused API/service/unit tests for owner-only denial, list predicates, admission, and
  Memory scope.

### Stable interfaces

- Private failures remain not-found-safe and non-disclosing.
- Team routes, Team primary ensure/create, and External Channel routing call sites stay
  on Team paths.
- Associated User ID is not client-selectable and is not exposed to non-owners.

### Validation

- Python quality checks and focused pytest suites.
- OpenAPI dump + client generation drift checks.
- No frontend behavior change required beyond consuming generated types if already
  compiled.

## Phase 3 — Owner lifecycle

### Deliverables

- Durable owner-lifecycle operation/repository/worker integration.
- Membership deletion: immediate access revocation + enqueue archive of owned User
  Sessions after safe stop; reuse existing archive participant path.
- User deletion: mark account unavailable first; enqueue purge of owned User Sessions;
  delete User row and private User Memory only after purge success.
- Retry/observability status without private transcript exposure.
- Lifecycle unit/integration tests for race, retry, and delayed final deletion.

### Stable interfaces

- Reuse `SessionLifecycleOrchestrator`, archived purge finalizer, and participant
  cleanup rather than cascading deletes.
- HTTP membership/user delete paths do not synchronously wait for Runtime/object-store
  cleanup.

### Validation

- Focused lifecycle tests with active-run stop and retry paths.
- Proof that Team Sessions and Agent Memory are not purged by User owner lifecycle.

## Phase 4 — Frontend

### Deliverables

- Team / My Sessions tabs in Agent focused shell/sidebar with local or route tab state.
- My Sessions create action opens private draft with no pre-create DB row.
- First-message success navigates to concrete User Session route.
- Separate query invalidation for Team vs User lists.
- Pure UI stories for tab empty/loading/populated and draft states.
- Korean locale strings where product UI already localizes labels.

### Stable interfaces

- Existing Team draft/create/list flows remain default Team behavior.
- No primary badge or auto-select for User Sessions.

### Validation

- TypeScript format/lint/typecheck.
- Component/story checks as applicable.

## Phase 5 — Validation and specs

### Deliverables

- E2E matrix from Design §12 covering dual User Sessions, cross-member denial, Team
  unchanged, Memory scopes, draft non-create, membership archive, and account purge.
- Remaining unit/integration gaps closed.
- Living specs updated for conversation/session, memory, user-auth/workspace membership
  deletion behavior, and code_paths/`last_verified_at`.
- Mark Requirements/Design `implemented` only after verified completion evidence.

### Validation

- Deterministic E2E plus focused backend/frontend checks.
- Spec-review against the final stack diff.
- CI green across the stacked PRs.

## Phase 6 — Cleanup

### Deliverables

- Remove this multi-phase plan and all `session-260806-user-sessions-phase-*.md`
  execution plans.
- No product behavior change.

## Data, API, runtime, and rollout notes

- Forward Alembic migration only under `python/apps/azents/db-schemas/rdb/`; update
  `db-schemas/rdb/revision`.
- Generate migrations with `alembic revision`; never hand-author a full migration file
  from scratch.
- Regenerate public clients after OpenAPI changes; never hand-edit generated packages.
- Runtime remains shared; do not claim filesystem privacy.
- Coordinated app/schema cutover: migrate and deploy backend defaults before enabling
  User creation UX; rollback uses pre-cutover backup and previous images.

## Context checkpoints

After each phase PR opens, record:

- completed behavior and changed interfaces;
- validation evidence;
- remaining scope and risks;
- exact reviewer outcome.

## Plan cleanup

Phase 6 removes all temporary plans for this feature after validation and spec
promotion.

Design delta: `None`
