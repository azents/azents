---
title: "GitHub User Account Toolkit Implementation Plan"
created: 2026-10-08
tags: [github, toolkit, backend, frontend, testenv]
---

# GitHub User Account Toolkit Implementation Plan

- Authority: [Requirements](../requirements/github-261008-user-account-toolkit.md), [ADR](../adr/github-261008-user-account-toolkit.md), [approved Design](../design/github-261008-user-account-toolkit.md).
- Approved revision: 3; mechanisms M1-M11.
- Design delta: None.
- Lead/integration/validation owner: `/root`.
- Single independent read-only reviewer for every stable integrated phase: `/root/github-user-reviewer`.
- Approved research baseline: `279db5f1fb52c634570d3d5eff6a669d2becdfd3`.
- Current integration baseline: main `e9f8ff0276df8e513703bbbba1851f37987edbe4`; preserved current main's removal of obsolete Toolkit visibility scopes without changing shared/Agent ownership or Design mechanisms.

## Reviewable Stack

1. **Backend authorization and cleanup contracts** (`feat/github-user-261008-backend` -> main): new user discriminators, public SDK ingress/exchange/identity/discovery/revocation, encrypted attempt/connection/retired-token persistence, ownership-gated Workspace/Agent routes, redacted summaries/availability, migration and backend tests. M1-M5, M7, M9-M11; backend half of M3/M8. Existing modes retain behavior.
2. **Current UI and generated client integration** (`feat/github-user-261008-ui` -> phase 1): generated Public clients, existing catalog/form/details/callback integration, account/sharing confirmation, partial readiness, cleanup failures/retry, availability and locale/component evidence. M1, M3-M5, M7-M9, M11. No UI redesign or PAT default change.
3. **Execution, product verification and Spec promotion** (`feat/github-user-261008-execution` -> phase 2): current-row MCP/live-and-snapshot handlers and opt-in Runtime environment; deterministic setup-to-Worker E2E, existing-mode regressions, Living Specs and approved removal verification. M6, M10 and complete M1-M11 coverage. Record implemented dates only after verified completion; remove temporary plans in this phase.

Open each phase PR before starting the next phase. Create the full planned stack before waiting on CI; inspect/fix CI for every PR. Do not merge or deploy.

## Owners and Interfaces

| Workstream | Owner | Boundary |
| --- | --- | --- |
| Provider SDK adapter and ingress tests | `/root/github-user-provider` | New `core/github_user_auth.py` and matching tests; preserve existing `github_auth.py` behavior |
| Domain DTOs, persistence, operations and migration | `/root/github-user-persistence` | New `core/github_user_oauth.py`, `rdb/models/github_user_oauth.py`, `repos/github_user_oauth/**`, relevant model registration and migration |
| Service orchestration and Public routes | `/root/github-user-service` | New `services/github_user_oauth/**`, `api/public/toolkit/v1/github_user.py`, focused service/route tests |
| Existing contract/projection/config integration, all phase integration | `/root` | GitHub auth unions, Toolkit create/update/delete/summary paths and route registration; generation and quality checks |
| Later UI and execution work | Assigned before phase activation | Never start before predecessor PR |

Agree detached typed provider/repository DTOs before integration. All repository methods own completed DB scopes. Requester context includes exact user/auth Session/Workspace/optional owning Agent and Toolkit. Service revalidates current management and registration at publication; provider HTTP never runs inside a transaction. Cleanup retains only encrypted non-executable retired material until exact-token revocation is confirmed and exposes an authorized retry.

## Verification and Removal

- Root runs integrated backend Ruff/typecheck/tests and documentation/migration/client checks; owners provide focused evidence, not a substitute for integrated validation.
- E2E is primary product evidence: Platform and BYOA, Platform absent, personal/two-org access, another participant, wrong/replayed/cancelled/stale setup, expiring rejection, permission intersection, replacement/disconnect and cleanup failures.
- Required CI uses deterministic synthetic provider/SDK fixtures without real GitHub credentials. Optional live registration/token/action tests are skipped explicitly without approved prerequisites; no production setting changes.
- Preserve old credentials, installation cache/map/routing, temporary discovery cleanup and generic MCP OAuth. Replace new-user reliance on installation cache, current three-mode-only config/serializer/form branches and registration-only fixture limitations.
- Prove no new-user refresh grant/secret/job, grant-wide revocation, App uninstall, global credential hub or proxy. Extend allowlisted summaries without secrets.
- Update Toolkit/MCP OAuth/System Settings/Runtime Living Specs where implemented behavior changes. Current Specs are not changed merely from Design.

## Environment, Rollout and Checkpoint

Use the Session-owned development environment or existing test substrate for product QA; never reset other Sessions or expose secrets. Backend/schema precede UI. Preserve encrypted cleanup on failure and do not silently downgrade user resources.

Checkpoint at plan creation: Requirements and ADR-D1/D2/D3 accepted; Design revision 3 M1-M11 approved by the implementation request. Only snapshot documents existed; no implementation/E2E/live provider behavior verified. No material decision remains pending.
