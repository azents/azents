---
title: "Multi-Worktree Registration Historical Decision Reconstruction"
created: 2026-07-04
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: multi-260704
historical_reconstruction: true
migration_source: "docs/azents/design/multi-worktree-registration.md"
---

# Multi-Worktree Registration Historical Decision Reconstruction

- Snapshot: `multi-260704`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/multi-worktree-registration.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### multi-260704/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: CI policy

- Backend repository/service/API tests must run in normal CI.
- Browser E2E can run in the existing E2E lane when the runtime fixture is available.
- Runtime-dependent E2E tests may be marked optional only when the CI environment cannot provide a ready runner; API/service coverage must not be skipped.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
