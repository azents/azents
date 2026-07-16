---
title: "Model-Scoped Selectable Model Settings Implementation Plan"
created: 2026-07-16
updated: 2026-07-16
tags: [backend, frontend, engine, models, migration, e2e, planning]
---

# Model-Scoped Selectable Model Settings Implementation Plan

## Feature Summary

Implement [Model-Scoped Selectable Model Settings](model-scoped-selectable-model-settings.md) and
[ADR-0145](../adr/0145-model-scoped-selectable-model-settings.md). Selectable model options will own token
caps and enabled built-in tools; Agent-global copies will be removed; Workspace defaults will share the
same contract; and only fully implemented built-in tools will remain configurable.

## PR Stack

### 1. Design

Branch: `feature/model-scoped-settings-design`

- Add ADR-0145.
- Add the feature design and test strategy.
- No runtime behavior changes.

### 2. Implementation plan

Branch: `feature/model-scoped-settings-plan`

- Record PR boundaries, dependencies, validation, rollout, and cleanup.
- No runtime behavior changes.

### 3. Backend, migration, and generated clients

Branch: `feature/model-scoped-settings-backend`

Depends on: implementation plan.

- Add selectable model settings core/API/repository contracts.
- Normalize default settings after catalog model resolution.
- Validate enabled tools per option.
- Remove `web_fetch` and `image_generation` configurable built-in tools.
- Apply selected option settings in foreground run, effective-context, and subagent paths.
- Persist selected settings in Session inference state for stable retry and recovery.
- Add a forward schema/JSONB migration and update the migration revision pointer.
- Regenerate OpenAPI specifications and public clients.
- Add backend tests for normalization, persistence, runtime resolution, catalog filtering, and migration
  transformations where supported by the existing migration test substrate.

### 4. Frontend model settings UX

Branch: `feature/model-scoped-settings-frontend`

Depends on: backend and generated clients.

- Extend selectable option form values and serialization.
- Add row-level settings modal for token caps and supported built-in tools.
- Enable all supported implemented tools when a model is selected.
- Remove Agent-global token and tool controls.
- Reposition the add button, add empty labels, and focus the newly created label input.
- Reuse the editor in Agent and Workspace default settings.
- Add/update Storybook fixtures and component-level interaction coverage available in the workspace.

### 5. Validation and spec promotion

Branch: `feature/model-scoped-settings-validation`

Depends on: frontend.

- Run deterministic E2E for Agent settings, Workspace default copy, model switching, and effective
  context behavior.
- Add only the fixture/prerequisite support required by those tests.
- Run Python and TypeScript quality checks.
- Perform visual verification at desktop and mobile widths.
- Compare implementation with Agent, model catalog, execution-loop, and context-compaction specs.
- Update living specs and mark the design implemented only after validation succeeds.

### 6. Cleanup

Branch: `feature/model-scoped-settings-cleanup`

Depends on: validation and spec promotion.

- Remove this temporary implementation plan.
- Regenerate documentation indexes.
- Make no behavior changes.

## Data and API Dependency Order

1. Core option settings types establish the stored and public contract.
2. Catalog-backed normalization derives safe defaults from resolved capabilities.
3. Migration materializes settings and removes unsupported tool identifiers before strict readers use the
   new contract.
4. Runtime consumes complete selected options.
5. Generated clients expose the new contract to frontend forms.
6. Frontend stops sending Agent-global migrated fields.

The coordinated release must deploy the migration and backend before or with the matching frontend. There
is no legacy runtime fallback.

## Migration Mapping

For every existing Agent option:

- copy old `context_window_tokens` and `max_output_tokens` to the option;
- if old built-in tools are non-empty, retain only supported implemented tools for that option;
- otherwise enable all supported implemented tools;
- remove migrated keys from Agent `model_parameters`.

For every Workspace default option:

- set both token caps to null;
- enable all supported implemented tools.

Add `agent_sessions.current_model_settings` and backfill prepared Sessions from their current model
snapshot and the owning Agent's old global settings. Remove `web_fetch` and `image_generation` from
persisted capability/tool arrays in current catalog, Agent, Workspace, and Session snapshots. Preserve
historical provider-tool events and attachments.

## Test Strategy by Phase

### Backend phase

- Core validation: omitted/default settings, explicit empty tools, unsupported and duplicate tools,
  positive token values.
- Service normalization: Agent direct options, Workspace defaults, Workspace-to-Agent copy.
- Runtime: default target, prompt-selected target, subagent override, main/lightweight context caps,
  max output and web-search lowering.
- Persistence: Agent and Workspace JSON round trips.
- Catalog: only implemented tool IDs survive capability construction.
- Migration: representative JSONB before/after fixtures where database integration is available.

### Frontend phase

- New option starts empty and receives focus.
- Add action sits immediately above the model list at desktop and mobile widths.
- Settings modal round-trips null/value token fields.
- Supported tools render from capability data; web search starts enabled and can be disabled.
- Model replacement resets settings from the new capability.
- Agent and Workspace forms serialize identical option settings.

### E2E validation matrix

| Scenario | Fixture | Assertion |
|---|---|---|
| Add model on mobile | Existing editable Agent | Empty label input is visible and focused |
| Per-model persistence | Two deterministic models | Distinct settings survive save/reload |
| Built-in defaults | Web-search-capable model | Web search starts enabled; unsupported tools are absent |
| Prompt target switch | Two model labels | Captured request uses selected option output/tool settings |
| Context switch | Different option caps | Session effective context and threshold match selected pair |
| Workspace copy | Saved Workspace defaults | New Agent contains identical option settings |
| Removed tools | Migrated/seeded capability data | Web fetch and image generation are not configurable |

## Fixture and Prerequisite Requirements

- Extend the deterministic catalog only if it does not already provide one web-search-capable model and one
  model without built-in tools.
- Use local deterministic provider/request capture for runtime assertions.
- Do not require production or live provider credentials.
- Capture Agent and Workspace identifiers created by E2E setup rather than relying on static database IDs.

## CI and Skip Policy

- Backend Ruff, Pyright, and targeted/full Pytest failures block the stack.
- TypeScript format, lint, typecheck, and build failures block the stack.
- Deterministic E2E failures block spec promotion.
- Live-provider checks are optional and may skip only when credentials are unavailable; they do not replace
  deterministic coverage.
- Generated OpenAPI/client diffs must be clean after regeneration.

## Spec Impact Candidates

- `docs/azents/spec/domain/agent.md`
- `docs/azents/spec/domain/model-catalog.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/context-compaction.md`

## Rollout and Cleanup

- Apply the forward migration before strict new readers serve traffic.
- Deploy backend and frontend as one coordinated feature release.
- Do not edit executed migrations or preserve Agent-global fallbacks.
- After validation, promote current behavior to living specs, mark the design implemented, and remove this
  plan in the cleanup PR.

## Known Blockers

None. The deterministic E2E request-capture capability must be confirmed during the validation phase; if
it cannot assert provider kwargs, backend runtime tests remain authoritative and E2E verifies the visible
selection and persisted effective profile.
