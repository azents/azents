---
title: "Workspace Project Browser Implementation Plan"
created: 2026-07-03
tags: [workspace, project, frontend, backend, runtime, plan]
---

# Workspace Project Browser Implementation Plan

## Source Documents

- [ADR-0089: Workspace Project Browser Surface](../adr/0089-workspace-project-browser-surface.md)
- [ADR-0090: Backend Project Browser Manifest](../adr/0090-backend-project-browser-manifest.md)
- [Workspace Project Browser Design](../design/workspace-project-browser.md)

## Stack Shape

```text
main
  ← feature/workspace-project-browser-design
  ← feature/workspace-project-browser-plan
  ← feature/workspace-project-browser-catalog
  ← feature/workspace-project-browser-manifest-api
  ← feature/workspace-project-browser-frontend
  ← feature/workspace-project-browser-verification
  ← feature/workspace-project-browser-spec-promotion
  ← feature/workspace-project-browser-cleanup
```

Expected PR titles:

1. `workspace-project-browser [1/N]: design documents`
2. `workspace-project-browser [2/N]: implementation plan`
3. `workspace-project-browser [3/N]: Phase 1 — catalog and status projection`
4. `workspace-project-browser [4/N]: Phase 2 — backend manifest API`
5. `workspace-project-browser [5/N]: Phase 3 — frontend Project browser surface`
6. `workspace-project-browser [6/N]: Phase 4 — E2E/testenv verification`
7. `workspace-project-browser [7/N]: Phase 5 — spec impact and promotion`
8. `workspace-project-browser [8/N]: Phase 6 — cleanup`

The `N` marker may remain symbolic while the stack is in flight. If a phase must split for reviewability, downstream numbers do not need to be renumbered.

## Requirement Mapping

| Requirement | Phase(s) | Notes |
| --- | --- | --- |
| REQ-WPB-1 — Project-first concrete session browser | Phase 2, Phase 3, Phase 4 | Backend returns Project manifest; frontend defaults to Project mode; E2E verifies populated and empty states. |
| REQ-WPB-2 — Explicit All files secondary mode | Phase 2, Phase 3, Phase 4 | Backend manifest preserves all-files mode; frontend exposes explicit switch; E2E verifies root inspection. |
| REQ-WPB-3 — Project management inside Workspace surface | Phase 3, Phase 4 | Frontend moves Project management into Workspace panel and removes normal Projects navigation. |
| REQ-WPB-4 — Project root capabilities are backend-provided and registry-scoped | Phase 2, Phase 3, Phase 4 | Backend capability model is source of truth; frontend renders it. |
| REQ-WPB-5 — Backend-owned Project browser manifest | Phase 2, Phase 3, Phase 4 | Existing-session and pre-session APIs return a shared entry model. |
| REQ-WPB-6 — Agent Project catalog stores reusable status projection | Phase 1, Phase 2, Phase 4 | Catalog/schema and status sync foundation precede manifest usage. |
| REQ-WPB-7 — Manifest reads are non-blocking | Phase 1, Phase 2, Phase 4 | Sync service and manifest service keep runner operations out of read path. |
| REQ-WPB-8 — Boundary-triggered Project status sync | Phase 1, Phase 2, Phase 4 | Phase 1 defines service; Phase 2 wires registration/bootstrap/run-end/runner-READY/read-refresh triggers. |
| REQ-WPB-9 — Preserve Agent Workspace path contract | Phase 2, Phase 3, Phase 4 | Existing file APIs keep absolute Agent Workspace paths; frontend continues file operations with those paths. |

## Phase 1 — Catalog and Status Projection

### Purpose

Introduce the Agent-scoped Project catalog/status projection foundation without changing the frontend surface or requiring the new manifest API.

### Covered requirements

- REQ-WPB-6
- REQ-WPB-7 foundation
- REQ-WPB-8 foundation

### Boundary

This phase adds durable status projection data and a sync/upsert service boundary. It does not switch frontend behavior and does not remove existing Project APIs.

### Input from previous phase

- ADR/design documents define the catalog as an Agent-scoped path candidate/status projection.
- Current code already has `agent_project_presets`, `agent_project_defaults`, and session-owned Project rows.

### Output for next phase

- A repository/service abstraction that Phase 2 can use to build Project manifests.
- Schema migration for the catalog/status projection.
- Idempotent status sync/update methods suitable for use by registration, bootstrap, run-end, runner-READY, manifest stale-read, and refresh triggers.

### Dependency and base branch

- Base: `feature/workspace-project-browser-plan`.
- Depends on design and implementation plan only.

### Expected end state

- Catalog rows can be upserted for an Agent/path before a session exists.
- Status projection can represent unchecked, available, missing, unavailable, and error states.
- Sync/update behavior is covered by backend unit tests.
- Existing preset/default/session Project behavior remains compatible until Phase 2 migrates call sites.

### Verification scope

