---
title: "Transaction Ownership Phase 6: Email Verification"
created: 2026-09-08
tags: [backend, architecture, database, security]
---

# Phase Execution Plan

- Phase: 6, Email verification delivery, verification, and administration reads.
- Branch/base: `refactor/email-verification-transactions-260908` →
  `refactor/title-repository-transactions-260908`.
- PR boundary: one reviewable account ownership slice for completed email
  verification repository operations and their direct service callers.
- Inputs: requester transaction rules; account/config transaction research and
  per-entry evidence; [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md);
  [transaction-260908/ADR](../adr/transaction-260908-repository-ownership.md);
  [transaction-260908/DESIGN](../design/transaction-260908-repository-ownership.md).
- Deliverables: Auth email-code delivery and conditional verification complete
  their database work inside repositories; Email Verification CRUD reads no
  longer own sessions; SMTP delivery remains after the completed database
  operation.
- Non-goals: password reset, signup token, user/session composition outside the
  existing separate Auth flow, API/schema/migration changes, locks, retries,
  compatibility aliases, or fallback behavior.
- Mechanisms: M1, M2, M3, M4, M5.
- Authorities: `transaction-260908/REQ-1` through `REQ-5`;
  `transaction-260908/ADR-D1` through `ADR-D3`.
- Design delta: None.

| Workstream | Owner | Owned paths | Dependencies / output | Validation |
| --- | --- | --- | --- | --- |
| Email verification repository ownership | `/root/impl-email-verification` | `repos/email_verification/**`, a new composing operation repository, `services/auth/**`, `services/email_verification/**`, directly coupled Security email OTP callers, focused tests, and User/Auth Spec | Existing email verification, user, and session repositories; completed create-delivery, verify-and-mark, stale cleanup, and read/list operations | Repository atomic rollback, conditional verification race, service transaction-state assertions, current error outcomes |
| Independent review and integration | `/root/tx-review`, `/root` | Read-only stable-diff review; shared evidence, integration, commit, PR, and CI handling | This phase plan and Phase 6 owner report | Requirements/ADR/Design/spec/diff review and final validation |

## Operation Boundaries

`EmailVerificationOperationRepository` owns database-only completed operations.
Its delivery operation deletes stale rows and inserts the new record in one
transaction. Its verification operation validates email, CSRF token, expiry,
single-use state, and code before conditionally marking the row verified in one
transaction. Query and list operations similarly close their own read
transactions.

Auth and Security services generate inputs, call completed operations, and perform
SMTP delivery only after the delivery operation returns. Auth preserves the
existing order: verified mark commit, stale cleanup, user resolution or existing
open-registration creation, then separately existing auth Session creation and
JWT issuance. This phase does not combine those existing separate auth session
operations into a new atomic group.

## Removal and Absence Verification

Remove `SessionManager` ownership from the Auth email-verification delivery and
conditional-mark scopes and every `EmailVerificationService` method. Remove direct session-taking
EmailVerification repository calls from Auth and the coupled Security email OTP
paths. Do not introduce a session alias, generic callback, repository-to-service
import, new lock, retry, fallback, migration, or public contract change.

Search direct callers and transaction factory imports after the implementation.
Verify that all changed service calls use completed typed operations, and that no
email service invocation occurs while the operation repository's transaction is
active.

## Integration and Review

The independent reviewer is `/root/tx-review`. Review against current User &
Authentication Spec, transaction Requirements/ADR/Design, the Phase 6 plan,
research evidence, and stable diff. Batch material corrections before final
validation.

Run focused pytest for Auth, Security, Email Verification service, and operation
repository tests; changed-path Ruff and format checks; full configured `ty`;
and pre-commit. Record no new REQ-5 exception: this slice uses conditional
database mutation rather than a cross-I/O lock. Do not commit, push, create a PR,
or merge in this owner worktree.
