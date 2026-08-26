---
title: "Reliable Runtime Lifecycle Implementation Plan"
created: 2026-08-25
updated: 2026-08-25
tags: [runtime, lifecycle, implementation, plan]
---

# Reliable Runtime Lifecycle Implementation Plan

## Authority

- Requirements:
  [runtime-260825/REQ](../requirements/runtime-260825-reliable-lifecycle.md)
- ADR: [runtime-260825/ADR](../adr/runtime-260825-reliable-lifecycle.md)
- Approved Design:
  [runtime-260825/DESIGN](../design/runtime-260825-reliable-lifecycle.md),
  revision `1`, authority IDs `M1` through `M9`
- Design delta: `None`

## Delivery Shape

Use two stacked PRs.

1. `runtime lifecycle [1/2]: normalize restart convergence`
2. `runtime lifecycle [2/2]: ship authoritative lifecycle UI`

The first PR changes durable Control interpretation and both Provider Restart
boundaries without changing the public lifecycle schema. The second PR adds the
shared public presentation, generated clients, frontend behavior, E2E coverage,
Living Spec promotion, implemented markers, and plan cleanup.

## Reviewer

- Exact independent reviewer: `runtime-lifecycle-reviewer`
- Role: read-only review against confirmed Requirements, accepted ADR, approved
  Design revision `1`, current Specs, phase plan, and current diff
- Required review focus: lifecycle authority, destructive boundaries,
  generation/configuration fencing, cross-Provider consistency, API meaning,
  and missing/unauthorized Design mechanisms

## Phase 1: Control and Provider Convergence

- Branch: `feat/runtime-reliable-lifecycle`
- Base: `origin/main`
- Approved mechanisms: `M2`, `M3`, `M4`, `M7`, `M9`
- Deliverables:
  - successful correlated Restart completion hands the same generation to Start;
  - Docker and Kubernetes Restart delete execution resources only;
  - Recreation holds concurrency until exact Provider and Runner readiness; and
  - focused repository, gRPC, reconciler, Recreation, and Provider tests.
- Removal obligations:
  - remove Provider-local delete-and-create Restart;
  - remove Recreation success based on applied configuration alone.
- Validation:
  - focused `azents` backend tests;
  - Docker Provider tests and quality checks;
  - Kubernetes Provider tests and quality checks;
  - pre-commit on changed files.

## Phase 2: Presentation, UI, and Verification

- Branch: `feat/runtime-reliable-lifecycle-ui`
- Base: `feat/runtime-reliable-lifecycle`
- Approved mechanisms: `M1`, `M5`, `M6`, `M8`, plus integrated verification of
  `M2`, `M3`, `M4`, `M7`, and `M9`
- Deliverables:
  - one shared server lifecycle presentation in Runtime and Workspace APIs;
  - generated Python and TypeScript clients;
  - authoritative Agent Runtime settings and Workspace UI;
  - explicit Restart confirmation and distinct Reset presentation;
  - transition polling, component coverage, and required Docker E2E;
  - Living Spec updates and implemented markers.
- Removal obligations:
  - remove public/UI reliance on the single `RuntimeSummary`;
  - remove independently interpreted Workspace lifecycle meaning;
  - remove Restart submission without confirmation.
- Validation:
  - backend/API tests and full affected Python quality checks;
  - OpenAPI client regeneration and drift validation;
  - TypeScript format, lint, typecheck, tests/build;
  - required focused E2E;
  - `/spec-review` equivalent spec-impact audit;
  - pre-commit and PR CI.

## Interfaces and Integration

- Phase 1 preserves the existing public API.
- Phase 1 fixes the durable Restart semantics that Phase 2 presents.
- Phase 2 may add or replace public response fields only as authorized by `M1` and
  regenerates clients from OpenAPI.
- Redis and process-local state remain coordination only.
- No relational migration or protobuf field is planned.

## E2E and Prerequisites

- Reuse existing Runtime Profile and `agent-basic` prerequisites.
- Verify Workspace preservation with a deterministic sentinel file.
- Docker is the required E2E Provider.
- Kubernetes asynchronous deletion remains required Provider unit-test coverage;
  live Kubernetes verification is optional only when its prerequisite is absent.
- No new credential snapshot is planned.

## Removal and Absence Verification

| Removal | Phase | Verification |
| --- | --- | --- |
| Provider-local Restart recreation | 1 | Provider tests prove no create/start/ensure calls occur during Restart. |
| Configuration-only Recreation success | 1 | Reconciler tests hold items running until Provider and Runner readiness. |
| Single-summary UI authority | 2 | Repository search finds no frontend Runtime lifecycle translation from `RuntimeSummary`. |
| Independent Workspace lifecycle authority | 2 | Runtime and Workspace API tests compare the shared lifecycle presentation. |
| Restart without confirmation | 2 | Component interaction tests require confirmation before mutation. |
| Temporary plans | 2 | Final branch removes this plan and all phase plans after spec promotion. |

## Rollout and Rollback

Deploy the stacked changes as one coordinated release after both PRs merge. Phase 1
is safe independently because old UI continues reading existing actions and Provider
Restart remains an idempotent lifecycle operation. Phase 2 requires Phase 1.

Rollback is coordinated. Existing desired generations and configuration evidence
remain valid; ordinary Start convergence is idempotent.

## Blockers

None.
