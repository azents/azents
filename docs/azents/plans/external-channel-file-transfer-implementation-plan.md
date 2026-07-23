---
title: "External Channel File Transfer Implementation Plan"
created: 2026-07-23
tags: [backend, engine, slack, external-channel, files, frontend, testenv]
---

# External Channel File Transfer Implementation Plan

## Source of Truth

- Requirements: [`files-260723/REQ`](../requirements/files-260723-external-channel-transfer.md)
- ADR: [`files-260723/ADR`](../adr/files-260723-external-channel-transfer.md)
- Design: [`files-260723/DESIGN`](../design/files-260723-external-channel-transfer.md)
- Requirements short ID: `files-260723`

This plan delivers provider-neutral External Channel file transfer with Slack as the
first provider. Inbound content remains metadata-only until the Agent explicitly
downloads one selected file into its Runtime. Outbound files extend the existing
`channel_action` reply and stream directly from Runtime to Slack without Exchange,
Artifact, ModelFile, or private durable staging.

Each implementation phase must add and follow its own phase execution plan before code
changes begin. The stack is created completely before CI monitoring begins, and no PR is
merged without explicit requester approval.

## Stack Shape

```text
main
← design/channel-file-transfer
← plan/channel-file-transfer
← feature/channel-file-transfer-foundation
← feature/channel-file-transfer-inbound
← feature/channel-file-transfer-outbound
← feature/channel-file-transfer-admin-e2e
← validate/channel-file-transfer
← docs/channel-file-transfer-spec
← cleanup/channel-file-transfer-plans
```

| PR | Branch | Base | Boundary |
| --- | --- | --- | --- |
| 1 | `design/channel-file-transfer` | `main` | Approved Requirements, ADR, and Design baseline |
| 2 | `plan/channel-file-transfer` | PR 1 | Multi-phase implementation and validation plan |
| 3 | `feature/channel-file-transfer-foundation` | PR 2 | Phase 1 — metadata, locators, capabilities, and limit contracts |
| 4 | `feature/channel-file-transfer-inbound` | PR 3 | Phase 2 — explicit inbound download Tool and Slack read adapter |
| 5 | `feature/channel-file-transfer-outbound` | PR 4 | Phase 3 — Runtime chunk streaming and one-outcome Slack file reply |
| 6 | `feature/channel-file-transfer-admin-e2e` | PR 5 | Phase 4 — Admin settings, Slack fake, and deterministic E2E |
| 7 | `validate/channel-file-transfer` | PR 6 | Full validation evidence and implementation/spec drift corrections |
| 8 | `docs/channel-file-transfer-spec` | PR 7 | Living-spec promotion and implemented snapshot markers |
| 9 | `cleanup/channel-file-transfer-plans` | PR 8 | Remove stale implementation and phase plans |

## Dependency and Parallelization Map

```text
Design baseline
  → implementation plan
    → foundation contracts
      → inbound download ─┐
      → outbound delivery ├→ Admin/E2E → validation → spec promotion → cleanup
                           ┘
```

The stacked Git history remains sequential even where implementation work can be split.
Within a phase, bounded workstreams may run in parallel only after the phase execution
plan fixes interfaces and assigns non-overlapping paths.

- Phase 1 is a hard dependency for all later phases because it owns normalized metadata,
  locator, capability, and effective-limit contracts.
- Phase 2 and Phase 3 consume Phase 1 contracts and are logically independent, but their
  PR branches remain sequential to preserve one reviewable stack and avoid shared Toolkit
  and provider-adapter conflicts.
- Phase 4 depends on both transfer directions and supplies the deterministic provider
  behavior required for the primary E2E journey.
- Validation, spec promotion, and cleanup are strictly sequential.

## Phase 1 — Foundation Contracts

- Branch: `feature/channel-file-transfer-foundation`
- Base: `plan/channel-file-transfer`
- Phase execution plan:
  `docs/azents/plans/external-channel-file-transfer-phase-1-foundation.md`

### Purpose

Establish all bounded provider-neutral contracts that later transfer operations consume,
without downloading or uploading file bytes.

### Boundary

- Project Slack `files[]` through HTTP, Socket, and hydration paths into one bounded
  normalized metadata shape.
