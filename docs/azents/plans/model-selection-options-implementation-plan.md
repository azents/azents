---
title: "Agent Model Selection Options Implementation Plan"
created: 2026-07-09
tags: [backend, frontend, database, api, documentation, testenv]
---

# Agent Model Selection Options Implementation Plan

## Feature summary

Design: [`docs/azents/design/model-selection-options.md`](../design/model-selection-options.md)

Introduce ordered selectable model option lists for Agents and Workspace model settings. Each list entry has a unique label and a resolved `AgentModelSelection` snapshot. Agent main/lightweight model choices and Workspace default main/lightweight choices reference labels from the list. The first ordered option is the deterministic fallback when a selected label is missing. Lists are stored as JSONB arrays, capped at 10 entries, and label uniqueness is enforced in application validation.

Existing direct snapshot fields remain as denormalized effective runtime/default snapshots:

- Agent `model_selection` and `lightweight_model_selection`
- Workspace `default_model_selection` and `default_lightweight_model_selection`

Runtime continues to use effective snapshots only; it must not resolve labels or query model catalogs during run start.

## Stack prefix

`model-selection-options`

## Planned PR stack

1. `model-selection-options [1/7]: Design`
   - Final design document under `docs/azents/design/`.
2. `model-selection-options [2/7]: Implementation plan`
   - This multi-phase plan under `docs/azents/plans/`.
3. `model-selection-options [3/7]: Backend model option contract`
   - Database migration, RDB/domain/repository data fields, service normalization, Agent and Workspace API schemas, backend unit tests, OpenAPI/client regeneration.
4. `model-selection-options [4/7]: Web model option editors`
   - Shared list editor UI, Agent create/edit form integration, Workspace model settings UI integration, frontend tests/stories where practical.
5. `model-selection-options [5/7]: Validation and spec comparison`
   - Planned backend/frontend checks, E2E/testenv validation evidence, independent subagent spec-vs-implementation comparison, fixes discovered during validation.
6. `model-selection-options [6/7]: Spec promotion`
   - `/spec-review`, living spec updates, model catalog drift correction, ADR for label-based model target contract.
7. `model-selection-options [7/7]: Cleanup`
   - Remove this implementation plan after specs and ADR reflect shipped behavior.

## Phase dependencies

- Phase 3 depends on Phase 1-2 documents.
- Phase 4 depends on generated client types from Phase 3.
- Phase 5 depends on backend and frontend behavior being complete enough for product validation.
- Phase 6 depends on Phase 5 verification evidence.
- Phase 7 depends on Phase 6 spec/ADR promotion.

## Phase 3: Backend model option contract

### Data model

- Add Agent fields:
  - `selectable_model_options` JSONB array, non-null after migration.
  - `main_model_label` string, non-null after migration.
  - `lightweight_model_label` string, non-null after migration.
- Add Workspace model settings fields:
  - `default_selectable_model_options` JSONB array, nullable only before configuration/backfill.
  - `default_main_model_label` string, nullable only before configuration/backfill.
  - `default_lightweight_model_label` string, nullable only before configuration/backfill.
- Generate Alembic migration via `alembic revision` and update `db-schemas/rdb/revision`.
- Backfill Agents from existing effective snapshots:
  - one `default` option when main and lightweight snapshots are equal;
  - `default` plus `lightweight` when they differ.
- Backfill Workspace settings from existing defaults:
  - no options when no default main model exists;
  - one `default` option when only default main exists or lightweight equals main;
  - `default` plus `lightweight` when lightweight differs.

### Core/service contract

- Add shared model option types near the existing Agent model selection contract:
  - request entry: label + `{ llm_provider_integration_id, model_identifier }` input;
  - stored/response entry: label + `AgentModelSelection` snapshot.
- Add app-layer normalization helper:
  - trims labels;
  - rejects empty labels;
  - rejects duplicates after trimming;
  - rejects more than 10 entries;
  - resolves every input through stored catalog projection;
  - normalizes missing selected labels to first entry;
  - returns effective main/lightweight snapshots.
- Keep label uniqueness case-sensitive after trimming.
- Preserve current `model_selection` and `lightweight_model_selection` request fields during transition, but prefer the new list path when supplied.
- Agent create behavior:
  - explicit selectable list overrides Workspace defaults;
  - otherwise copy Workspace default selectable list and labels;
  - creation without any model option fails;
  - write effective snapshot columns from labels;
  - when an explicit legacy `model_selection` is supplied, initialize a one/two-option list from legacy inputs and bootstrap Workspace defaults only if empty.
- Agent update behavior:
  - selectable list is whole-list replacement;
  - selected labels normalize against the final list;
  - effective snapshot columns are recomputed when list or labels change;
  - if only legacy direct model fields are supplied, update the effective list entry/labels consistently for compatibility during transition.
- Workspace settings update behavior:
  - default selectable list is whole-list replacement;
  - default labels normalize against the final list;
  - effective default snapshot columns are recomputed;
  - clearing an already configured default list remains disallowed.

### API/client

- Add new request/response fields to Agent create/update/read/list routes.
- Add new request/response fields to Workspace model settings get/update routes.
- Regenerate OpenAPI and generated Python/TypeScript public clients from the backend spec.

### Backend tests

- Normalization helper:
  - empty list rejected;
  - more than 10 rejected;
  - empty/whitespace label rejected;
  - duplicate trimmed labels rejected;
  - invalid selected labels fall back to first;
  - model resolution failure returns model-selection error.