- Backend repository/service tests for catalog upsert and status projection transitions.
- Migration check via existing backend migration tooling.
- No frontend E2E change expected in this phase.

## Phase 2 — Backend Manifest API

### Purpose

Expose backend-owned Project browser manifest entrypoints and wire meaningful status sync triggers while preserving existing file APIs.

### Covered requirements

- REQ-WPB-1 backend support
- REQ-WPB-2 backend support
- REQ-WPB-4 backend capability model
- REQ-WPB-5
- REQ-WPB-6 integration
- REQ-WPB-7
- REQ-WPB-8
- REQ-WPB-9 backend preservation

### Boundary

This phase adds backend APIs and public client schema updates. It should not complete the frontend Project-first migration beyond minimal client/router plumbing needed for type safety.

### Input from previous phase

- Catalog/status projection repository and service.
- Sync/upsert service boundary.

### Output for next phase

- Existing-session Project browser manifest endpoint.
- Pre-session Project manifest preview endpoint.
- Shared manifest response schema with browser modes, entries, status projection, and capabilities.
- Backend route/service tests for non-blocking read behavior and Project root capability policy.
- Generated OpenAPI and public TypeScript client updates.

### Dependency and base branch

- Base: `feature/workspace-project-browser-catalog`.
- Depends on Phase 1 data model and service outputs.

### Expected end state

- Frontend can consume one backend manifest contract instead of synthesizing Project-root semantics.
- Manifest reads do not call runner stat/list operations before responding.
- Registration success, registration request approval, session bootstrap, manifest stale-read enqueue, explicit refresh, run end, and runtime runner READY transition have sync trigger wiring or documented no-op-safe enqueue paths.
- Runtime lifecycle control remains outside status sync; runner READY triggers only status projection work.

### Verification scope

- Backend API tests for access control, session/agent match, Project path validation, pre-session preview, empty Projects, all-files mode descriptor, and capability policy.
- Tests proving manifest reads return stored unchecked/stale status without runner access.
- OpenAPI dump and public client generation checks.

## Phase 3 — Frontend Project Browser Surface

### Purpose

Move azents-web to the backend manifest contract and deliver the Project-first Workspace browser UX.

### Covered requirements

- REQ-WPB-1
- REQ-WPB-2
- REQ-WPB-3
- REQ-WPB-4 frontend rendering
- REQ-WPB-5 frontend consumption
- REQ-WPB-9 frontend preservation

### Boundary

This phase changes azents-web UI/container behavior. It should not introduce new backend semantics beyond consuming Phase 2 APIs.

### Input from previous phase

- Generated public client methods and types for existing-session and pre-session manifest APIs.
- Backend manifest entries include capabilities and status projection.

### Output for next phase

- Workspace panel defaults to Project mode.
- All files is an explicit secondary mode.
- Project management is inside the Workspace surface.
- Header no longer exposes a normal Projects tab.
- Legacy `?page=projects` normalizes to the canonical session surface.
- New-session Project preview/picker uses backend manifest semantics.
- File operations continue to use absolute Agent Workspace paths.

### Dependency and base branch

- Base: `feature/workspace-project-browser-manifest-api`.
- Depends on Phase 2 generated client and backend API contract.

### Expected end state

- Existing root-first file browser components are reused where possible, but action rendering follows backend capabilities.
- Project root rows do not expose delete/move/rename actions when capabilities disallow them.
- Empty Project mode is explicit and does not fall back to root entries.
- Project registration/removal flows remain session-scoped.

### Verification scope

- TypeScript typecheck/lint/build for azents-web.
- Component tests or Storybook stories for populated Project mode, empty Project mode, All files mode, and Project-root capability rendering when practical.
- E2E scenarios are finalized in Phase 4.

## Phase 4 — E2E/Testenv Verification

### Purpose

Run product-facing verification for the cumulative feature and fix any issues in the originating phase branches before spec promotion.

### Covered requirements

- All requirements REQ-WPB-1 through REQ-WPB-9.

### Boundary

This phase may add or adjust E2E/testenv fixture support and may carry targeted fixes discovered during verification. It must not introduce new product scope.

### Input from previous phase

- Cumulative implementation through Phase 3.
- QA Checklist from the design document.

### Output for next phase

- Design document QA Checklist filled with PASS execution records and fixes applied.
- E2E/testenv evidence for all added/changed behavior.
- Strict spec comparison table identifying spec updates required for Phase 5.
- No unresolved implementation-missing items.

### Dependency and base branch

- Base: `feature/workspace-project-browser-frontend`.
- Requires all implementation phases to have PRs opened.

### Expected end state

- Every QA checklist item has PASS evidence.
- Any failures are fixed in their originating phase branches and cascaded forward.
- Final full suite run confirms no regressions.

### Verification scope

The E2E primary matrix below is mandatory for this phase.

## Phase 5 — Spec Impact and Promotion

### Purpose

Promote implemented behavior into current specs and mark the design as implemented after verification evidence is complete.

### Covered requirements

