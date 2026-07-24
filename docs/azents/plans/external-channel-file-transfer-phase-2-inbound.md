---
title: "External Channel File Transfer Phase 2 Execution Plan"
created: 2026-07-23
tags: [backend, engine, slack, external-channel, files, runtime]
---

# External Channel File Transfer Phase 2 Execution Plan

## Phase Execution Plan

- Phase: `2 — Explicit inbound download`
- Branch/base: `feature/channel-file-transfer-inbound` →
  `feature/channel-file-transfer-foundation`
- PR boundary: One root-only provider-neutral Tool that validates a binding-scoped file
  locator, reads one currently accessible direct Slack-hosted file, enforces the effective
  inbound limit, and writes the complete result to one Runtime path.
- Inputs: Approved `files-260723` Requirements/ADR/Design, the multi-phase implementation
  plan, and Phase 1 metadata, locator, capability, and System Settings contracts.
- Deliverables: `download_external_file`, active ownership and capability validation,
  Slack `files.info` plus authenticated private-body download, declared and actual byte
  enforcement, current run-scoped Runtime `FileStorage.put`, overwrite protection, and a
  bounded result containing path, filename, media type, and actual byte count.
- Non-goals: Multiple files per call, automatic download, Exchange/Artifact/ModelFile
  creation, provider URL exposure, partial Runtime files, chunked Runtime writes,
  outbound publication, Admin settings, deterministic E2E, and living-spec promotion.
- Interfaces: The Tool accepts one opaque `file` locator, one absolute Runtime `path`, and
  explicit `overwrite`; the service receives the current Agent, Session, and run-scoped
  `FileStorage`; Slack metadata is normalized through the same Phase 1 classification;
  provider URLs and credentials remain inside the service/adapter boundary.

| Workstream | Owned paths | Output | Validation |
| --- | --- | --- | --- |
| Download domain/service | `services/external_channel/file_transfer.py`, focused tests, repository download-target query/data records | Active Agent/Session/binding/route/resource/connection validation, capability and credential resolution, effective inbound policy, provider-authoritative read, bounded Runtime write, safe result/errors | Service tests for ownership, lifecycle, capability, settings, provider failures, size limits, overwrite, Runtime failure, and no write before complete download |
| Slack read adapter | `services/external_channel/slack_events.py`, focused Slack client tests, shared Phase 1 normalization helper only when required | Typed `files.info` metadata, supported direct-hosted validation, private URL selection, authenticated bounded content read, controlled error mapping | Mock-transport tests for success, deleted/inaccessible/external/remote/Slack Connect/sparse/unsupported files, malformed metadata, declared oversize, actual oversize, auth, rate limit, and transport failure |
| Root Toolkit and Runtime wiring | `engine/tools/external_channel.py`, its tests, `engine/tools/runtime_instruction_context.py`, `engine/run/resolve.py`, focused resolve tests, Toolkit DI dependency wiring | Root-only Tool exposure beside `channel_action`, current run-scoped `FileStorage` lookup, stable Tool schema/result, controlled `FunctionToolError` mapping | Toolkit schema/execution tests, Runtime context missing tests, root/subagent exposure regression, current-run storage wiring tests |
| Integration and phase documentation | Phase execution plan and final cross-boundary callsite/test fixtures | One cohesive inbound path with no persistence or public API additions | Focused Ruff, Pyright, Pytest, pre-commit, `git diff --check`, and scope-drift review |

- Dependency order: Define repository/service target and provider result contracts first;
  add Slack reads and bounded content handling; wire the run-scoped Runtime context into
  the root Toolkit; then integrate Tool error/result rendering and focused regressions.
- Authorization order: Parse locator → verify provider support → query the current active
  Agent/Session/binding/route/resource/connection → require `download_files` → decrypt
  credentials → resolve effective inbound limit → call Slack.
- Transfer order: enforce destination overwrite policy → `files.info` → normalize and
  require a supported direct hosted file → reject declared oversize → select the current
  private download URL → fetch with bearer authentication while enforcing the actual-byte
  limit → write one complete payload through `FileStorage.put` → return bounded metadata.
- Atomicity: Provider and validation failures perform no Runtime write. Existing
  destinations fail before `put` unless `overwrite=true`. Runtime write failure remains a
  Tool failure and is never represented as a successful transfer.
- Final validation:
  - `cd python/apps/azents && uv run ruff check <all changed Python paths>`
  - `cd python/apps/azents && uv run ruff format --check <all changed Python paths>`
  - focused Pytest for External Channel file service, Slack adapter, Toolkit, Runtime
    context, repository query, and run-resolution wiring
  - `cd python/apps/azents && uv run pyright`
  - repository pre-commit hooks and `git diff --check`
- Scope-drift check: Compare
  `git diff --name-status feature/channel-file-transfer-foundation...HEAD` and the semantic
  diff against this phase. Remove outbound manifests/chunk reads/uploads, Admin API/Web,
  testenv E2E, living-spec changes, generated public API changes, durable file entities,
  or unrelated refactors before commit and PR creation.
