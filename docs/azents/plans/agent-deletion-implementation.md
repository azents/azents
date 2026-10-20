---
title: "Agent Deletion Implementation Plan"
created: 2026-10-20
tags: [agent, lifecycle, backend, testing]
---

# Agent Deletion Implementation Plan

- Requirements: [harbor-261020/REQ](../requirements/harbor-261020-agent-deletion-lifecycle.md).
- Decisions: [harbor-261020/ADR](../adr/harbor-261020-agent-deletion-lifecycle.md).
- Approved Design: [revision 2, M1–M12](../design/harbor-261020-agent-deletion-lifecycle.md), requester-approved 2026-10-20.
- Design delta: None.
- Implementation/integration/validation owner: `/root`.
- Single independent read-only reviewer: `/root/deletion-fix-review`.

## Delivery and Interfaces

1. **Participants and ownership** (`feat/agent-deletion-participants`, base approved design): M1–M9. Typed participant/context/evidence contracts; fenced complete DB operations; fresh registry-owned finalization; field-aware PostgreSQL ownership coverage and current dependency spec. Remove old manual completeness lists. No visibility schema or public UI changes.
2. **Visibility and read-only** (stacked on phase 1): M10–M12 plus existing M4. Public lifecycle projection, one nullable failure-boundary field, typed normal waits, authoritative mutation guards, generated clients, localized component states. Preserve authorized reads and internal cleanup.
3. **Pipeline verification** (stacked on phase 2): M6/M12. Expanded unit, PostgreSQL integration and component behavior matrices for each owning responsibility; no E2E-heavy branch matrices.
4. **Representative E2E and completion** (stacked on phase 3): M6/M7. Actual DELETE-to-disappearance flow, final spec review, verified implemented markers, remove temporary implementation/phase plans.

Each phase opens its own PR before the next phase starts. Root runs focused integrated validation and requests the named reviewer only for a stable diff. Corrected high-risk findings receive targeted re-review. All latest-SHA CI runs must finish; no merge or production changes are authorized.

## Verification and Prerequisites

- Frozen backend dependencies; existing isolated PostgreSQL testcontainers for repository and catalog tests.
- Ruff, whole-backend `ty`, focused pytest and migration/schema checks per changed boundary.
- Phase 2 regenerates OpenAPI clients and runs affected TypeScript checks/component tests.
- Required E2E uses existing testenv setup/public APIs without direct DB writes or paid models. Session dev environment preparation previously failed on a missing private helper image; investigate the exact prerequisite rather than resetting source data or changing test semantics.
- Pure policy doubles isolate orchestration; real PostgreSQL owns constraint/rollback/race evidence.

## Removal and Completion

Registry replaces finalizer model/absence tuples and monolithic external-cleanup dispatch. Phase 2 removes claim-time error clearing and UI-only edit assumptions. Retain Session authority, native evidence, shared resources and current retry cadence. Compare installed FK edges to the declared field-scoped catalog; preserve explicitly historical identifiers.

Update Living Specs with implementation, including keys/dependencies/delete policy/owner and actual verification date. Record commands/results and any remaining evidence at each boundary. Check both missing approved behavior and unauthorized additions. Any material Design delta returns to design; ordinary implementation details remain root-owned. Remove these plans only after all phases validate and specs are promoted.
