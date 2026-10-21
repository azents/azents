---
title: "Google Direct Tools Phase 1 Foundation Execution Plan"
created: 2026-10-21
tags: [google, implementation, backend, security]
---

# Phase Execution Plan

- Phase: 1, canonical contracts and cutover primitives.
- Branch/base: `feat/google-direct-foundation` → `main` (`cc1d82fa9` at start).
- PR boundary: Reviewable pure foundation for the approved direct replacement; not a separately deployable new Google implementation.
- Inputs: Confirmed [Requirements](../requirements/google-261021-direct-workspace-tools.md), accepted [ADR](../adr/google-261021-direct-workspace-tools.md), approved [Design revision 1](../design/google-261021-direct-workspace-tools.md), current Google Connection Spec and [implementation plan](google-direct-implementation-plan.md).
- Deliverables: Typed service/request intent; supported operation scope alternatives and actual grant projections; strict pure old-config/published-outcome transformations with nonsecret preflight failures; focused tests.
- Non-goals: Activating persisted contracts before consumers are replaced, Google SDK effects, live OAuth, UI/Picker implementation, operational migration, merge or deployment.
- Interfaces: Canonical services and supported sorted/deduplicated request scopes; operation identities carry service and exact SDK method; sufficient actual scope sets are independent of request intent; projection distinguishes whole-Drive read/write and app-file access. Migration takes decoded typed old/new config/outcome data, preserves unrelated final metadata and rejects malformed/ambiguous input without echoing it.
- Approved Design mechanisms: M1 (catalog boundary), M2, M4 (contract), M5 (scope projection), M9 (pure transform), M10 (atomic preflight prerequisites), M13 (narrow matrix).
- Authority references: google-261021/REQ-1 through REQ-10 as traced in Design; ADR-D1/D4; Design sections 5/6/7/10/13; strict typed-ingress and dependency-layer conventions.
- Design delta: None.
- Removal obligations: No execution replacement is activated in this primitive phase. Old policy consumers are replaced in phase 2; management/ack/task persisted contracts and Alembic activation in phase 3. New contracts contain no task ceiling, scanner acknowledgement, schema version or permissive fallback.
- Absence verification: Inspect new contracts for accidental old-task/action authority; compare all catalog method alternatives to official discovery evidence. Full old-unit absence is owned by replacement phases, not claimed here.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Approved baseline and plans | `/root` | `docs/azents/{requirements,adr,design}/google-261021-direct-workspace-tools.md`, supporting validation, these feature plans | requester approval | recorded matching approval and authority | catalog validation, snapshot/trace checks |
| Direct scope contracts | `/root` | `python/apps/azents/src/azents/core/google_workspace_policy.py`, companion tests | Design M1/M2/M4/M5 | service intent, operation catalog and actual capabilities | scope alternatives, broad/partial/empty/unknown, disabled services, Drive mixed-scope tests |
| Cutover primitive | `/root` | `python/apps/azents/src/azents/core/google_workspace_cutover.py`, companion tests | canonical contracts | deterministic validated transformation/preflight | all eight old tasks, old/new canonical shapes, malformed config, historical metadata/identity tests |

- Integration order: Approved baseline → canonical catalog/intent → pure transformation → focused integrated checks → stable-diff review → root corrections/checks → commit/PR.
- Independent review: `/root/google-direct-reviewer`, read-only one-way opinions after root completes implementation and validation; root applies corrections directly.
- Final validation: Root runs affected Ruff check/format, `uv run ty check --error-on-warning`, focused pytest, `python scripts/docs_catalog.py validate`, snapshot checks and `git diff --check`. Full subproject pytest runs when feasible; distinguish missing infrastructure from code failures. No provider credentials required.
- Scope-drift check: New contracts cover approved direct operation groups without arbitrary URL/method execution or selected-action restrictions; migration adds no grants, credential store, version/fallback or remote effects. Return material findings to design rather than extending authority.
- Context checkpoint: Design approved; no runtime contract activation. Implemented 70 closed operations over 48 SDK methods; 263 sufficient-scope alternatives match the official discovery revisions Gmail/Drive `20261012`, Calendar `20261016`. Root ran whole-backend Ruff check/format and `ty check --error-on-warning` successfully. Focused pytest: 135 passed. Whole-backend `pytest -n auto --dist worksteal -q`: 13,642 passed, 3 skipped in 106.94 seconds before the final strict-timeout validator tightening and its three new cases; affected focused tests and whole-backend lint/format/type checks passed again afterward. No live Google calls, migration, API/generated contract changes or runtime activation. The single independent reviewer found one scope underexposure: metadata-only `files.update` access fields also admit `drive.metadata`. Root corrected that entry and expanded the regression to distinguish metadata access fields from content writes and permission-resource mutations, then reran affected tests, static checks and official method-scope comparison. The same reviewer's targeted re-review confirmed the correction resolved with no further findings (reviewed staged diff SHA-256 `d1de4771c7c583ee00c32e834c2cc3c0bd2f2f33e597fb0bf154cd410f55ee6f`). At migration activation, freeze the finite historical mapping/transform inside the generated migration itself and retire the preparatory core cutover helper; it must not become a runtime legacy policy dependency. Later phases must consume these primitives, move the shared service enum out of the retired MCP policy, generate migration through Alembic, test disposable populated databases, replace obsolete units and validate complete assembled behavior before marking implementation complete.