- Agent service:
  - create copies Workspace default list;
  - explicit list overrides Workspace default list;
  - effective snapshots follow selected labels;
  - deleting selected label falls back to first option;
  - changing a selected label's model changes effective snapshot;
  - legacy direct model input initializes compatible list behavior.
- Workspace settings service:
  - update validates list and labels;
  - effective defaults follow selected labels;
  - existing configured defaults cannot be cleared.
- Runtime resolve:
  - existing effective snapshot source remains unchanged.

## Phase 4: Web model option editors

### Shared UI/state

- Add a reusable selectable model option editor for Agent and Workspace forms.
- Reuse `ModelCatalogPicker` for selecting each row's model.
- Support add, remove, reorder, edit label, and per-row model selection.
- Enforce the same frontend validation as backend for fast feedback:
  - at least one option;
  - at most 10 options;
  - non-empty labels;
  - duplicate trimmed labels;
  - selected labels fallback to the first remaining option when removed/renamed.

### Agent form

- Agent create form loads Workspace model settings and pre-fills list/labels from Workspace defaults.
- Agent edit form renders current Agent list and selected labels.
- Main/lightweight controls become label selects backed by the list.
- Save payload uses new selectable list and label fields.

### Workspace model settings

- Replace direct default model pickers with default selectable model list editor.
- Add default main/lightweight label selects backed by the default list.
- Persist new list/label fields through generated public client APIs.

### Frontend tests

- Editor prevents empty lists and duplicate labels.
- Removing selected label falls back to first option.
- Picking a row model updates only that row.
- Agent create payload uses Workspace prefilled defaults when unchanged.
- Workspace settings payload persists list and labels.

## Phase 5: Validation and spec comparison

### Commands and checks

Backend:

```bash
cd python/apps/azents
uv run pytest src/azents/services/agent src/azents/services/workspace_model_settings src/azents/repos/agent src/azents/repos/workspace_model_settings
uv run ruff check src/azents/core src/azents/rdb/models src/azents/repos/agent src/azents/repos/workspace_model_settings src/azents/services/agent src/azents/services/workspace_model_settings src/azents/api/public/agent src/azents/api/public/workspace_model_settings
uv run pyright src/azents/core src/azents/rdb/models src/azents/repos/agent src/azents/repos/workspace_model_settings src/azents/services/agent src/azents/services/workspace_model_settings src/azents/api/public/agent src/azents/api/public/workspace_model_settings
```

Frontend:

```bash
cd typescript
pnpm run lint --filter=@azents/web
pnpm run typecheck --filter=@azents/web
```

Generated clients/OpenAPI:

```bash
cd python/apps/azents
uv run python src/cli/dump_openapi.py
cd ../../..
turbo run generate --filter=@azents/public-client
```

### E2E primary validation matrix

| Scenario | Evidence |
| --- | --- |
| Workspace settings create a default model option list and default labels | Settings page save succeeds; API response contains list and labels |
| Agent create pre-fills Workspace default list | Agent create payload/created Agent contains copied list and selected labels |
| Agent edit changes a selected label's model | Agent response effective `model_selection` changes while selected label stays the same |
| Agent edit removes selected label | Response selects first remaining option and effective snapshot follows it |
| Chat run still starts using effective snapshot | Existing deterministic chat fixture succeeds without runtime catalog reads |

### Independent spec comparison

Before spec promotion, spawn an independent subagent with no implementation involvement to compare:

- `docs/azents/design/model-selection-options.md`
- current implementation diff
- current specs under `docs/azents/spec/domain/agent.md`, `docs/azents/spec/domain/model-catalog.md`, and `docs/azents/spec/flow/agent-execution-loop.md`

Required output from subagent:

- implemented behavior vs design table;
- current spec drift table;
- missing tests or validation risks;
- recommendation for spec promotion changes.

The lead agent must then directly double-check the subagent findings before finalizing validation.

## Phase 6: Spec promotion

- Run `/spec-review` against the implementation stack.
- Update `docs/azents/spec/domain/agent.md`:
  - selectable model options fields;
  - label fallback rules;
  - Workspace default list behavior;
  - effective snapshot cache/runtime source.
- Update `docs/azents/spec/domain/model-catalog.md`:
  - submit normalization for selectable model option entries.
- Update `docs/azents/spec/flow/agent-execution-loop.md`:
  - runtime receives effective snapshots resolved before run start.
- Correct current stale model-catalog drift around public listing vs stored projection behavior.
- Add an ADR for the durable label-based model target contract and rejected alternatives.
- Mark the design as implemented only after validation evidence is complete.

## Phase 7: Cleanup

- Delete `docs/azents/plans/model-selection-options-implementation-plan.md` after specs and ADR are merged.
- Keep the design document as historical rationale.
- Do not mix behavior changes into cleanup.

## Fixture/prerequisite support

- Existing deterministic model listing/catalog fixtures should be enough for backend and E2E coverage.
- No new provider credentials should be required.
- If E2E cannot assert the exact runtime model externally, use deterministic fixture evidence or API response/state evidence showing effective snapshots before run start.

## Blockers and external actions

None known. API/client generation and E2E environment availability are normal implementation prerequisites, not design blockers.

## Rollout notes

- Migration backfills existing rows so runtime remains compatible immediately after deploy.
- Existing direct snapshot fields stay populated, so worker/runtime deploy can be independent from web deploy.
- Existing clients can continue reading `model_selection` and `lightweight_model_selection` during the transition.

## Spec impact candidates

- Agent domain spec
- Model catalog domain spec
- Agent execution loop flow spec
- ADR for label-based model target abstraction
