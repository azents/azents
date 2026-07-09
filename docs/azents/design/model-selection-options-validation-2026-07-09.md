---
title: "Agent Model Selection Options Validation Report"
created: 2026-07-09
tags: [backend, frontend, testenv, documentation]
---

# Agent Model Selection Options Validation Report

## Scope

Validated the `model-selection-options` stack through the frontend implementation branch and the validation branch.

Branches in stack order:

1. `azents/model-selection-options-design`
2. `azents/model-selection-options-plan`
3. `azents/model-selection-options-backend`
4. `azents/model-selection-options-frontend`
5. `azents/model-selection-options-validation`

## Implementation summary

- Backend adds Agent and Workspace selectable model option lists, label selections, normalization, migration/backfill, API fields, and generated clients.
- Web adds a shared selectable model option editor used by Agent forms and Workspace model settings.
- Validation branch adds deterministic E2E coverage for Workspace selectable defaults copying to Agent create and first-option fallback after selected labels are removed.

## Commands run

### Backend

```bash
cd python/apps/azents
uv run ruff check . && \
  uv run pytest src/azents/services/model_options_test.py \
    src/azents/services/agent \
    src/azents/services/workspace_model_settings \
    src/azents/repos/agent \
    src/azents/repos/workspace_model_settings \
    src/azents/engine/run/resolve_test.py \
    src/azents/services/memory/service_test.py && \
  uv run pyright
```

Result: passed.

- Ruff: `All checks passed!`
- Pytest: `14 passed, 2 skipped`
- Pyright: `0 errors, 0 warnings, 0 informations`

### Frontend

```bash
cd typescript
pnpm run format --filter=@azents/web
pnpm run lint --filter=@azents/web
pnpm run typecheck --filter=@azents/web
```

Result: passed.

Note: one parallel lint/typecheck attempt caused a transient `@azents/public-client:generate` file race while both tasks regenerated the same output directory. Re-running the commands sequentially passed.

### E2E static validation

```bash
cd testenv/azents/e2e
uv run pyright src/tests/azents/public/test_model_selection.py
uv run ruff check src/tests/azents/public/test_model_selection.py
```

Result: passed.

The new E2E test is deterministic and API-level. It covers:

1. Workspace `default_selectable_model_options` update with main/lightweight labels.
2. New Agent creation copying the Workspace selectable model list and selected labels.
3. Agent update with removed selected labels falling back to the first ordered option.

The E2E test itself was not executed locally because the validation environment in this runtime did not start the Azents devserver fixture. It should run in the normal deterministic E2E environment.

## Independent spec comparison

An independent subagent compared the design, implementation diff, and current specs.

### Implemented behavior vs design

| Design requirement | Verification result |
| --- | --- |
| Agent-owned ordered selectable model list capped at 10 | Implemented in backend data/API/service and web editor. |
| Unique trimmed labels and non-empty validation | Implemented in backend normalizer and frontend validation. |
| Main/lightweight selections reference labels | Implemented through `main_model_label` and `lightweight_model_label`. |
| Invalid selected label falls back to first option | Implemented in backend normalizer and editor state updates. |
| Runtime keeps using effective snapshots | Implemented; runtime resolve still reads `model_selection` and `lightweight_model_selection`. |
| Workspace defaults become selectable option list plus labels | Implemented. |
| Agent create prefilled from Workspace defaults | Implemented in backend create path and web create form. |
| Whole-list replacement on Agent/Workspace update | Implemented. |
| Submit normalization resolves through stored catalog projection | Implemented. |
| No chat composer, subagent model selection, or dynamic routing in this phase | Preserved. |

### Current spec drift

| Spec | Drift |
| --- | --- |
| `docs/azents/spec/domain/agent.md` | Still describes only direct Agent model snapshots and direct Workspace defaults. Needs selectable option fields, label rules, fallback, caps, whole-list replacement, and denormalized effective snapshot semantics. |
| `docs/azents/spec/domain/model-catalog.md` | Submit normalization should cover selectable model option entries, not only singular direct model selections. |
| `docs/azents/spec/flow/agent-execution-loop.md` | Runtime behavior is mostly still accurate, but should explicitly say labels are resolved before run start and runtime receives effective snapshots only. |
| Cross-spec model catalog text | `agent.md` still contains stale text saying public model listing does not use materialized catalog cache, conflicting with `model-catalog.md`. |

## Direct double-check

The lead agent independently checked the same spec areas and confirmed the subagent findings:

- The design is aligned with the implementation direction.
- The current living specs are stale and must be promoted before cleanup.
- `agent.md` contains the largest behavior drift and a known stale catalog-cache paragraph.
- `model-catalog.md` already reflects stored catalog reads but needs selectable option normalization coverage.
- `agent-execution-loop.md` needs only a runtime boundary clarification.

## Validation risks

- Browser UI E2E for the new editor was not added in this validation branch. The API-level deterministic E2E covers the durable behavior; Storybook covers editor states.
- The new E2E test should be run in the deterministic E2E environment before merging the validation PR.
- Legacy direct model fields remain accepted by backend and tRPC routes for transition compatibility. Spec promotion should document this as current compatibility behavior rather than a ModelConfig legacy fallback.

## Recommendation

Proceed to spec promotion:

1. Update `docs/azents/spec/domain/agent.md` for selectable model option fields and rules.
2. Update `docs/azents/spec/domain/model-catalog.md` for selectable option submit normalization.
3. Update `docs/azents/spec/flow/agent-execution-loop.md` with the runtime snapshot boundary.
4. Add an ADR for the durable label-based model target contract.
5. Keep cleanup as a later stack PR after specs and ADR are merged.
