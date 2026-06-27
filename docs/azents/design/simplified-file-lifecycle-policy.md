---
title: "Simplified File Lifecycle Policy"
created: 2026-06-27
updated: 2026-06-27
tags: [architecture, backend, engine, scheduler]
---
# Simplified File Lifecycle Policy

## Purpose

This design replaces the more complex ADR-0046 follow-up direction for background file cleanup. The previous direction moved existing ExchangeFile, Artifact, and ModelFile cleanup into a scheduler, but it kept separate lifecycle policies for each kind, including run-age Artifact expiration and persistent ModelFile degradation stages.

The new direction simplifies the policy before implementation:

- **ModelFile** is context-owned. It is retained only while reachable from the current AgentSession head or pinned by an active run.
- **Artifact** is TTL-owned. It is a temporary file-access resource and expires by `expires_at`.
- **ExchangeFile** is TTL-owned. It is a temporary file-access resource and expires by `expires_at`.
- Runtime prompt guidance tells the agent that `exchange://` and `artifact://` resources are temporary. When the `import_file` tool is available, the agent should import files needed for later work into the runtime workspace.

This design intentionally does not introduce a generic `file_resources` base table in the first phase. The primary simplification is policy-level: remove run-age Artifact retention and persistent ModelFile degradation/age transitions from the cleanup contract.

## Goals

- Keep normal Agent run input preparation free from synchronous file lifecycle cleanup.
- Avoid scheduler scans that recalculate deletion eligibility for every session.
- Make ModelFile cleanup robust to compaction and head movement by tying it to the authoritative session head update path, not engine filters.
- Keep Artifact and ExchangeFile cleanup indexable by `expires_at`.
- Centralize lifecycle policy so resource services, lowerers, filters, and schedulers do not independently reimplement retention rules.
- Preserve historical metadata in transcripts while making expired/deleted blob access fail predictably.

## Non-goals

- Do not make `exchange://` or `artifact://` a long-term storage contract.
- Do not add a unified `file_resources` base table in this design phase.
- Do not make ModelFile an archive or original-file preservation layer.
- Do not infer entity ids from URI strings. URI remains a file-location address.
- Do not rely on engine context filters as the correctness path for deletion.

## Current Problem

The current lifecycle model has several independent policies:

- ExchangeFile expires by time.
- Artifact expires by run age.
- Image ModelFile degrades through persistent stages, then becomes unreachable, then deleted.
- Non-image ModelFile becomes unreachable by run age, then deleted.

Moving those policies into a scheduler still leaves three problems.

1. **Discovery cost**: run-based cleanup pushes the scheduler toward finding candidate sessions, looking up latest run indexes, and recalculating due resources.
2. **Filter fragility**: if deletion candidates are discovered by engine filters, compaction or head movement can make files disappear from the filter traversal before they are marked.
3. **Policy scattering**: creation, lowering, filtering, resolver access, and scheduler cleanup can each drift if they embed their own lifecycle rules.

## Decision

### D1. Split files into context-owned and TTL-owned resources

There are two lifecycle classes.

| Class | Resources | Retention owner | Cleanup trigger |
| --- | --- | --- | --- |
| Context-owned | ModelFile backing FilePart | AgentSession head reachability plus active run pins | Head movement candidate queue |
| TTL-owned | Artifact, ExchangeFile | Explicit `expires_at` | Scheduler `expires_at` index |

### D2. ModelFile is deleted when it is no longer head-reachable

ModelFile is a normalized model-input blob. It is not original storage. It is retained while either condition is true:

1. The current AgentSession head references a FilePart with that `model_file_id`.
2. An active run has pinned the ModelFile because the run may still materialize it for a model or tool boundary.

When neither condition is true, the ModelFile is deleteable. Deletion removes model-input blob access only; transcript metadata and bounded placeholders may remain.

This replaces persistent ModelFile lifecycle stages such as `jpeg:1024`, `jpeg:300`, `unreachable` grace, and run-age deletion as the primary cleanup policy.

### D3. ModelFile image resizing is request-local materialization

Persistent ModelFile degradation is removed from the cleanup policy. Image size, provider capability, request byte limits, and placeholder fallback are handled when constructing a provider request.