- Persist supported and unsupported file metadata in existing revision JSONB.
- Create deterministic binding-scoped versioned locators and render one bounded `Files:`
  section consistently through first-turn lowering, replay, compaction continuity,
  Recent Transcript, structured visible values, and token accounting.
- Add independent `download_files` and `upload_files` connection capabilities derived
  fail-closed from Slack scope evidence.
- Add the provider-neutral External Channel file-limit System Settings section, database
  enum migration, typed defaults, validation, and runtime resolution.
- Define additive internal manifest and action input contracts needed by later phases,
  without enabling provider file mutations.

### Explicit Non-Goals

- No provider file download or Runtime destination write.
- No Runtime chunk reads or Slack external upload calls.
- No Admin Web settings card or deterministic end-to-end journey.
- No living-spec promotion.

### Data, API, and Runtime Impact

- Add one PostgreSQL `system_setting_section` enum value through a new migration.
- Extend existing JSON models only; add no attachment table or durable file storage.
- Add capability fields with absent legacy values interpreted as unavailable.
- Add the typed settings model and internal resolver; defer dedicated Admin API/UI
  representation to Phase 4.
- Keep generated clients unchanged unless an exposed schema must change in this phase;
  any required client changes must be produced by the repository generators.

### Test Strategy

- Projection and normalization tests for direct, external, Slack Connect, sparse,
  malformed, and truncated file entries.
- Renderer/lowerer/replay/continuity/token-accounting parity and secrecy tests.
- Locator parse/render and binding identity tests.
- Independent scope-to-capability validation tests.
- Migration, settings-definition, default, bound, and aggregate-invariant tests.
- Regression tests proving text-only messages and connections remain unchanged.

### Output for Later Phases

Stable metadata, locator, capability, settings, and manifest contracts with no file bytes
or provider URLs in persisted or model-visible state.

## Phase 2 — Explicit Inbound Download

- Branch: `feature/channel-file-transfer-inbound`
- Base: `feature/channel-file-transfer-foundation`
- Phase execution plan:
  `docs/azents/plans/external-channel-file-transfer-phase-2-inbound.md`

### Purpose

Allow the root Agent to explicitly materialize one selected supported Slack attachment at
one authorized Runtime path.

### Boundary

- Add the provider-neutral `download_external_file` Tool for active root External Channel
  bindings.
- Validate locator version/provider, current Agent and Session ownership, active binding,
  route, connection, and `download_files` capability before provider access.
- Add Slack `files.info` and authenticated private-file download operations.
- Reject external/remote, Slack Connect, sparse access-check, deleted, unavailable,
  unsupported, declared-oversize, and actual-oversize files.
- Buffer at most one configured inbound limit and write it atomically through the current
  run-scoped Runtime `FileStorage.put` path with existing overwrite behavior.
- Return bounded Tool results containing only Runtime path, filename, media type, and
  actual byte count.

### Explicit Non-Goals

- No multi-file inbound Tool call.
- No automatic materialization, Exchange, Artifact, ModelFile, or model file input.
- No outbound file publication.
- No chunked Runtime write protocol.

### Data, API, and Runtime Impact

- No new persistence entity or public Main Web API.
- Extend the External Channel Toolkit and run-scoped execution dependency wiring.
- Extend the Slack provider client with metadata and authenticated content reads.
- Reuse the Phase 1 effective inbound limit and capability contracts.

### Test Strategy

- Tool authorization and unrelated/inactive binding rejection.
- Missing capability and revoked/deleted/inaccessible provider results.
- Direct upload success, modified file-ID provider-authoritative behavior, and unsupported
  mode failures.
- Declared and streaming actual-byte limit enforcement.
- Destination validation, overwrite behavior, provider failure, and Runtime write failure.
- Tests proving no partial Runtime file and no durable Azents file object is created.

### Output for Later Phases

A complete explicit one-file inbound path available to deterministic E2E fixtures.

## Phase 3 — Outbound Streaming Reply

- Branch: `feature/channel-file-transfer-outbound`
- Base: `feature/channel-file-transfer-inbound`
- Phase execution plan:
  `docs/azents/plans/external-channel-file-transfer-phase-3-outbound.md`

### Purpose

Extend one explicit Channel reply with multiple Runtime files while preserving the
existing commit-before-provider-call and one-attempt outcome contract.

