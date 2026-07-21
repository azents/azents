---
title: "Model-Scoped Selectable Model Settings Validation"
created: 2026-07-16
updated: 2026-07-16
tags: [backend, frontend, engine, migration, e2e, qa]
document_role: supporting
document_type: supporting-validation-report
migration_source: "docs/azents/design/model-scoped-selectable-model-settings-validation-2026-07-16.md"
---

# Model-Scoped Selectable Model Settings Validation

## Environment

- Repository base: `origin/main` at `8231f070`
- Python: project-managed `uv` environments
- TypeScript: pnpm workspace with Turborepo
- Container runtime: unavailable locally (`docker: not found`)

## Validation Results

| Area | Command | Result |
|---|---|---|
| Backend full tests | `cd python/apps/azents && uv run pytest -q` | Passed: 1298 passed, 390 skipped |
| Backend static checks | `cd python/apps/azents && uv run ruff check ... && uv run ruff format ... && uv run pyright` | Passed |
| Generated Python client | `cd python/libs/azents-public-client && uv run pytest -q` | Passed before the validation phase: 416 passed |
| Deterministic settings fixture | `cd python/apps/azents && uv run pytest -q src/azents/testing/deterministic_model_listing_test.py` | Passed: 1 test |
| Testenv static checks | focused Ruff and Pyright for changed E2E files | Passed |
| E2E collection | `cd testenv/azents/e2e && uv run pytest --collect-only -q ...` | Passed: 8 tests collected |
| Deterministic E2E execution | focused model-selection and per-prompt profile tests | Not run locally because Docker is not installed; CI execution is required |
| Frontend format/lint/typecheck | filtered `@azents/web` Turborepo commands | Passed |
| Frontend unit tests | `cd typescript/apps/azents-web && pnpm run test` | Passed: 18 tests |
| Frontend Storybook/build | filtered Storybook and production builds | Passed; Storybook emitted only the existing chunk-size warning |
| PostgreSQL migration execution | Alembic upgrade against a populated PostgreSQL fixture | Not run locally because Docker/PostgreSQL is unavailable; CI deployment validation is required |
| Independent code review | read-only subagent review of the full implementation stack | Two warnings found and fixed: migration tool deduplication and empty-row label fallback |

## E2E Coverage Added

The deterministic catalog now has a dedicated `deterministic-model-settings` variant with one
`web_search`-capable model and one model without built-in tools. The focused E2E assertions cover:

- distinct Workspace option settings and exact copy into a newly created Agent;
- prompt-selected context caps and resulting automatic compaction thresholds;
- prompt-selected maximum output tokens in the mock provider journal;
- enabled `web_search` and explicit all-off option serialization through Workspace and Agent APIs.

AIMock converts Responses requests into its Chat Completions fixture shape and intentionally filters
non-function tools from the request journal. Provider-native `web_search` lowering therefore remains
covered by the runtime lowerer and resolver tests rather than by a journal assertion.

## Implementation-to-Spec Comparison

| Contract | Implementation evidence | Spec result |
|---|---|---|
| Settings belong to each selectable option | Core/API/repository contracts store `SelectableModelSettings` beside each model snapshot | Updated `domain/agent.md` |
| Omitted settings default from resolved capability | Agent and Workspace normalization derives defaults after catalog resolution | Updated `domain/agent.md` and `domain/model-catalog.md` |
| Explicit empty built-in tools means all-off | Normalization and runtime tests preserve `[]`; E2E API assertions distinguish enabled and disabled option settings | Updated `domain/agent.md` |
| Unsupported configurable tools are removed | Implemented registry and capability projection retain only `web_search`; migration strips removed identifiers | Updated `domain/model-catalog.md` |
| Foreground runtime uses selected option settings | `RunRequest` resolution applies selected output cap, tools, and context cap | Updated `flow/agent-execution-loop.md` |
| Retry and recovery retain prepared intent | `AgentSession.current_model_settings` is stored with the selected model snapshot | Updated `domain/agent.md` and `flow/agent-execution-loop.md` |
| Lightweight context cap affects compaction | Effective context combines selected foreground and lightweight option caps | Updated `flow/context-260305-context-compaction.md` |
| Lightweight output cap does not override summary budget | Compaction continues to use its dynamic internal output budget | Updated `flow/context-260305-context-compaction.md` |
| Workspace settings copy is complete and non-propagating | New Agent creation copies option snapshots and settings; later Workspace edits do not propagate | Updated `domain/agent.md` |
| New model UX starts with an empty focused label | Shared editor creates an empty row and focuses its label input | Storybook interaction coverage present |
| Reordering a pending empty row preserves valid selected labels | Fallback first preserves an existing valid label, then chooses the first non-empty option | Frontend unit regression coverage present |

## Remaining CI Evidence

The validation PR must remain failing or incomplete until deterministic E2E and migration checks run in
an environment with PostgreSQL and the repository container fixtures. After those checks pass, mark the
feature design implemented and record the final CI result here.