Request-local materialization may create a derivative blob or in-memory payload, but the derivative does not become a durable lifecycle state. If derivative caching is later added, the derivative must be tied to the same head/pin retention as its parent ModelFile.

### D4. Artifact expires by explicit TTL

Artifact is a temporary agent/tool file output addressable by `artifact://`. It is not long-term storage and no longer uses run-age retention.

Artifact creation computes and stores `expires_at`. Cleanup is:

```text
available Artifact where expires_at <= now -> expired -> blob delete pending
```

Expired Artifact metadata may remain in transcript history. `import_file artifact://...` fails with `expired` after expiry even if the physical blob still exists.

### D5. ExchangeFile continues to expire by explicit TTL

ExchangeFile remains a temporary user-agent file exchange resource addressable by `exchange://`. It expires by `expires_at`.

Expired ExchangeFile metadata and attachment cards may remain in history, but download, preview, import, and model materialization paths must treat it as unavailable.

### D6. Runtime prompt guidance explains TTL resources only when `import_file` exists

When a runtime exposes `import_file`, the prompt should include concise guidance:

```text
Files shared through exchange:// or artifact:// are temporary and may expire.
Do not rely on those URIs for long-term storage across future turns.
If a file should be kept for later work, import it into the runtime workspace using import_file and continue from the returned local path.
```

When `import_file` is not available, do not mention it. A minimal fallback can say that temporary file links may expire and the user may need to provide the file again.

### D7. Scheduler owns cleanup execution, not policy discovery

The scheduler executes bounded cleanup work from explicit queues/indexes:

- TTL cleanup for Artifact and ExchangeFile via `expires_at` indexes.
- ModelFile GC candidates produced by head movement.
- Blob deletion retry for rows whose access state is already terminal but physical deletion failed.

The scheduler must revalidate before deleting a ModelFile candidate:

```text
not referenced by current head
AND not pinned by an active run
AND not already deleted
```

## Data Model Direction

### Artifact

Add `expires_at` as the cleanup source of truth.

Keep or migrate existing fields only as display/history snapshots where needed. `expires_after_run_index` stops being the cleanup policy source.

Recommended index:

```text
artifacts(status, expires_at)
```

### ExchangeFile

ExchangeFile already has `expires_at`. Ensure cleanup uses an indexable query and does not run from Agent input preparation.

Recommended index:

```text
exchange_files(status, expires_at)
```

### ModelFile active references

Materialize current-head ModelFile reachability so cleanup never has to parse arbitrary event payloads during background scans.

Possible table:

```text
agent_session_model_file_refs
- session_id
- head_id
- model_file_id
- created_at
```

The table represents the current head's ModelFile references for one session. It is replaced transactionally when the session head changes.

### ModelFile GC candidates

Head movement enqueues candidates that were referenced by the previous head but are absent from the new head.

Possible table:

```text
model_file_gc_candidates
- model_file_id
- session_id
- reason
- created_at
- attempt_count
- last_attempt_at
```

The scheduler treats this as a hint and revalidates current reachability and pins before deletion.

### Active run pins

A run pins ModelFiles that it may still materialize. The pin prevents deletion during long-running model/tool execution even if compaction advances the head.

Possible table:

```text
model_file_pins
- model_file_id
- run_id
- session_id
- created_at
```

Pins are released when the run reaches a terminal state. A repair path can remove stale pins for terminal runs.

## Flow

### ModelFile creation

1. User input boundary or explicit file action creates FilePart.
2. ModelFile is created as normalized model-input storage.
3. The FilePart is written into canonical session content.
4. Session head reference extraction includes the `model_file_id` when that content becomes head-reachable.

### Session head update

All head movement paths go through one service boundary.

```text
SessionHeadService.update_head(session_id, new_head)
  -> extract ModelFile refs reachable from new head
  -> replace agent_session_model_file_refs for session
  -> enqueue old refs absent from new refs as GC candidates
  -> commit with head update
```

This applies to compaction, reset/new-head movement, and any future head rewrites.

### ModelFile GC

```text
Scheduler reads model_file_gc_candidates in bounded batches
  -> check current head refs
  -> check active pins
  -> if no refs and no pins: mark ModelFile deleted and try blob delete
  -> if still referenced/pinned: drop or defer candidate
```

