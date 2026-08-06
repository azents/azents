---
title: "session-260806 Phase 1 Foundation Execution Plan"
created: 2026-08-06
updated: 2026-08-06
tags: [session, privacy, backend, plan]
---

# session-260806 Phase 1 Foundation Execution Plan

## Phase Execution Plan

- Phase: `1 — Persistence foundation`
- Branch/base: `feature/session-260806-user-sessions-01-foundation` → `main`
- PR boundary: Feature docs, multi-phase plan, root product-mode/associated-user persistence, domain/repo constraints, Team list exclusion
- Inputs: Approved `session-260806/REQ`, `session-260806/ADR`, `session-260806/DESIGN` revision `1` (`M1–M8`)
- Deliverables:
  - Tracked Requirements/ADR/Design and multi-phase implementation plan
  - Root product mode enum (`team`/`user`) and `associated_user_id` on `agent_sessions`
  - Schema/domain constraints for root/subagent and Team/User/primary combinations
  - Deterministic Team backfill for existing rows
  - Team list/repository queries exclude User mode roots
  - Focused migration/repository tests
- Non-goals:
  - Public My Sessions API, User admission endpoint, owner-auth sweep
  - Memory capability resolver changes
  - Owner lifecycle archive/purge
  - Frontend tabs/draft
  - Spec promotion
- Interfaces:
  - `session_kind` remains root/subagent
  - `primary_kind` remains Team primary only; User roots always null primary
  - Existing Team create/ensure paths write Team mode + null associated user
  - Repository list helpers used by Team surfaces exclude `product_mode = user`
- Approved Design mechanisms: `M1`, `M2` (repo predicates only), `M6`, `M8`
- Authority references: `session-260806/REQ-1`, `REQ-2`, `REQ-5`; `session-260806/ADR-D1`; Design §§4,8,13,14
- Design delta: `None`
- Removal obligations:
  - Team-only root classification without explicit product mode
  - Team list projections that would include future User roots once mode exists
- Absence verification:
  - Migration/backfill tests prove existing rows are Team with null associated user
  - Team list repository tests prove User roots are excluded
  - Invalid mode/owner/primary combinations rejected by constraints or domain mapping tests

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Feature docs + plans | `/root` | `docs/azents/requirements/session-260806-user-sessions.md`, `docs/azents/adr/session-260806-user-sessions.md`, `docs/azents/design/session-260806-user-sessions.md`, `docs/azents/plans/session-260806-user-sessions-implementation-plan.md`, `docs/azents/plans/session-260806-user-sessions-phase-1-foundation.md` | Approved design | Tracked authority + plans | docs frontmatter/index via pre-commit |
| Enums + RDB model | `/root` | `python/apps/azents/src/azents/core/enums.py`, `python/apps/azents/src/azents/rdb/models/agent_session.py` | docs | product mode enum + columns/constraints/indexes | model import + unit mapping tests |
| Migration | `/root` | `python/apps/azents/db-schemas/rdb/migrations/versions/*`, `python/apps/azents/db-schemas/rdb/revision` | model | forward migration + Team backfill + revision pin | migration upgrade path / invariant tests |
| Domain + repository | `/root` | `python/apps/azents/src/azents/repos/agent_session/**`, related domain data types under repos/services used by create/list | model | create/list map mode + associated user; Team lists exclude User mode; Team create sets Team defaults | repository tests |
| Focused tests | `/root` | matching `*_test.py` beside changed modules | domain/repo | constraint and list exclusion coverage | `uv run pytest` focused |

- Integration order: docs/plans → enums/model → alembic revision → domain/repo create+list → tests → commit/PR
- Independent review: `hardtack` via `/root/session-260806-reviewer`; read-only against REQ/ADR/DESIGN, migration safety, constraint completeness, Team-behavior preservation; inputs are phase plan + diff; output is accept/request-changes with required findings only
- Final validation:
  - `cd python/apps/azents && uv run ruff check --fix . && uv run ruff format . && uv run ty check --error-on-warning`
  - focused `uv run pytest` for agent_session repo/model/migration tests
  - `git diff --check`
  - docs index via pre-commit on commit
- Scope-drift check: covers M1/M8 and Team-list half of M2 only; no API/Memory/lifecycle/frontend/spec expansion; no new product behavior beyond persistence readiness
- Context checkpoint:
  - Completed: tracked REQ/ADR/DESIGN/plans; `AgentSessionProductMode`; root
    `product_mode` + `associated_user_id` columns/constraints/indexes; Team
    backfill migration `2a9ad984951f`; domain/repo create+list predicates; Team
    list exclusion and owner User list helper; focused repo + migration tests.
  - Changed interfaces: `AgentSession`/`AgentSessionCreate` require product mode
    and associated user fields; Team list helpers return Team mode only.
  - Evidence: `repository_test.py` 29 passed; product-mode migration test +
    root creation tests passed; ruff/ty clean on touched modules.
  - Remaining: Phase 2 public auth/list/admission/Memory/OpenAPI.
  - Risks: API responses still omit product mode until Phase 2; all Team create
    call sites updated to explicit Team mode.

Design delta: `None`