- Spec side of all requirements, especially REQ-WPB-9 and QA-9.

### Boundary

This phase modifies specs and the design frontmatter only. It should not change product behavior.

### Input from previous phase

- PASS QA Checklist in the design document.
- Strict spec comparison table from Phase 4.
- Cumulative implementation diff.

### Output for next phase

- Updated current specs under `docs/azents/spec/**`.
- `docs/azents/design/workspace-project-browser.md` frontmatter has `implemented` set to the promotion date.
- PR body summarizes specs added, updated, or removed.

### Dependency and base branch

- Base: `feature/workspace-project-browser-verification`.

### Expected end state

- Current specs match implemented behavior.
- No `TBD` remains in the design QA Checklist.
- Documentation index is regenerated and verified.

### Verification scope

- `/spec-review` against cumulative implementation diff.
- Docs index generation/check.

## Phase 6 — Cleanup

### Purpose

Remove temporary planning documents after implementation and spec promotion are complete.

### Covered requirements

- No product requirement; this keeps documentation source-of-truth clean after completion.

### Boundary

This phase deletes only temporary plan documents and regenerates docs index. It must not change code, specs, ADRs, or implemented design content.

### Input from previous phase

- Implemented design and promoted specs.

### Output

- `docs/azents/plans/workspace-project-browser-implementation-plan.md` removed.
- Any phase-specific plan documents for this feature removed.
- Docs index regenerated.

### Dependency and base branch

- Base: `feature/workspace-project-browser-spec-promotion`.

### Expected end state

- Source of truth is implemented design, specs, ADRs, and code.
- Temporary plan artifacts are gone.

## E2E Primary Matrix

| Scenario | Requirement coverage | Fixture/prerequisite | Evidence |
| --- | --- | --- | --- |
| Existing session with two Projects opens Project mode by default | REQ-WPB-1 | Runtime-ready Agent Workspace with two deterministic Project directories and session rows | Browser assertion showing Project mode and exactly those Project roots |
| Empty session shows empty Projects state | REQ-WPB-1, REQ-WPB-2 | Session created with `project_paths: []` | Browser assertion showing empty state; no root entries until All files switch |
| All files mode shows Agent Workspace root | REQ-WPB-2, REQ-WPB-9 | Runtime-ready workspace with files outside Project roots | Browser assertion showing root entries after explicit mode switch |
| Project root action menu is registry-scoped | REQ-WPB-4 | Session with at least one registered Project | Browser/action assertion: remove Project visible; delete/move/rename hidden or disabled |
| Remove Project preserves filesystem directory | REQ-WPB-3, REQ-WPB-4 | Registered Project directory containing a known file | Remove Project, switch to All files, assert directory/file still exists |
| Legacy Projects URL normalizes away | REQ-WPB-3 | Existing session URL with `?page=projects` | Route assertion: canonical session surface renders; no standalone Projects page |
| Pre-session preview uses backend manifest semantics | REQ-WPB-5, REQ-WPB-6 | Draft session page with selected Project paths before first message | Browser/API assertion that preview entries match backend manifest entry model |
| Manifest read succeeds with unchecked/stale status | REQ-WPB-7 | Catalog row with unchecked/stale status and no runner dependency in read path | API assertion returns manifest immediately with unchecked/stale status |
| Status sync updates after runtime READY or explicit refresh | REQ-WPB-8 | Runtime transition or explicit refresh with deterministic Project path | API/browser assertion status changes after sync without blocking initial read |

## Testenv Fixture and Prerequisite Support

Product behavior must be verified through E2E first. Testenv support is needed only to make runtime-ready workspace contents deterministic and observable.

Required fixture capabilities:

- create or reuse an Agent with runtime-ready Agent Workspace;
- create deterministic directories and files under `/workspace/agent`;
- create sessions with explicit `project_paths`, including an empty set;
- expose a stable way to reset Project/catalog rows between scenarios;
- verify runtime runner readiness before scenarios that need file inspection.

External credentials are not expected. If E2E infrastructure requires a prerequisite snapshot, it should record only runtime readiness and fixture metadata, not secrets.

## Blockers and Manual Actions

No known blocker prevents implementation.

Potential implementation choices that must remain within existing decisions:

- Status sync can begin as best-effort/idempotent non-blocking work. A durable job queue is not required unless implementation reality shows in-process enqueue cannot satisfy refresh and stale-status behavior.
- Runtime READY sync should use runner state persistence boundaries, not runtime lifecycle control. Server must not restart or mutate runtime lifecycle based only on Project status sync needs.
- Future worktree creation is not part of this stack. The stack only provides catalog/manifest semantics that future worktree success can call.

## Completion Criteria

The stacked feature is complete when:

- all implementation phases are merged in order;
- E2E/testenv verification records PASS evidence for every QA Checklist item;
- specs are promoted and the design has an `implemented` date;
- temporary plan documents are removed in cleanup;
- no Project browser behavior remains dependent on frontend-only Project root synthesis.
