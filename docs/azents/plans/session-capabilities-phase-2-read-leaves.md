---
title: "Independent Read Getters Phase Execution Plan"
created: 2026-10-04
tags: [concurrency, implementation-plan]
---

# Phase Execution Plan

- Phase: 2/6, independent descriptive getters (first lock-removal phase).
- Branch/base: `refactor/lag-tolerant-read-getters-261004` to foundation PR branch.
- Authority: `readleaves-261004/REQ-1`–`REQ-2`, ADR D1, Design M1.
- Design delta: None.
- Owner: `/root`; no implementation delegation is needed for two repository modules.
- Independent reviewer: `/root/catalog-design-owner`.
- Deliverables: five revision/Profile/configuration getters accept ReadSession and
  have no lock-mode argument; all callers/fakes updated; DB ReadOnly writer-overlap test.
- Non-goals: blanket owner gates, CAS/claim/credential mutation fencing, cache modes,
  static prompt or MCP cadence changes.
- Removal: getter-level for_update parameters and conditional row locks.
- Absence proof: source/caller inventory, typing and actual PostgreSQL read-only test.
- Verification: focused Runtime/provider-policy/reconciliation/state-sink tests,
  whole backend type/lint and required CI/E2E.
- Scope checkpoint: writer overlap returns old committed Profile name; pending
  mutation serialization remains at its original actual state transition.

The parent foundation PR remains unmerged. Update this branch to the verified
parent head before opening the stacked PR. Do not apply or deploy live resources.
