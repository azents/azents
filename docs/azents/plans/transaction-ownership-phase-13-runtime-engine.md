---
title: "Transaction Ownership Phase 13: Runtime Control Reads"
created: 2026-10-01
tags: [backend, runtime, engine, architecture, database]
---

# Phase Execution Plan

- Phase: 13, completed Runtime Control read operations.
- Branch/base: `refactor/transaction-ownership-261001-1-runtime-engine` → `main`.
- PR boundary: remove the two residual transaction lifetimes in
  `runtime/control_server.py` using typed completed repository reads.
- Authorities: transaction-260908/REQ-1 through REQ-5, ADR-D1 through ADR-D3,
  Design revision 1 mechanisms M1 through M5.
- Design delta: None.
- Non-goals: Runtime protocol, owner routing, model selection, transcript
  semantics, schema/API/configuration/retry/fallback changes, or cross-I/O locks.
- Reviewer: `/root/issue-hardening-review` read-only.

## Boundaries

Repository operations own Runtime lookup and generation cutover lookup. Existing
generation and owner authority remain unchanged. Runtime/Provider/owner work and
server startup remain after the completed operations.

## Validation

Run focused Runtime Control and repository tests; full
backend Ruff/format/type checks and pytest; pre-commit; independent review; and PR
CI. Search the changed services for remaining transaction-factory ownership and
repository-to-service imports.
