---
title: "External Channel File Transfer Phase 4 Execution Plan"
created: 2026-07-23
tags: [admin, api, frontend, slack, external-channel, files, e2e]
---

# External Channel File Transfer Phase 4 Execution Plan

## Phase Execution Plan

- Phase: `4 — Admin settings and deterministic E2E`
- Branch/base: `feature/channel-file-transfer-admin-e2e` →
  `feature/channel-file-transfer-outbound`
- PR boundary: Expose the provider-neutral file policy through direct-save Admin
  settings, extend the credential-free Slack provider fake for inbound and outbound file
  operations, and verify the complete Slack file-transfer journey through supported
  public/provider boundaries.
- Inputs: Approved `files-260723` Requirements/ADR/Design, the multi-phase plan, and the
  Phase 1–3 metadata, settings, Runtime, Tool, and Slack transfer contracts.
- Deliverables: Dedicated Admin detail/patch API, regenerated Admin clients, an
  independent Admin Web settings card, deterministic Slack file scenarios and sanitized
  evidence, and primary/failure-mode E2E coverage.
- Non-goals: Candidate validation or health checks for local file policy, provider-specific
  policy overrides, live Slack credentials in mandatory CI, direct test database writes,
  Todo Markdown, living-spec promotion, validation reporting, and cleanup.
- Interfaces: `external_channel_files` remains a direct-activation System Setting;
  administrators edit MiB values while the API stores and returns bytes; Slack events
  remain admitted through `HTTPS POST /external-channel/v1/slack/events`; fake evidence
  excludes credentials, URLs, filenames, message content, and file bodies.

| Workstream | Owned paths | Output | Validation |
| --- | --- | --- | --- |
| Admin API | `api/admin/system_setting/v1`, focused route tests | Redacted detail and optimistic partial patch for inbound per-file, outbound per-file, and outbound aggregate byte limits | Serialization, direct mutation, null/range/aggregate validation, version conflict, and audit behavior |
| Generated clients | Admin OpenAPI, Python Admin client, TypeScript Admin client | Generator-produced operations and models for the dedicated settings endpoints | OpenAPI generation, Python client generation checks, TypeScript client generation and typecheck |
| Admin Web | `typescript/apps/azents-admin-web` System Settings feature and tRPC router | Independent direct-save card with MiB inputs, effective bytes, current version, loading/error/dirty/save states | Format, lint, typecheck, component-level state coverage where supported, and build |
| Slack fake | `testenv/azents/e2e/src/support/slack_provider_fake.py` and contract tests | Configurable file metadata/download/upload/completion behavior and content-free size/order/text-presence evidence | Focused fake tests for success, scope, missing/rejected files, size mismatch, and ambiguous completion |
| Deterministic E2E | External Channel public E2E journey and model proxy support | Multiple inbound metadata entries, one explicit Runtime download, Agent processing, and one text-plus-multiple-file reply to the original thread | Primary success journey; focused service and fake tests retain limit, unsupported mode, missing-scope, rejection, size-mismatch, and ambiguity coverage |

- Dependency order: Add and test the Admin API → regenerate Admin clients → add tRPC and
  direct-save UI → extend the Slack fake and its contract tests → add deterministic E2E
  model/provider scenarios.
- Admin save behavior: Convert administrator-entered whole MiB values to bytes, send all
  edited limits with the current `admin_version`, activate directly, invalidate detail and
  audit queries, and retain the draft on failure so conflicts can be corrected after
  reload.
- Slack fake behavior: Serve bounded direct-upload metadata and authenticated private
  bytes; acquire one deterministic upload URL per outbound file; collect bytes without
  exposing them in evidence; complete once with ordered file IDs and thread metadata.
- E2E behavior: Configure provider state through `__testenv/configure`, create the
  connection/binding through public APIs and user flows, submit a signed event through
  the existing Slack callback boundary, and assert sanitized provider and Tool history
  evidence without direct database mutation.
- Final validation:
  - focused backend Ruff/format, Pytest, and Pyright
  - Admin OpenAPI and generated Python/TypeScript client consistency
  - Admin Web format, lint, typecheck, tests, and build run sequentially
  - Slack fake focused Pytest
  - deterministic External Channel E2E selections
  - repository pre-commit hooks and `git diff --check`
- Scope-drift check: Compare
  `git diff --name-status feature/channel-file-transfer-outbound...HEAD` against this
  phase. Remove living-spec promotion, validation reports, stale-plan cleanup, live-only
  credential dependencies, direct database writes, provider-specific policy, or unrelated
  refactors.
