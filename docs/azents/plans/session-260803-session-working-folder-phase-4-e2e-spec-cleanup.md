---
title: "Session Working Folder Phase 4 Execution Plan"
created: 2026-08-04
updated: 2026-08-04
tags: [session, workspace, migration, e2e, documentation]
---

# Phase Execution Plan

- Phase: `4 — Integrated E2E, Contract Migration, Spec Promotion, and Cleanup`
- Branch/base: `feat/session-working-folder-4-e2e-spec-cleanup` → `feat/session-working-folder-3-worktree-archive`
- PR boundary: verify the approved Session working-folder behavior end to end, tighten the expanded persistence contract after PostgreSQL zero-null evidence, promote verified behavior to current Specs, mark the snapshot implemented, and remove temporary plans.
- Inputs:
  - Phase 1 context persistence and expand migration `5ffa2fdb4e51`;
  - Phase 2 Runtime, Project Browser, API, generated-client, and Web behavior;
  - Phase 3 worktree allocation and archive cleanup safety;
  - confirmed `session-260803` Requirements, accepted ADR, approved Design revision 1, and implementation plan.
- Deliverables:
  - PostgreSQL expand/backfill/new-context evidence that `working_folder_path IS NULL` count is zero;
  - contract migration making `working_folder_path` non-null and replacing the transitional populated-path index with a named unique constraint;
  - deterministic public API and Docker Runtime E2E for Project Browser and worktree/archive/restore behavior;
  - current Spec promotion, matching `implemented: 2026-08-04` dates, and temporary-plan deletion.
- Non-goals:
  - changing ownership sources, path derivation, setup ordering, cleanup/retry policy, legacy allocation paths, restore semantics, retention purge behavior, or public API authority;
  - adding a fixed path fallback, reset coordinator, cleanup retry queue, purge filesystem work, or new Design mechanism;
  - deploying, modifying live data, merging, or hand-editing generated clients.
- Interfaces:
  - `SessionAgentContext.working_folder_path` remains the exact stored destructive-ownership authority;
  - paths remain derived from current Runner-reported Agent Workspace evidence;
  - archive commits before external I/O, attempts typed Git cleanup, then attempts exact lexical folder deletion once;
  - retention purge remains database-only.
- Approved Design mechanisms: `M1` through `M11`.
- Authority references: `session-260803/REQ-1` through `REQ-7`; `session-260803/ADR-D1` through `ADR-D4`; approved Design revision 1.
- Design delta: `None`
- Removal obligations:
  - replace nullable `working_folder_path` and its transitional populated-path unique index with the final non-null named unique constraint;
  - remove the feature implementation plan and Phase 1–4 plans after verified current Specs become authoritative.
- Absence verification:
  - migration schema inspection proves the final constraint and transitional-index removal, plus reversible downgrade;
  - repository search proves no Session working-folder plans remain after Spec promotion;
  - snapshot validation accepts matching Requirements and Design implementation dates.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Contract migration and zero-null proof | `/root` | `python/apps/azents/db-schemas/rdb/migrations/**`; migration tests; revision file | Phase 1 expand migration | Evidence-backed final persistence contract | PostgreSQL upgrade/downgrade, zero-null query, Alembic head/revision |
| Integrated API/Runtime E2E | `/root` | `testenv/azents/e2e/**` | Phases 1–3 | Complete approved journey evidence | Project Browser and worktree lifecycle E2E |
| Stable-diff validation | `/root` | affected Python/testenv/generated artifacts | Integrated behavior | Static and runtime evidence | Ruff, Pyright/ty, focused backend and migration tests, generated checks |
| Spec promotion and cleanup | `/root` | affected living Specs, snapshot frontmatter, Session working-folder plans | Complete validation | Specs authoritative; plans removed | `/spec-review`, docs validation/index generation, plan-absence search |

## Integration Order

1. Map `M1`–`M11` journeys to deterministic E2E or focused fault-injection evidence.
2. Exercise PostgreSQL from the pre-expand schema through expand backfill and new-context creation; record the zero-null query.
3. Generate and validate the contract migration, including final schema and downgrade shape.
4. Run deterministic Project Browser and Git worktree archive/restore E2E.
5. Run stable-diff backend, Runner, migration, generated-client, TypeScript/testenv, and documentation checks as applicable.
6. Run `/spec-review`, promote verified behavior, add matching implementation dates, and remove all feature plans.
7. Commit, push, open the stacked PR, request `hardtack`, and monitor CI without merging.

## Independent Review

- Exact reviewer: GitHub reviewer `hardtack`.
- Scope: Phase 4 diff against `M1`–`M11`, migration safety, deterministic E2E evidence, current Specs, snapshot implementation marking, and plan cleanup.
- Criteria: zero-null proof precedes contract tightening; no unauthorized mechanism or behavior; final uniqueness is correct and reversible; Session-folder ownership, symlink boundary, archive/restore, legacy path, and purge semantics remain approved.

## Final Validation

- PostgreSQL expand/backfill/new-context zero-null and contract upgrade/downgrade tests;
- Project Browser public E2E and Session Git worktree lifecycle E2E;
- focused backend matrix and Runner symlink/archive tests from Phases 1–3;
- Ruff format/check, full Pyright, E2E `ty`, Alembic head/revision, generated-artifact checks, and `git diff --check`;
- `/spec-review`, snapshot/frontmatter validation, generated docs indexes, and final plan-absence search.

## Scope-Drift and Context Checkpoint

Every changed file must map to verification or promotion of `M1`–`M11`. Reject a new ownership source, path rewrite, fallback, cleanup/retry mode, reset coordinator, legacy-path migration, purge filesystem work, API authority, live-environment mutation, or new Design mechanism. Record PostgreSQL environment/query/result, E2E results, static checks, affected Specs, implementation date, plan-removal proof, reviewer request, CI state, and blockers.
