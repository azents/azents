---
title: "session-260806 Phase 2 Backend Surface Execution Plan"
created: 2026-08-06
updated: 2026-08-06
tags: [session, privacy, backend, api, memory, plan]
---

# session-260806 Phase 2 Backend Surface Execution Plan

## Phase Execution Plan

- Phase: `2 — Backend product surface`
- Branch/base: `feature/session-260806-user-sessions-02-backend-surface` → `feature/session-260806-user-sessions-01-foundation`
- PR boundary: Owner authorization, Team/My list APIs, User Session admission, Memory capability resolver, OpenAPI + generated clients
- Inputs: Phase 1 foundation merged into base branch (`product_mode`, `associated_user_id`, Team list predicates)
- Deliverables:
  - Mode-aware public Session access helper with not-found-safe denials
  - Separate Team and current-user My Sessions list service/API projections
  - Atomic User Session first-message admission path
  - User Memory capability projection for User Sessions only
  - OpenAPI dump + generated Python/TypeScript public clients
  - Focused API/service/unit tests
- Non-goals:
  - Owner lifecycle archive/purge (Phase 3)
  - Frontend tabs/draft UX (Phase 4)
  - Living-spec promotion and full E2E matrix (Phase 5)
- Interfaces:
  - Private failures remain not-found-safe
  - Team create/list/primary/External Channel paths remain Team-only
  - Associated User is not client-selectable
  - Generic Engine/Run/Worker/Toolkit contexts remain Userless
- Approved Design mechanisms: `M2` (API), `M3`, `M4`, `M5`, `M6`
- Authority references: `session-260806/REQ-1`–`REQ-5`; `ADR-D1`; Design §§5–6,12–14
- Design delta: `None`
- Removal obligations:
  - Workspace-membership-only authorization on private-capable boundaries
  - Single Team-only list API surface for Agent sessions
  - Team-only Memory toolkit projection for User Session execution
- Absence verification:
  - Cross-member service/API tests prove non-owner access is denied without private metadata
  - Team list endpoints never return User roots
  - Team Memory tools still reject User scope; User Sessions bind associated User only

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Access helper | `/root` | `python/apps/azents/src/azents/services/chat/**`, resource authority call sites | Phase 1 | mode-aware authorize | service/API tests |
| List + admission APIs | `/root` | `services/agent_session_input.py`, `api/public/chat/v1/**` | access helper | My Sessions list + user first-message | API tests |
| Memory resolver | `/root` | `engine/tools/builtin.py`, `engine/tools/memory.py`, resolve path | Phase 1 domain fields | Agent+User Memory projection | unit tests |
| OpenAPI/clients | `/root` | `specs/public/openapi.json`, generated public clients | API models | regenerated clients | dump/generate checks |
| Tests | `/root` | matching `*_test.py` | above | focused coverage | pytest |

- Integration order: access helper → list/admission → Memory → OpenAPI/clients → tests → PR
- Independent review: `hardtack` via `/root/session-260806-reviewer`; privacy/authorization completeness, Team preservation, Memory isolation, API contract
- Final validation: focused pytest; ruff/ty; OpenAPI dump; public client generate
- Scope-drift check: no lifecycle/frontend/spec promotion beyond required temporary docs
- Context checkpoint:
  - Completed: mode-aware `_authorize_public_session` on core chat access paths;
    My Sessions list service/API; User first-message admission service/API;
    Memory tools accept associated-user dual scope; OpenAPI + public clients
    regenerated.
  - Changed interfaces: `GET /agents/{id}/user-sessions`,
    `POST /agents/{id}/user-sessions/messages`; Memory tools allow user scope
    only when root User Session associated user is present.
  - Evidence: memory tool tests 23 passed; openapi dump + client generate;
    ruff/ty on touched modules.
  - Remaining later phases: full owner-auth sweep on every resource boundary,
    lifecycle, frontend, E2E/spec.
  - Risks: some chat/resource paths may still use membership-only checks and
    need follow-up hardening in this phase if CI/review finds gaps.

Design delta: `None`