### Boundary

- Add optional `files` to both `channel_action` modes, limited to 20 absolute Runtime
  paths and requiring conversational text for file-bearing publication.
- Resolve run-scoped `FileStorage`, stat all paths before commit, require readable regular
  files, and enforce per-file and aggregate limits.
- Persist only a bounded file manifest in the existing action and `REPLY` delivery JSON.
- Add bounded 1 MiB Runtime chunk iteration beside whole-file `get()` and verify exact
  expected byte counts.
- Add Slack external upload URL acquisition, sequential direct Runtime-to-provider
  streaming, and one `files.completeUploadExternal` publication containing ordered file
  IDs, text, channel, and root thread.
- Map confirmed rejection, transport ambiguity, Runtime mutation/read failure, and
  completion outcomes to one existing reply delivery result without automatic retry.

### Explicit Non-Goals

- No upload-only Agent action.
- No parallel uploads, resumable uploads, durable staging, or recovery replay of a
  file-bearing attempt without its original Runtime source.
- No provider-visible partial text or file reply before all uploads succeed.
- No provider-specific administrator limit override.

### Data, API, and Runtime Impact

- Extend internal Tool/action/delivery JSON models additively.
- Extend run-scoped execution context access for download writes and outbound reads.
- Add bounded chunk reads using the existing Runtime Runner offset/max-bytes protocol.
- Keep `ExternalChannelDeliveryOperation.REPLY`; add no file-specific delivery enum.

### Test Strategy

- Tool schema and pre-commit path/stat/per-file/aggregate validation.
- Chunk iterator ordering, exact length, too-short, too-long, and read-failure tests.
- Sequential upload order and bounded-memory behavior without whole-file `get()`.
- No completion after a failed acquisition or stream.
- Exactly one completion after all streams, preserving file order and root thread.
- Confirmed failure versus ambiguous unknown classification and no automatic retry.
- Regression tests for unchanged text-only publication and cleanup delivery.

### Output for Later Phases

A complete file-bearing provider reply path suitable for Admin-controlled limits and the
primary deterministic E2E journey.

## Phase 4 — Admin Settings and Deterministic E2E

- Branch: `feature/channel-file-transfer-admin-e2e`
- Base: `feature/channel-file-transfer-outbound`
- Phase execution plan:
  `docs/azents/plans/external-channel-file-transfer-phase-4-admin-e2e.md`

### Purpose

Expose the provider-neutral policy to administrators and prove the complete Slack journey
with public/provider behavior and deterministic fixtures.

### Boundary

- Add dedicated Admin API serialization and mutation for the
  `external_channel_files` settings section.
- Regenerate Admin OpenAPI and Python/TypeScript clients through repository generators.
- Add an `External Channel files` Admin System Settings card with MiB inputs, effective
  byte values, version handling, direct save, and normal audit behavior.
- Extend the Slack fake with `files.info`, authenticated private downloads,
  `files.getUploadURLExternal`, byte-collecting upload URLs,
  `files.completeUploadExternal`, scope variation, missing/rejected files, size mismatch,
  and ambiguous completion.
- Add deterministic E2E for one invocation containing multiple direct Slack files, one
  selected inbound download, Agent processing, and one text-plus-multiple-file reply to
  the original thread.
- Exercise signed HTTPS `POST /external-channel/v1/slack/events` admission or the
  equivalent existing fixture entry point without writing External Channel database
  state directly.

### Explicit Non-Goals

- No live Slack credential requirement in mandatory CI.
- No direct testenv database seeding of External Channel domain state.
- No provider-specific settings UI or health-check workflow.
- No Todo Markdown support or separate upload-only UI.
- No living-spec promotion.

### Data, API, Frontend, and Testenv Impact

- Add Admin API schemas/routes only for the new typed setting section.
- Regenerate, never hand-edit, generated Admin clients.
- Update Admin Web System Settings composition without changing unrelated cards.
- Add provider fake state and evidence through supported API/provider boundaries.

### Test Strategy

- Admin API mutation, optimistic version conflict, audit, and effective settings tests.
- Generated client consistency checks.
- Admin Web format, lint, typecheck, component tests, and build, run sequentially where
  required.