Blob deletion failure is logged and retried. Access denial is controlled by ModelFile status, not by physical deletion success.

### Artifact / Exchange TTL cleanup

```text
Scheduler reads available rows with expires_at <= now in bounded batches
  -> mark expired
  -> try blob delete
  -> record blob_deleted_at on success
  -> retry failed blob deletion later
```

## Runtime Prompt Guidance

The runtime prompt assembly layer should conditionally include file TTL guidance when tool inventory includes `import_file`.

Guidance should be short and operational. It must not imply that `import_file` preserves user-facing download links permanently. It only copies the file into the runtime workspace so later agent work can continue from a local path.

When `import_file` is absent, do not instruct the model to call it.

## Access Semantics

- Expired Artifact and ExchangeFile access fails even if the blob remains due to delete retry failure.
- Deleted ModelFile rich input materialization fails or becomes a bounded placeholder.
- Transcript/event metadata is not removed solely because blob access expired.
- URI remains a file-location address. Entity references continue to use explicit ids.

## Migration Plan

### Phase 1. Design and policy centralization

- Add this design.
- Add `FileLifecyclePolicy` or equivalent constants for Artifact TTL, Exchange TTL, and ModelFile head-owned behavior.
- Remove new work on run-age Artifact cleanup and persistent ModelFile degradation cleanup.

### Phase 2. Artifact TTL conversion

- Add `artifacts.expires_at` if missing.
- Backfill existing Artifacts from current run-age fields using a conservative TTL from `created_at`.
- Make Artifact creation compute `expires_at`.
- Change Artifact resolver/lowerer to display TTL/expired status instead of run-age remaining count.

### Phase 3. Scheduler TTL cleanup

- Add scheduler job or extend existing periodic task to expire due Artifact and ExchangeFile rows by `expires_at`.
- Keep cleanup bounded and idempotent.
- Preserve blob delete retry with `blob_deleted_at` or equivalent marker.
- Remove Agent run input preparation calls that synchronously expire Artifact/ExchangeFile rows.

### Phase 4. ModelFile head reference index

- Centralize session head updates behind a service boundary if not already centralized.
- Add current-head ModelFile reference materialization.
- Add ModelFile GC candidate queue.
- Add active run pin creation/release around model request materialization and tool paths that need ModelFile blobs.

### Phase 5. ModelFile GC scheduler

- Process GC candidates in bounded batches.
- Revalidate current head references and active pins before deletion.
- Mark deleted before blob delete; retry blob delete failures.
- Remove persistent run-age ModelFile degradation/unreachable cleanup paths.

### Phase 6. Prompt guidance

- Add conditional runtime prompt guidance when `import_file` is in the available tool set.
- Add tests proving the guidance appears only with `import_file`.

### Phase 7. Spec sync and cleanup

- Update current specs for file exchange, agent execution loop, context compaction, and periodic execution.
- Update ADR-0046 through a new amendment or a new ADR, not by rewriting the implemented original decision body.
- Remove obsolete implementation-plan text that claims Artifact run-age and ModelFile degradation are current behavior after code changes land.

## Required Discussion Points

Only these points need explicit product/architecture confirmation before implementation.

### 1. Default Artifact TTL

Artifact changes from run-age retention to time TTL. We need choose an initial default.

Recommended default: **7 days**.

Rationale: long enough for normal follow-up work, short enough to make the temporary-resource contract credible. Large-file-specific shorter TTL can be added later if needed.

### 2. Default ExchangeFile TTL

ExchangeFile already has TTL semantics. We need confirm whether Artifact and ExchangeFile share a TTL or use separate defaults.

Recommended default: keep current ExchangeFile default if one exists; otherwise use **7 days** initially for both and tune by storage metrics.

### 3. ModelFile deletion aggressiveness

When head moves, ModelFile becomes deleteable after refs and pins disappear. We need decide whether to delete immediately or keep a short safety delay.

Recommended default: **no product-visible grace**, but scheduler processing is asynchronous. The GC candidate queue naturally creates a short operational delay, while active pins protect running work.

### 4. Runtime workspace durability wording

The prompt should say imported files are for later runtime work, but should not promise permanent retention beyond the runtime workspace lifecycle.

