---
title: "Transaction Ownership Phase 12: Security Operations"
created: 2026-09-08
tags: [backend, architecture, database, security]
---

# Phase Execution Plan

- Owner: `/root`, direct implementation and review without subagents.
- Base: `refactor/auth-session-transactions-260908` at `cc7109f1d`.
- Authority: transaction-260908 Requirements REQ-1 through REQ-5, ADR-D1 through ADR-D3, and Design revision 1 mechanisms M1 through M5.
- Design delta: None.
- Outcome: Security service password and User reads and mutations return from completed DB-only operation repositories. Email delivery, password hashing/checking, and JWT creation stay outside transactions.
- Preserve existing OTP consumption, password setup/removal errors, email availability, and last-valid-credential behavior. Recheck password removal eligibility at the final DB mutation rather than trusting the separate credential projection preflight.
- No schema, public API, dependency, distributed-lock, or recovery-contract changes.
- Credential provider projection and UserEmail administration ownership remain explicit residuals until their separate composing boundaries are migrated; this slice does not claim their arbitrary concurrent mutations are coordinated.
- Validation: Security and credential regression tests; focused final-removal stale-state tests; full backend type checking and affected API tests; pre-commit; explicit absence search for service-owned transaction contexts.
- This phase plan remains active until the whole migration is cleaned up.