- Slack fake operation and failure-mode tests.
- Deterministic primary E2E plus focused limit, scope, unsupported-mode, and ambiguous
  completion cases.

### Output for Later Phases

A user-manageable policy surface and deterministic end-to-end evidence for every primary
file-transfer behavior.

## Validation Phase

- Branch: `validate/channel-file-transfer`
- Base: `feature/channel-file-transfer-admin-e2e`
- Evidence document:
  `docs/azents/design/external-channel-file-transfer-validation-2026-07-23.md`

Run the complete planned command matrix, record environment and evidence, inspect fixture
prerequisites, and compare implementation strictly against the approved Requirements,
ADR, Design, and current living specs. Fix implementation defects or missing validation in
this PR. If an earlier phase boundary must be corrected, apply the fix to its responsible
branch and rebase all dependent branches with `--force-with-lease`.

The validation report must include:

- commands, environment, results, and deterministic E2E evidence;
- provider fake and prerequisite verification;
- requirement-by-requirement evidence;
- a table of implemented behavior versus current specs;
- discovered failures and fixes;
- accepted non-blocking risks; and
- explicit readiness or blocker status for spec promotion.

## Spec Promotion Phase

- Branch: `docs/channel-file-transfer-spec`
- Base: `validate/channel-file-transfer`

Run the repository spec-review workflow and update the current behavior in at least:

- `docs/azents/spec/domain/external-channel.md`;
- `docs/azents/spec/flow/external-channel-provider-ingress.md`;
- `docs/azents/spec/flow/external-channel-delivery.md`;
- `docs/azents/spec/flow/external-channel-lifecycle.md`;
- `docs/azents/spec/flow/file-exchange-storage.md`; and
- `docs/azents/spec/flow/agent-execution-loop.md` when the Tool/runtime path changes its
  documented execution behavior.

After complete verified implementation, add the same KST `implemented` date to the
Requirements and Design snapshots. Do not rewrite the accepted ADR. Any newly discovered
hard-to-reverse decision requires a new confirmed snapshot rather than modifying the
accepted `files-260723/ADR` record.

## Cleanup Phase

- Branch: `cleanup/channel-file-transfer-plans`
- Base: `docs/channel-file-transfer-spec`

Remove this implementation plan and all phase execution plans after specs are current and
the snapshot is marked implemented. Remove only stale plan references and generated index
entries; do not mix behavior changes, refactors, or further documentation redesign into
this PR.

## E2E Primary Validation Matrix

| User-visible behavior | Primary validation | Required evidence | Phase |
| --- | --- | --- | --- |
| Multiple inbound Slack attachments are separately visible as bounded metadata and locators | Deterministic Slack event-to-Agent input E2E | Captured Agent input without URLs or bytes | 4 |
| Unsupported external, Slack Connect, sparse, malformed, and truncated records fail closed but remain identifiable | Projection/service matrix plus focused E2E | Stable unsupported reasons and no transfer | 1, 4 |
| Receiving or replaying an attachment does not materialize bytes | Input/replay/compaction tests and E2E storage assertions | No Exchange, ModelFile, or Runtime file before Tool call | 1, 4 |
| Agent explicitly downloads only one selected file | Tool-to-provider-to-Runtime E2E | Provider calls and destination content for selected file only | 2, 4 |
| Locator use is scoped to the current active Agent, Session, binding, and connection | Authorization integration tests | Unrelated and disconnected attempts rejected before provider access | 2 |
| Slack remains authoritative for a modified accessible provider file ID | Provider adapter integration test | Same-binding request reaches Slack and follows Slack allow/deny result | 2 |
| Revoked scope, deleted file, unavailable file, and provider denial produce clear failures | Fake-provider failure matrix | Controlled Tool result and no partial destination | 2, 4 |
| Configured inbound actual-byte limit cannot be bypassed by metadata | Oversized fake response integration test | Transfer stops and destination is absent | 2, 4 |
| One Channel action publishes text with multiple Runtime files to the same root thread | Deterministic outbound E2E | Ordered uploads and one completion request | 3, 4 |
| Missing, unreadable, non-regular, oversized, or aggregate-oversized Runtime files fail before success | Tool/service integration matrix | No false delivered outcome or provider completion | 3, 4 |
| Upload or completion ambiguity produces one `unknown` reply without replay | Fake-provider ambiguity E2E | One attempt and one combined durable outcome | 3, 4 |
| Text-only External Channel replies remain unchanged | Existing and new regression E2E | Existing `chat.postMessage` path remains delivered | 3, 4 |
| Administrators can view and change provider-neutral limits with versioning and audit | Admin API/UI integration and browser/component tests | Effective values, version conflict, and audit evidence | 4 |
| Missing file scopes do not disable unrelated Slack text conversation | Connection validation integration test | Directional capability false; text capability remains active | 1, 4 |