Recommended wording: "for later work" rather than "permanent" or "long-term archive".

## Trivial Decisions Taken

These do not need further discussion unless implementation reveals a constraint.

- Expired/deleted blob metadata remains in transcript history.
- Blob delete failure never re-enables access.
- Scheduler cleanup is bounded and retryable.
- URI parsing does not infer entity ids.
- Prompt guidance is conditional on `import_file` availability.
- ModelFile request-local resize failure produces a bounded placeholder or provider-capability fallback, not a persistent lifecycle state.

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Head ref extraction misses a ModelFile | Needed model input could be deleted | Extract refs from typed canonical FilePart fields, test every head update path, and revalidate before deletion |
| Active pin leak | ModelFile blob may not be deleted | Release pins on terminal run states and add stale-pin repair for terminal runs |
| Artifact TTL surprises users | Old `artifact://` imports may fail later | Add prompt guidance and expired-status metadata; tell agents to use `import_file` for files needed later |
| Runtime workspace misunderstood as permanent archive | Users may overtrust local paths | Prompt wording avoids permanent-retention claims |
| Request-local image resizing increases repeated work | More CPU on repeated calls | Add derivative cache later, tied to parent ModelFile lifetime |

## Test Strategy

### E2E primary verification matrix

| Behavior | Primary path | Expected result |
| --- | --- | --- |
| Artifact TTL guidance with runtime files | Start a session with `import_file` available and inspect model prompt/request journal | Prompt includes temporary URI guidance and `import_file` instruction |
| No `import_file` guidance without tool | Start a session where runtime file tools are unavailable | Prompt does not mention `import_file` |
| Artifact expiration | Create Artifact, advance time past `expires_at`, run scheduler, then call `import_file artifact://...` | Tool returns expired/unavailable error; transcript metadata remains |
| ExchangeFile expiration | Upload file, advance time past `expires_at`, run scheduler, then download/import | Access fails as expired; attachment metadata remains |
| ModelFile head GC | Send file input, compact or move head so FilePart is no longer reachable, run GC | ModelFile blob is deleted or marked deleted; history metadata remains |
| Active run pin safety | Keep a run active while head moves past its FilePart, run GC | ModelFile is not deleted until the run releases the pin |

### E2E plan

Use product/testenv E2E where available for upload, session run, compaction/head movement, and runtime tool behavior. Use deterministic backend integration tests for scheduler time travel, pin races, and deletion retry where product E2E would be slow or flaky.

### Testenv fixture/prerequisite support

Testenv needs fixtures for:

- A session with runtime file tools enabled.
- A session with runtime file tools disabled or filtered from tool inventory.
- File upload and Artifact creation with controllable `expires_at`.
- A compaction/head movement path that removes a FilePart from the current head.
- Mock object storage that can assert delete attempts and simulate delete failure.

### Fixture and seed requirements

- Workspace, user, agent, and session seed.
- Runtime workspace with file tools enabled for prompt guidance and `import_file` checks.
- Seeded Artifact and ExchangeFile rows with `expires_at` in the past and future.
- Seeded ModelFile/FilePart event content reachable from one head and unreachable from another.
- Active run row for pin safety tests.

### Credential/prerequisite snapshot requirements

No external live credentials are required. Object storage, model provider request journal, and runtime tools should use local test doubles or existing testenv services.

### Evidence format

PR verification should include:

- E2E command and result summary.
- Scheduler unit/integration test names for TTL cleanup, ModelFile GC, pin safety, and blob delete retry.
- Prompt/request journal excerpt showing conditional `import_file` guidance.
- DB assertion or log evidence that expired/deleted access is denied before physical blob deletion success is required.

### CI execution policy

- Unit and integration tests run in normal Python CI.
- Product E2E should run in the existing E2E job if the testenv already supports required fixtures.
- If new fixture support is not ready, add deterministic backend integration tests first and track product E2E enablement in the implementation PR.

### Skip/fail criteria

- Live external-provider tests are optional and skipped without credentials.
- Local deterministic scheduler and resolver tests must not be skipped.
- Any failure that allows expired/deleted blob access is blocking.
- Any prompt test that mentions `import_file` when the tool is unavailable is blocking.
