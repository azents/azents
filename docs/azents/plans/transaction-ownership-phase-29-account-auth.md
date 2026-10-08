---
title: "Transaction Ownership Phase 29: Account and Authentication Access"
created: 2026-10-02
tags: [backend, security, architecture, database]
---

# Phase Execution Plan

- Phase: `29, complete Account CRUD, system roles and authentication admission`.
- Branch: `refactor/transaction-ownership-261002-17-account-auth`.
- Initial parent: Phase 28 PR #2052, `e5b6ed552405c68781edffbeac0b66e8e2f2e2f4`.
  Gate verified: open, MERGEABLE/CLEAN, 38 passed checks, 3 skipped checks,
  no failed or unfinished checks. No Agent merge. If the parent remains open,
  create a stacked PR; if merged, reconcile with main using the stack procedure.
- Scope: 25 application-owned lifetimes: User 6, UserEmail 5, Workspace 6,
  SystemUserRole 6, core authentication/membership admission 2.
- Deliverables: domain-local completed repository operations, session-free
  services and HTTP auth dependencies, detached typed outcomes, canonical pure
  input/error definitions for touched API/CLI callers, atomicity/boundary tests.
- Non-goals: Credential (2 contexts and 6 session-taking declarations), signup,
  bootstrap, password reset, invitations, configuration, Memory, Engine/Worker
  and other issue #1718 residuals. No schema, public contract, provider, retry,
  configuration, compatibility, generated client, or new lock changes.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
  REQ-1 through REQ-5; [ADR](../adr/transaction-260908-repository-ownership.md)
  ADR-D1 through ADR-D3; [DESIGN](../design/transaction-260908-repository-ownership.md)
  revision 1; current User & Authentication and Workspace & Membership Specs.
- Design delta: `None`.

## Ownership and Integration

| Workstream | Owner | Owned paths | Output |
| --- | --- | --- | --- |
| Account deletion and system roles | `/root/tx-platform-inventory` | repos/user and system_user_role operations/data/tests; services/user and system_user_role; new core/user.py and core/system_user_role.py; API admin/user, admin/system, public/user; CLI system_admin; auth_operation repository_test deletion constructor only | 12 completed operations, canonical errors/patch input, rollback and shared-lock preservation |
| Email and Workspace | `/root/tx-chat-inventory` | repos/user_email and workspace operations/data/tests; services/user_email and workspace; new core/user_email.py and core/workspace.py; API admin/user_email, admin/workspace, public/workspace | 11 completed operations, atomic owner membership, unique conflict and omission preservation |
| Authentication access | `/root/tx-engine-input` | new core/account_access.py, repos/account_access.py, services/account_access.py; core/auth/deps.py and deps_test.py | 2 completed admission reads; detached outcomes; unchanged HTTP contexts |
| Integration and evidence | `/root` | phase/master plans, Specs, remaining defining-module imports, quality and CI evidence | zero public/admin OpenAPI delta, full backend validation, independent review and PR CI |

Shared file coordination: the access owner updates the SystemUserRoleService
fixture in deps_test only after learning the account owner's constructor.
Account owner may update defining-module imports for its relocated symbols outside
owned directories except access/email/workspace-owned files; coordinate those
with their owner. Workspace and email DTOs unrelated to API input/error relocation
remain in place. Narrow repository primitives remain available to later compositions
and explicitly deferred credential providers. No commits or branch changes by
implementation owners; root integrates and commits the stable diff.

## Preserved Atomic Groups and Effects

- User create retains User + primary UserEmail + final primary reference together.
  Read/update/list semantics, locale and omitted fields are unchanged.
- Deletion acquires the existing shared advisory lock `0x617A656E7473`, checks
  User and final-admin authority, disables access, removes roles, revokes every
  authentication Session and creates/gets the durable purge job in one transaction.
  A typed outcome distinguishes missing User (success, no publication/log) from
  accepted deletion, including an already-disabled existing User. Terminal
  invalidation and accepted logging remain in the service after commit/close.
- Role grant/revoke retain the same shared advisory lock and live enabled-User,
  assignment and final-admin predicates. Grant returns assignment plus `created`
  from the same transaction to preserve audit logging. Email lookup remains a
  separate completed read before locked grant revalidation.
- Workspace-only admin create stays distinct from Workspace + OWNER create.
  Workspace, resolved internal ID and ordinary WorkspaceUser.create share one
  transaction; membership insertion failure rolls back Workspace. Existing unique
  conflicts and rollback behavior remain unchanged. List membership/Workspace
  rows in one completed read and retain missing projection omission.
- UserEmail uniqueness, missing delete, foreign-key and pagination behavior remain
  unchanged. Do not add credential or primary-email policies.