## Fixture and Prerequisite Support

Mandatory deterministic CI requires:

- a Slack fake that exposes scope headers and the complete supported read/upload operation
  sequence;
- signed provider event ingress and hydrated message fixtures containing bounded direct,
  unsupported, and multiple file records;
- authenticated fake private-download bodies with declared/actual size control;
- upload endpoints that collect streamed bytes and record request ordering without
  requiring application-side whole-body fixtures;
- configurable confirmed provider rejection, transport ambiguity, missing file, scope,
  and size mismatch outcomes;
- Runtime fixtures that expose existing stat, bounded read, write, path authorization,
  and overwrite behavior; and
- assertions through public APIs, provider calls, Session events, and Runtime state rather
  than direct External Channel database writes.

Optional live Slack validation requires a dedicated App installed with the applicable
`files:read` and/or `files:write` bot scopes, channel membership, reachable HTTPS callback
configuration, and test files within workspace policy. Live credentials are never a
mandatory CI prerequisite, and absent optional credentials must produce a declared skip
rather than a false pass.

## Quality and Command Matrix

Commands are finalized in each phase execution plan after affected subprojects are known.
The expected full validation set is:

- Backend Python: Ruff, Pyright, focused unit/service/integration tests, migration tests,
  and deterministic E2E.
- Runtime/file storage: focused protocol/storage tests proving bounded chunk behavior.
- OpenAPI/clients: dump specifications and regenerate clients through repository
  generators; verify no manual generated edits.
- TypeScript: format, lint, typecheck, tests, and Admin Web build. Lint, typecheck, and
  build must not run concurrently.
- Documentation: generated docs index and snapshot validation through pre-commit.
- Repository: `git diff --check`, scope-drift comparison, and full pre-commit hooks before
  each PR.

## Blockers and External Actions

No repository implementation blocker is known.

- Existing Slack installations require the corresponding file scopes and reinstallation
  before each direction becomes available. This does not block deterministic CI or
  text-only behavior.
- Workspace policies or Slack limits can reject otherwise valid outbound files. Provider
  rejection remains a controlled file-bearing reply failure.
- A live HTTPS callback must target
  `POST /external-channel/v1/slack/events`; Socket Mode may be validated separately.
- The settings enum migration must be deployed before application code resolves the new
  section.

## Rollout and Rollback

- Apply the additive PostgreSQL enum migration before deploying code that reads the new
  setting section.
- Missing capability fields in existing JSON snapshots remain unavailable; text behavior
  remains active.
- New Slack App guidance requests both file scopes, while existing installations opt in
  independently.
- Existing messages without file metadata and text-only `channel_action` calls remain
  unchanged.
- Rollback leaves one unused enum value and additive JSON fields. No Channel file bytes or
  attachment rows require cleanup.
- Ambiguous provider mutations are not retried during rollout or rollback.

## Spec Impact Candidates

- External Channel ownership, capability, message metadata, and lifecycle invariants.
- Provider ingress projection and hydration behavior for bounded Slack files.
- Agent-visible rendering, Runtime Tool execution, and continuity behavior.
- Commit-before-call delivery with one-outcome multi-file Slack publication.
- File storage distinctions among External Channel transfer, Exchange, Artifact, and
  ModelFile.
- Provider-neutral System Settings and Admin management behavior.

## Cleanup Completion Criteria

Cleanup may remove the plan documents only after:

- all implementation and validation PRs exist in the stack;
- deterministic E2E and the full required command matrix pass;
- implementation/spec drift has been corrected;
- living specs describe current behavior;
- Requirements and Design share the verified `implemented` date; and
- the cleanup diff contains no executable behavior change.
