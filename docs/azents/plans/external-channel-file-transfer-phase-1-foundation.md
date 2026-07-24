---
title: "External Channel File Transfer Phase 1 Execution Plan"
created: 2026-07-23
tags: [backend, engine, slack, external-channel, files, system-settings]
---

# External Channel File Transfer Phase 1 Execution Plan

## Phase Execution Plan

- Phase: `1 — Foundation contracts`
- Branch/base: `feature/channel-file-transfer-foundation` → `plan/channel-file-transfer`
- PR boundary: Bounded Slack file metadata and locators, independent file capabilities,
  and provider-neutral effective transfer-limit contracts, with no file byte transfer.
- Inputs: Approved `files-260723` Requirements/ADR/Design and the multi-phase
  implementation plan in PR 2.
- Deliverables: HTTP/Socket/hydration metadata parity, persisted bounded metadata,
  deterministic binding-scoped locators in every model-visible representation,
  independent read/write capabilities, generated Slack guidance scopes, and a typed
  direct-activation settings section with an additive PostgreSQL enum migration.
- Non-goals: Provider file reads, Runtime writes, Runtime chunk reads, Slack upload calls,
  Admin API/Web presentation, generated Admin clients, deterministic E2E, living-spec
  promotion, and any attachment table or durable file staging.
- Interfaces: `attachment_metadata.files` contains bounded provider-neutral entries and
  no URLs or bytes; Agent-visible entries add `file` locators with the
  `external-file:v1:<provider>:<binding-id>:<provider-file-id>` envelope;
  `ExternalChannelCapabilitySnapshot` adds required `download_files` and `upload_files`
  booleans; `ExternalChannelFilesConfig` owns inbound, outbound per-file, and outbound
  aggregate byte limits.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Shared file contract and integration | Root agent | `python/apps/azents/src/azents/core/external_channel_file.py`, its tests, phase plan, Public OpenAPI specification, generated Public Python/TypeScript clients, and final integration only | Approved Design and exposed capability schema | Bounded metadata model, locator encode/decode/enrichment helpers, shared constants, and generated client parity | Focused core tests, OpenAPI/client generation, Ruff, Pyright/typecheck |
| Slack ingress and capabilities | Slack foundation agent | `services/external_channel/slack_http.py`, `slack_http_test.py`, `slack_events.py`, `slack_events_test.py`, `data.py`, `contracts_test.py`, `connection_test.py`, `management.py`, `management_test.py`, and focused Socket tests if required | Shared contract | Safe `files[]` projection/normalization, unsupported classification, scope-derived capabilities, file scopes in generated guidance | Focused Slack and contract tests, Ruff |
| Model-visible projection and continuity | Rendering foundation agent | `services/input_buffer.py`, `input_buffer_test.py`, `engine/events/external_channel_rendering.py`, `external_channel_rendering_test.py`, `filters_test.py`, `openai_responses_test.py`, `litellm_responses_test.py`, and `services/chat/context` tests only if needed | Shared contract and normalized metadata shape | Locator enrichment at invocation projection and identical bounded Files rendering through structured value, initial lowering, replay, continuity, and token accounting | Focused input/render/lowerer/filter/context tests, Ruff |
| System Settings and migration | Settings foundation agent | `core/system_setting.py`, new External Channel settings definition/tests, `services/system_setting/service.py`, `service_test.py`, generated Alembic migration, `db-schemas/rdb/revision`, and focused model/migration tests | Approved limits contract | Registered schema-v1 direct section with defaults and invariants plus additive PostgreSQL enum value | Focused settings tests, Alembic heads/check, Ruff |

- Dependency order: Root fixes the shared file metadata, locator, and settings-limit
  constants first. Slack, rendering, and settings workstreams may then run in parallel.
  Rendering consumes only the shared metadata/locator helpers; Slack produces the stored
  metadata shape; settings remains independent except for shared numeric constants.
- Integration order: Shared core contract → Slack projection and capability changes →
  invocation enrichment and rendering → settings registry and migration → all callsite and
  fixture updates → focused tests → whole-app typecheck → scope-drift review.
- Shared files reserved for integration: Root owns the phase plan, shared core contract,
  generated Public API artifacts required by the exposed capability schema,
  cross-workstream conflict resolution, any test fixture changed by more than one
  workstream, and final commit/PR text. No subagent may edit an unowned path without an
  updated plan.
- Final validation:
  - `cd python/apps/azents && uv run ruff check <all changed Python paths>`
  - `cd python/apps/azents && uv run ruff format --check <all changed Python paths>`
  - focused Pytest for core file contracts, Slack HTTP/events/contracts/connection/
    management, input buffer, rendering, filters, both Responses lowerers, chat context,
    System Settings, and migration/model coverage
  - `cd python/apps/azents && uv run python src/cli/dump_openapi.py`
  - `cd python/libs/azents-public-client && make generate`
  - `cd typescript && pnpm run generate --filter=@azents/public-client`
  - `cd python/apps/azents && uv run pyright`
  - `cd python/apps/azents && uv run alembic -c db-schemas/rdb/alembic.ini heads`
  - repository pre-commit hooks and `git diff --check`
- Scope-drift check: Compare `git diff --name-status plan/channel-file-transfer...HEAD`
  and the semantic diff against the deliverables and explicit non-goals. Remove any file
  transfer, Runtime byte I/O, Admin UI/API, E2E, spec-promotion, or unrelated refactor
  before commit and PR creation.
