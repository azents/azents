---
title: "Transaction Ownership Phase 11: External Management"
created: 2026-09-08
tags: [backend, architecture, database, external-channel]
---

# Phase Execution Plan

- Owner: `/root`, direct execution and review without subagents.
- Base: `refactor/external-channel-connection-transactions-260908` at `a890d3dae`.
- Authority: transaction-260908 Requirements REQ-1 through REQ-5, ADR-D1 through ADR-D3, Design revision 1 mechanisms M1 through M5.
- Design delta: None.
- Goal: replace service-owned External Channel management transaction lifetimes with typed, completed repository operations; keep provider calls and lease assertions outside active DB transactions.
- Preserve Agent/admin and Workspace authorization, Multi App generation checks, connection/route/default lifecycle transitions, response-mode behavior, and current provider contracts.
- Preserve the two durable stages of single-connection disconnect. Failure after the first stage must retain DISCONNECTING and existing recovery behavior; no implicit stage collapse.
- Replace commit-then-query inside one service scope with explicit repository-owned write/read boundaries or an atomic completed projection where the current contract permits it.
- Existing conversation and participation leases are not new approved cross-I/O exceptions. Inventory their protected invariants separately; avoid introducing distributed locking and report unresolved unavoidable exceptions only after independent work.
- Repository methods compose narrower DB repositories, not mixed-I/O services or generic callbacks. Existing service error classes may become repository-origin errors with direct caller imports updated.
- Verification: source lifetime inventory; focused management/service/API and repository tests; stale generation/authorization and disconnect failure coverage; full backend type check; pre-commit; direct residual/lease review.
- Out of slice: unrelated access/admission, channel action dispatch, transport workers, and provider-output/file compensation unless directly required by a migrated management operation. They remain part of the broader unfinished migration.

## Implementation and Verification

- Replaced all 42 direct management-service session contexts with completed DB-only operations. Removed the service session manager, SQLAlchemy/RDB imports, and narrow repository dependencies.
- Preserved generation fencing, authorization, route idempotency, post-commit projection reads, and both durable stages of Single App disconnect. Provider actions and lease assertions remain service-owned and outside active DB transactions.
- Audited the operation await inventory: 40 async methods, including the private generation-lock helper; calls remain within repository composition and database operations. Public results are detached domain data or provider-effect plans.
- Full backend suite: 5,218 passed, 2 skipped. Subsequent disconnect failure-stage test additions passed in the focused service suite (25 tests); they do not change production code.
- Focused coverage includes authorization failures, stale generations, setup commit failure before activation, and first/second disconnect commit failures before terminal controls. Event assertions verify session exit before external effects.
- Full backend type checking, changed-file Ruff/format, and diff whitespace checks passed. Commit hooks run at submission.
- Updated External Channel lifecycle Living Spec to describe completed management operations and preserved two-stage disconnect.
- No new distributed locks or provider contracts were introduced. Existing lease suitability and unrelated transaction domains remain explicit follow-up work in the broader migration.
