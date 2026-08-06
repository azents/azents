---
title: "session-260806 Phase 5 Validation and Specs Execution Plan"
created: 2026-08-06
updated: 2026-08-06
tags: [session, privacy, e2e, spec, plan]
---

# session-260806 Phase 5 Validation and Specs Execution Plan

## Phase Execution Plan

- Phase: `5 — Validation and specs`
- Branch/base: `feature/session-260806-user-sessions-05-validation-specs` → `feature/session-260806-user-sessions-04-frontend`
- PR boundary: Deterministic E2E matrix coverage, living-spec promotion, remaining focused validation docs
- Inputs: Phases 1–4 backend/frontend surfaces; Design §12 matrix
- Deliverables:
  - Public deterministic E2E covering dual User Sessions, cross-member denial, Team exclusion, User first-message admission
  - Living specs for conversation, memory, and owner/access deletion behavior
  - Spec history/version/`last_verified_at` updates
- Non-goals:
  - Plan cleanup (Phase 6)
  - Frontend Storybook-only regressions already covered in Phase 4
  - Design delta
- Interfaces: Existing public User Session list/admission endpoints and owner-auth boundaries
- Approved Design mechanisms: `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8` (validation/promotion)
- Authority references: Design §12; `session-260806/REQ-1`–`REQ-5`
- Design delta: `None`
- Removal obligations: Living-spec statements that claim all Sessions are Team-only and that public boundaries authorize only Workspace membership
- Absence verification: Spec no longer claims Team-only product mode; E2E asserts User sessions absent from Team list and denied to non-owners

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| E2E matrix | `/root` | `testenv/azents/e2e/src/tests/azents/public/test_user_sessions.py` | Phase 2 APIs | deterministic cases | pytest in CI |
| Specs | `/root` | `docs/azents/spec/domain/{conversation,memory,user-auth}.md` | E2E/code | living behavior | pre-commit index |

- Integration order: E2E → specs → checks → PR
- Independent review: `hardtack`
- Final validation: focused E2E collection import/static checks where full stack unavailable locally; CI deterministic E2E
- Scope-drift check: no frontend product change, no plan cleanup
- Context checkpoint:
  - E2E: `test_user_sessions.py` covers dual User Sessions, Team-list exclusion, cross-member 404 denial, Team first-message control
  - Specs: conversation v141, memory v7, user-auth v9
  - Implemented frontmatter deferred until stacked CI verifies E2E evidence

Design delta: `None`
