---
title: "External Channel File Transfer Phase 3 Execution Plan"
created: 2026-07-23
tags: [backend, engine, slack, external-channel, files, runtime, delivery]
---

# External Channel File Transfer Phase 3 Execution Plan

## Phase Execution Plan

- Phase: `3 — Outbound streaming reply`
- Branch/base: `feature/channel-file-transfer-outbound` →
  `feature/channel-file-transfer-inbound`
- PR boundary: Extend one existing explicit `channel_action` reply with up to 20 Runtime
  files, validate every source before commit, stream files sequentially to Slack, and
  publish text plus all files through one completion and one existing `REPLY` outcome.
- Inputs: Approved `files-260723` Requirements/ADR/Design, the multi-phase plan, Phase 1
  capability/settings contracts, and Phase 2 run-scoped Runtime context wiring.
- Deliverables: Bounded outbound manifest, Tool schema/preflight, Runtime ranged reads and
  1 MiB iterator, persisted file-bearing reply intent, Slack external upload acquisition,
  sequential direct upload, one completion, and conservative one-attempt outcome mapping.
- Non-goals: Upload-only action, parallel/resumable upload, Exchange/Artifact/ModelFile or
  private staging, replay without the original run-scoped source, Admin UI/API, fake
  provider/E2E, living-spec promotion, and provider-specific administrator overrides.
- Interfaces: `channel_action.files` is an optional list of at most 20 absolute Runtime
  paths; file-bearing calls require message text; committed JSON stores only path,
  filename, media type, and expected size; upload URLs, credentials, and bytes remain
  in-memory; the existing `ExternalChannelDeliveryOperation.REPLY` owns the result.

| Workstream | Owned paths | Output | Validation |
| --- | --- | --- | --- |
| Manifest and Tool preflight | `core/external_channel_file.py`, `engine/tools/external_channel.py`, focused tests, action service input | Typed bounded manifest; absolute regular readable path validation; per-file and aggregate limits; message requirement; current run-scoped source passed only for immediate delivery | Tool schema, stat/path/limit/capability tests and unchanged text-only regressions |
| Runtime bounded source | `services/file_storage.py`, `engine/tools/builtin.py`, focused storage tests | `read_range` beside whole-file `get`; ordered 1 MiB iterator; exact expected byte count; no whole-file read | Range/iterator ordering, too-short, too-long, mutation/read failure, and operation-count tests |
| Durable action and one-attempt orchestration | `repos/external_channel/work.py`, `work_data.py`, `services/external_channel/channel_action.py`, focused tests | Manifest in action and `REPLY` payload; commit-before-provider call; immediate source injection; recovered file-bearing attempt without source terminalized conservatively | Idempotency, payload secrecy, commit ordering, cancellation, recovery, and text-only cleanup regressions |
| Slack external upload adapter | `services/external_channel/slack_events.py`, focused tests | `files.getUploadURLExternal`, known-length streamed body, ordered temporary IDs, one `files.completeUploadExternal` with channel/root thread/text | Sequential order, no completion after acquisition/stream failure, exact content length, one completion, rejection/ambiguity mapping |

- Dependency order: Define manifest and ranged-read contracts → implement Runtime iterator
  and preflight → persist manifest in action/reply intent → add provider upload operations
  → connect immediate one-attempt source → complete failure/recovery matrix.
- Pre-commit order: Resolve effective settings → require `upload_files` capability → stat
  every path without whole-file reads → require absolute regular files and positive bounded
  sizes → derive basename/media type → enforce per-file and aggregate limits → commit once.
- Provider order: For each manifest entry in order, acquire one Slack upload URL and stream
  exactly the expected bytes from Runtime in 1 MiB chunks. Stop on the first failure. Only
  after every stream succeeds, call `files.completeUploadExternal` once with ordered file
  IDs, conversational text, bound channel, and root thread.
- Outcome policy: Confirmed pre-completion rejection is failed; transport ambiguity during
  upload or completion is unknown; confirmed completion is delivered; no file-bearing
  provider mutation is retried. Text-only replies preserve the existing path.
- Final validation:
  - focused Ruff/format for all changed Python paths
  - focused Pytest for Tool/action repository/service, Runtime storage/iterator, Slack
    upload adapter, recovery, and existing text delivery
  - backend Pyright
  - repository pre-commit hooks and `git diff --check`
- Scope-drift check: Compare
  `git diff --name-status feature/channel-file-transfer-inbound...HEAD` against this phase.
  Remove Admin API/Web, testenv fake/E2E, living-spec edits, durable file staging, new
  delivery enums, upload-only behavior, parallel/resumable transfer, or unrelated changes.