- Auth admission evaluates User and exact authentication Session in one completed
  read. Workspace admission evaluates handle and membership in one completed read.
  Repositories consume pure domain input and return detached domain outcomes;
  JWT, HTTP errors, elevated flag, context and permission projection stay outside.
- No arbitrary callbacks, HTTP/service dependencies, external clients, retries,
  new locks, or live sessions escape the repository boundary.

## Removal and Absence Verification

Remove all 25 assigned application contexts and primitive/SessionManager injection
from migrated services and auth dependencies. Remove obsolete defining-module
symbols when relocating inputs/errors and update all callers without re-exports
or aliases. Preserve narrow repository APIs needed by existing compositions.
Search direct contexts, SQLAlchemy imports, live session parameters, returned
handles, callbacks, reverse imports and actual implicit transaction boundaries.
Do not treat lexical counts as confirmed repository-wide violations.

## Validation and Delivery

1. Baseline generated public/admin OpenAPI stored outside the repository before
   implementation; regenerate after integration and require identical JSON.
2. Focused existing service/repository/auth tests plus completed-operation tests:
   deletion rollback/purge/revoke/publication/missing/repeat/final-admin;
   shared advisory lock and Session issuance FOR SHARE concurrency;
   role idempotency/enabled-user checks; Workspace owner rollback; email conflicts;
   required/optional auth rejection matrix and workspace 404/403/live membership.
   Use deterministic barriers and authoritative state, not sleeps.
3. Ruff/format, configured `ty --error-on-warning`, full backend pytest and
   pre-commit, explicit saved exits and skip reasons. Real PostgreSQL must cover
   lock/deferred-FK and issuance/deletion tests; no provider credentials required.
4. Independent read-only review by retained `/root/phase25-independent-review`
   after the stable integrated diff and validation. Fix correctness findings and
   revalidate affected evidence before shipping.
5. Create PR with English title/body; run applicable required admin/public account,
   auth, Workspace and system-role E2E/CI on the exact head. Do not merge without
   explicit requester authorization. Keep the broad Channel Work active.
6. Re-measure residual inventory including latest main Memory additions. Record
   each assigned disposition and preserve all explicit later residuals. Phase 29
   alone does not satisfy issue #1718 closure; final call-path/coverage audit,
   integration checks, Spec promotion and temporary-plan cleanup remain.

## Execution Checkpoint

- All three implementation workstreams are stable. User/Role 12, Email/Workspace
  11, and access 2 assigned contexts now finish inside completed repository
  operations. Migrated services and HTTP auth dependencies expose no manager,
  SQLAlchemy, Session argument or arbitrary transaction callback.
- Canonical input/error moves update every defining-module caller without aliases
  or re-exports. Existing narrow query APIs and deferred Credential remain intact.
- Root integrated focused suite: `179 passed`. Root full backend final suite:
  `7072 passed, 3 skipped`. Skips remain the existing Redis-specific memory-variant
  cases; no missing live prerequisite was substituted for required verification.
- Root Ruff/format, full backend ty, full pre-commit, final public/admin OpenAPI
  exact JSON comparison (`234` / `69` paths), and removal/caller checks passed.
  All commands preserve saved logs and explicit exit markers outside the repo.
- Initial full suite had two new Workspace tests assuming an empty global list.
  Root changed only those tests to assert the authoritative baseline plus exactly
  two newly created handles, preserving rollback/projection checks. The complete
  focused and backend suites plus pre-commit were rerun successfully. Earlier new
  FK tests were corrected to actual commit rather than savepoint-only validation.
  No product behavior, constraint, schema, lock or retry was changed by these fixes.
- Fresh comparable candidate inventory: `600` contexts in `111` files at parent
  `e5b6ed552` becomes `575` in `106` files. These are discovery candidates, not
  confirmed residual violations. The extra parent candidate is Historical Memory
  snapshot refresh; it remains a later named scope.
- Design delta: `None`; all fixed atomicity, authorization, lock identity and
  post-commit effects remain intact. No cross-I/O lock exception was needed.
- Shipping base is `main` at `f42dc1f26` after the requester merged parent PR
  #2052 and the catalog fixes. The mandatory rebase script completed without
  conflicts; range-diff confirms all 111 phase patches are identical to the
  previously validated slice. Latest-base full backend revalidation passed
  `7111` cases with the same `3` skips; ty, pre-commit and exact OpenAPI equality
  also passed. The earlier `7072` result is retained as parent-base evidence.
- Retained independent reviewer `/root/phase25-independent-review` reviewed all
  `111` files with no findings: `75` import-only AST-equivalent paths and `36`
  direct implementation/test/documentation paths. Independent PostgreSQL and
  admission regression subset: `84 passed`. No source correction was needed.
- Exact-head PR CI remains pending; overall issue #1718 is not close-ready while
  broader application lifetimes and coverage remain.
