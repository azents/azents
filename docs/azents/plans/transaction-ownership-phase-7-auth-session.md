---
title: "Transaction Ownership Phase 7: Auth Session Operations"
created: 2026-09-08
tags: [backend, architecture, database, security, concurrency]
---

# Phase Execution Plan

- Phase: 7, Auth identity resolution, authentication Session issuance, refresh,
  and revocation operations.
- Branch/base: `refactor/auth-session-transactions-260908` →
  `refactor/email-verification-transactions-260908` at
  `e0ba6ef50ca0759dc59cc380d373fc94cafe3ef5`.
- PR boundary: one reviewable Auth ownership slice that replaces every remaining
  `AuthService` database context on this base with completed typed repository
  operations.
- Inputs: requester transaction rules; account/config transaction audit and Auth
  per-entry evidence; completed Phase 6 email verification ownership;
  [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md);
  [transaction-260908/ADR](../adr/transaction-260908-repository-ownership.md);
  [transaction-260908/DESIGN](../design/transaction-260908-repository-ownership.md),
  revision 1; current User & Authentication Spec.
- Deliverables: Auth user resolution or open-registration creation, password
  credential snapshot loading, active-user Session issuance, refresh-token
  eligibility/rotation/grace handling, and logout revocation finish their database
  work inside a new Auth operation repository. JWT creation, password hashing work,
  and terminal invalidation remain outside database transactions.
- Non-goals: combining Phase 6 verification marking with later Auth stages; changing
  verification phase order, registration policy, token timing, token expiry,
  authorization, error mapping, schema/API/generated clients, migrations, locks,
  retries, compatibility aliases, fallback behavior, or unrelated Session services.
- Interfaces: typed completed repository inputs/results only. The repository composes
  existing User, UserEmail, PasswordLogin, and Session repositories with no live
  Session or general callback exposed. Repository modules do not import services.
- Approved Design mechanisms: M1, M2, M3, M4, M5.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`;
  `transaction-260908/ADR-D1` through `ADR-D3`; current User & Authentication Spec.
- Design delta: None.
- Removal obligations: remove `SessionManager`, `AsyncSession`, transaction factory,
  and narrow session-taking repository dependencies from `AuthService`; remove all
  direct Auth service ownership of the remaining user/password/session contexts.
- Absence verification: search `services/auth/**` and direct callers for transaction
  factory imports, `async with` database contexts, direct narrow repository calls,
  live Session parameters, callback wrappers, compatibility aliases, and
  repository-to-service imports.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Auth completed operations | `/root/impl-auth-session` | `python/apps/azents/src/azents/repos/auth_operation/**`, its tests, and required narrow repository adjustments | Existing User, UserEmail, PasswordLogin, Session repositories and session manager | Typed repository-owned identity, credential, issuance, refresh, and revoke operations | Atomic/error tests, refresh concurrency and grace/rotation/max-expiry tests, disabled-user final-authority tests |
| Auth orchestration migration | `/root/impl-auth-session` | `python/apps/azents/src/azents/services/auth/**`, direct callers/tests | Auth operation interfaces; Phase 6 verification operations | No Auth-owned database context; preserved verification/user/session order; JWT/password verification/terminal invalidation outside DB | Deterministic transaction-state assertions, registration-disabled and invalid-token service tests |
| Current behavior specification | `/root/impl-auth-session` | `docs/azents/spec/domain/user-auth.md`, this phase plan | Stable implementation behavior | Current ownership boundaries, date/version/changelog | Documentation validation and spec-path review |
| Independent review and integration | `/root/tx-review`, `/root` | Read-only stable-diff review; shared integration handling | This plan, approved authority, audit evidence, implementation and tests | Requirements/ADR/Design/spec/diff review findings | Exact reviewer report and correction verification |

## Operation Grouping and Race Preservation

1. Keep the existing verification phases separate: Phase 6 conditional verification
   mark commits first, stale verification cleanup commits second, Auth user
   resolution/open-registration creation commits third, and authentication Session
   issuance commits fourth. Do not combine the mark with user or Session work.
2. Resolve an email to an existing user or create the user only when registration is
   open in one completed database operation. Preserve disabled-user and
   registration-required result mapping.
3. Password login loads the active user and password-hash snapshot in one completed
   read. Password verification runs after that operation. Session issuance uses a
   separate completed operation that revalidates active-user authority with a
   database-only `FOR SHARE` User row lock held through Session insertion. This
   serializes with account disable-and-revoke so a stale credential snapshot cannot
   leave a newly disabled account with an active Session.
4. Session issuance retains refresh-token expiry and optional maximum-expiry values
   calculated by Auth orchestration. JWT creation occurs only after the Session
   transaction commits.
5. Refresh lookup, revoked/expired/user-disabled eligibility, previous-token grace,
   current-token rotation interval, maximum-expiry clamping, and conditional
   rotation stay in one repository-owned transaction. The candidate token is
   generated before entering the repository, and concurrent current-token requests
   preserve the existing conditional-update behavior: one rotation wins and the
   loser returns the latest committed Session/token rather than publishing its
   unused candidate.
6. Logout revocation completes before terminal invalidation publication. Missing
   Session mapping remains unchanged, and publisher failure does not reopen or roll
   back the completed revocation.
7. No cross-I/O lock is needed. Session issuance uses only a short database row lock
   in the User-then-Session lock order, while refresh keeps its existing conditional
   token update. The Phase 7 REQ-5 cross-I/O exception ledger result is `None`.

- Integration order: add operation data/contracts and repository tests; implement
  repository operations; migrate AuthService and service tests; update current
  spec; run absence inventory and final validation.
- Independent review: `/root/tx-review` reviews the stable diff read-only against
  transaction Requirements/ADR/Design, current User & Authentication Spec, this
  Phase 7 contract, account audit/per-entry evidence, Phase 6 boundaries, exact
  error/phase/concurrency behavior, and removal obligations. Output is one findings
  report for `/root` and the implementation owner.
- Final validation: focused Auth operation and service pytest; changed-path Ruff
  check and format; full `uv run ty check --error-on-warning`; normal staged
  pre-commit. No commit, push, PR, merge, or live action in this owner worktree.
- Scope-drift check: verify M1–M5 coverage for all remaining Auth contexts and reject
  schema/API/lock/retry/fallback changes, verification-stage combination, generic
  transaction wrappers, unrelated Session ownership migration, and product behavior
  changes.
- Context checkpoint: record completed operation behavior, changed interfaces,
  deterministic boundary/concurrency evidence, remaining account ownership scope,
  touched paths, risks, and blockers in the final owner report.
