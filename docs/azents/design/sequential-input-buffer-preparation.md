---
title: "Sequential Input Buffer Preparation Design"
created: 2026-07-12
updated: 2026-07-12
tags: [architecture, backend, engine, api, frontend]
---

# Sequential Input Buffer Preparation Design

## Problem

The current input-buffer path combines queue draining with run creation and model-call boundaries. It claims compatible FIFO chunks, groups inputs by requested inference profile, promotes `action_message` envelopes into durable history, and may inject matching inputs into an already running AgentRun. Message-kind behavior, inference resolution, event append, action side effects, and turn continuation are therefore coupled in one service.

This creates several problems:

- FIFO correctness depends on chunk selection and worker ownership assumptions.
- Model target resolution is delayed until AgentRun activation even though the input message owns the override.
- Historical message inference fields require later run association or mutation to describe resolved state.
- TurnAction envelopes leak from queue storage into durable transcript history.
- Edit creates a special pending buffer even though it is an idle-only durable history rewrite.
- Processor failures, preparation-only actions, and active-run continuation cannot be represented by one boolean.
- The central service accumulates dependencies and branching for every buffer and action type.

## Goals

- Treat input-buffer processing as preparation for the next turn.
- Process exactly one durable FIFO item at a time until the queue is empty.
- Start or continue a turn only after the final empty-buffer check.
- Give each buffer/action kind an isolated polymorphic processor.
- Resolve model and effort overrides while processing the message that applies them.
- Store the current resolved inference configuration on AgentSession.
- Allow different turns in one AgentRun to use different models.
- Keep actual provider/model execution provenance internal and out of the chat UI contract.
- Preserve durable semantic events without equating persistence with model visibility.
- Make handled preparation failures durable, non-retryable, and non-blocking.
- Linearize input acceptance, FIFO processing, and turn claim through the AgentSession row lock.
- Remove deprecated or unnecessary buffer kinds and background execution infrastructure.

## Non-goals

- Do not add a new FIFO sequence column or Session sequence counter. UUIDv7 Buffer id ordering remains the queue order for this change.
- Do not redesign the existing frontend pending/live-state architecture.
- Do not expose physical provider/model identity in the chat UI.
- Do not preserve compatibility readers for removed `edited_user_message`, `background_completion`, or durable `action_message` behavior.
- Do not make third-party or dynamically registered input-buffer processors.
- Do not change unrelated FastAPI background jobs, asyncio implementation tasks, or Runtime exec process handling.

## Current Behavior

`InputBufferService.flush_session_input_buffers()` claims an ordered set with `FOR UPDATE SKIP LOCKED`, selects a profile-compatible prefix, promotes multiple buffers, appends events, associates input events with an AgentRun, and deletes the promoted rows. `RunExecutor` peeks at the first profile, creates or claims a run, resolves the run profile, and may poll matching buffers again between model calls.

`action_message` is currently both a queue envelope and a durable event. Goal and Skill actions append additional semantic events. Worktree execution is keyed by the durable action event. Edit rewrites history and then enqueues `edited_user_message`. Background completion has both worker-local and Runtime Coordination Store injection paths.

AgentSession stores last-used target and effort, while AgentRun stores requested and resolved inference provenance and assumes one resolved main model for the full run.

## Proposed Domain Model

### Supported InputBuffer kinds

The final supported storage kinds are:

- `user_message`
- `action_message`
- `goal_continuation`
- `agent_message`

`action_message` has a closed action discriminator:

- `goal`
- `skill`
- `create_git_worktree`

Remove:

- `edited_user_message`
- `background_completion`

`action_message` is buffer-only. It is never a durable transcript event.

### SessionInferenceState

AgentSession owns the resolved configuration prepared for the next turn:

- `current_model_target_label`
- `current_model_selection`
- `current_reasoning_effort`
- `current_effective_context_window_tokens`
- `current_effective_auto_compaction_threshold_tokens`
- `current_inference_resolved_at`

The domain projection is named `SessionInferenceState`. A newly created Session may have no state until its first model-bearing preparation resolves an explicit override or the Agent default. Once present, the state is complete except that effort may be null to represent provider/model default.

Rename message-level `requested_inference_profile` to `applied_inference_profile`. The internal event representation records the resolved configuration applied by that message. Public chat projection exposes only the target label and reasoning effort; it does not expose the physical model selection.

### AgentRun

AgentRun remains the multi-turn lifecycle for status, parentage, run indexing, terminal result, and internal recovery. It no longer owns one requested/resolved model profile. Different turns in the same AgentRun may use different SessionInferenceState snapshots.

Remove run-bound requested/resolved inference fields and inference-profile source from the authoritative run contract. Model output events retain internal adapter/provider/model facts where needed. A model invocation captures the current SessionInferenceState at its turn boundary; pending buffers do not modify Session state until the next boundary, so retry inside the current turn remains stable.

## Processor Architecture

### InputBufferDrainService

A shared orchestrator owns cross-kind behavior only:

1. Establish initial turn eligibility from whether an actual AgentRun is running at a between-turn boundary.
2. Lock the AgentSession and load the oldest Buffer by `id ASC` without `SKIP LOCKED`.
3. Dispatch the single Buffer to its concrete processor.
4. Fold the processor's TurnEffect.
5. Repeat until the durable queue is empty.
6. Under the final Session row lock, either claim/continue the next turn or transition the Session to idle.

The orchestrator does not inspect type-specific payload fields after dispatch.

### Processor contract

Use an explicit constructor-injected Protocol or equivalent interface:

```python
class InputBufferProcessor(Protocol):
    async def process(
        self,
        context: InputBufferPreparationContext,
        buffer: InputBuffer,
    ) -> InputBufferPreparationOutcome: ...
```

The closed processor registry selects by Buffer kind and, for `action_message`, by action discriminator. Registration is explicit application composition, not import-time global plugin registration.

Concrete processors:

- `UserMessageInputBufferProcessor`
- `GoalActionInputBufferProcessor`
- `SkillActionInputBufferProcessor`
- `CreateGitWorktreeActionInputBufferProcessor`
- `GoalContinuationInputBufferProcessor`
- `AgentMessageInputBufferProcessor`

### Preparation outcome

`InputBufferPreparationOutcome` contains a success/handled-failure classification and one TurnEffect:

- `eligible`: set accumulated eligibility to true.
- `neutral`: preserve accumulated eligibility.
- `failed`: set accumulated eligibility to false.

Fold items in durable FIFO order. Initialize the accumulator to true only for an actual running AgentRun at a between-turn boundary; `AgentSession.run_state = running` alone is insufficient.

Examples:

| Initial active run | Effects | Result |
| --- | --- | --- |
| no | `neutral` | no turn |
| no | `neutral, eligible` | start turn |
| yes | `neutral` | continue existing run |
| no | `eligible, failed` | no turn |
| no | `failed, eligible` | start turn |
| yes | `failed` | stop before another turn |

When the final effect prevents continuation at an active between-turn boundary, finalize the existing AgentRun as completed, append the typed preparation failure separately, and transition the Session to idle. A preparation failure is not a failed model run.

## Type-specific Processing

### user_message

A user message contains text/content parts, attachments, optional model override, and optional effort override.

Successful atomic preparation:

1. Combine overrides with current SessionInferenceState or Agent default.
2. Resolve the effective model selection and effort.
3. Materialize attachment/FilePart input as required.
4. Append one immutable `user_message` with `applied_inference_profile`.
5. Update SessionInferenceState to the same resolved configuration.
6. Delete the Buffer.
7. Return `eligible`.

A handled model/effort resolution failure appends a typed `system_error`, leaves SessionInferenceState unchanged, deletes the Buffer, and returns `failed`.

### action_message.goal

The action envelope is consumed and decomposed.

Successful atomic preparation:

1. Validate the objective and current Goal state.
2. Resolve and prepare the effective inference configuration.
3. Create the active Goal state.
4. Append `goal_updated`.
5. Append `user_message` containing the objective and applied inference profile.
6. Update SessionInferenceState.
7. Delete the Buffer.
8. Return `eligible`.

The lowerer independently decides the model representation of `goal_updated` and `user_message`. Neither event is model-facing merely because it is durable.

Validation or Goal-state failure follows the shared handled-failure rule and returns `failed`.

### action_message.skill

Successful atomic preparation:

1. Resolve the exact Skill from the active projection.
2. Snapshot the Skill body and source metadata.
3. Resolve and prepare the effective inference configuration.
4. Append `skill_loaded` containing only the Skill snapshot.
5. Append `user_message` when user-authored content is present; the message owns that content and applied inference profile.
6. Update SessionInferenceState.
7. Delete the Buffer.
8. Return `eligible`, including Skill invocation without additional user text.

The existing typed lowerers decide how `skill_loaded` and `user_message` enter model context. Skill lookup/validation failure returns `failed`.

### action_message.create_git_worktree

Worktree preparation is a long-running processor with durable `ActionExecution` state.

1. Atomically create or claim an ActionExecution keyed by source Buffer id.
2. Release DB locks before Runtime operations.
3. Validate source Project/ref and create the worktree through typed Runner operations.
4. Register the Session Project and refresh Agent Project catalog, Project status, and Skill projection.
5. Persist progress in ActionExecution tables and publish live projection updates.
6. Commit terminal `action_execution_result` as a durable UI/recovery event.
7. If user-authored text is present, resolve inference settings, append `user_message`, and update SessionInferenceState.
8. Consume the source Buffer at the terminal commit.

`action_execution_result` is UI-only and the event lowerer drops it. A generated `user_message` remains model-facing through its normal lowerer.

TurnEffect:

- successful worktree with user message: `eligible`
- successful setup-only worktree: `neutral`
- handled worktree failure: `failed`

A worktree preparation failure is final. Remove ActionExecution retry/discard behavior and its API/UI controls. Unexpected infrastructure interruption does not become a handled failure; the durable claim and Buffer remain recoverable.

### goal_continuation

Append one typed `goal_continuation` event, preserve SessionInferenceState, delete the Buffer atomically, and return `eligible`. Its typed lowerer produces the model continuation reminder.

### agent_message

Append one typed `agent_message` event, preserve SessionInferenceState, delete the Buffer atomically, and return `eligible`. Its typed lowerer produces the inter-agent model message.

Wake policy remains producer-owned. `spawn_agent` and `followup_task` wake the target; `send_message` may queue without waking. Once drained, the message is still eligible.

## Failure Semantics

Handled semantic failures are final preparation results:

1. Append one typed, user-safe `system_error` linked by deterministic Buffer-derived external id.
2. Do not commit intended domain side effects.
3. Do not update SessionInferenceState.
4. Delete the Buffer in the same result transaction.
5. Return `failed` and continue FIFO draining.

Preparation failure events are durable UI/recovery facts and are dropped by the model lowerer.

Unexpected database, Runtime transport, process, or programming exceptions propagate. Atomic work rolls back and retains the Buffer. Long-running worktree recovery resumes its durable ActionExecution claim. Unexpected errors are not converted into successful final failures.

## Concurrency and Transactions

### Producer protocol

Every producer uses AgentSession row lock as the queue linearization point:

1. `SELECT AgentSession FOR UPDATE`
2. validate producer-specific access and state
3. append Buffer
4. apply producer-specific run-state transition
5. commit
6. send wake-up if the producer owns wake behavior

Normal follow-up input remains allowed while running. Edit remains idle-only.

### Processor protocol

Atomic processors lock AgentSession and the FIFO head and commit semantic events, domain state, SessionInferenceState, and Buffer deletion together.

Do not use `FOR UPDATE SKIP LOCKED`. Redis ownership is routing, not the correctness mutex.

Worktree does not retain Session row locks during external work. Its ActionExecution claim keyed by Buffer id is the durable execution fence.

### Empty boundary

The final transaction locks AgentSession and checks the queue again. If a producer committed first, its Buffer is processed. If the final boundary commits first, later input belongs to the next between-turn boundary.

With an empty queue:

- eligibility true and active run: continue the same AgentRun with the current SessionInferenceState;
- eligibility true and no active run: create an AgentRun without model binding and start its first turn;
- eligibility false and active run: complete the AgentRun and set Session idle;
- eligibility false and no active run: create no AgentRun and set Session idle.

## Idempotency

### Acceptance

Producer acceptance owns duplicate semantics.

REST messages and TurnActions use `chat_write_requests` keyed by `(session_id, user_id, client_request_id)`. A retry validates write type and the full normalized payload. Matching retries return the same accepted target and authoritative snapshot; conflicts fail.

Internal producers define source identity only where their domain needs it. Remove generic `(session_id, kind, idempotency_key)` Buffer idempotency and payload comparison.

### Processing

Buffer id is the deterministic source identity. Derived outputs use stable ids such as:

- `<buffer-id>:user_message`
- `<buffer-id>:goal_updated`
- `<buffer-id>:skill_loaded`
- `<buffer-id>:action_execution_result`
- `<buffer-id>:failure`

Atomic processor rollback leaves no partial result. Worktree recovery reuses the Buffer-keyed ActionExecution claim.

## Edit Flow

Remove `edited_user_message` Buffer handling.

The REST edit transaction:

1. locks AgentSession;
2. requires idle state, no pending command, and no pending Buffer;
3. validates the editable target;
4. resolves the edit inference configuration;
5. soft-reverts target and later visible history;
6. appends the immutable replacement `user_message` with edit lineage and applied profile;
7. updates SessionInferenceState;
8. marks the Session running and records write idempotency;
9. commits, sends wake-up, and returns `history_reload_required = true`.

The frontend never renders an edited message as pending Buffer state.

## Pending Buffer Deletion

Delete mutates queue state only.

- Lock AgentSession and target Buffer.
- Delete only unclaimed pending work.
- Missing/already-consumed ordinary Buffer is idempotent success.
- A Buffer with active long-running ActionExecution claim returns processing conflict; action cancellation is not performed by pending delete.
- Do not change Session run state in the delete API.

The queued Runner cycle observes no pending/actionable work, creates no AgentRun, sets Session idle, and exits. Lost wake-up follows stale-running recovery.

## API and Frontend Changes

Keep the existing REST history/live taxonomy and pending Buffer UI architecture.

Required contract cleanup:

- remove `edited_user_message` and `background_completion` generated types;
- remove durable `action_message` history assumptions;
- keep pending `action_message` live projection;
- replace requested message profile naming with applied profile naming;
- remove run-level inference summary fields from public/live projections when they expose physical resolution;
- remove worktree retry/discard mutations and controls;
- regenerate OpenAPI clients rather than editing generated files.

Pending snapshots remain ordered by UUIDv7 Buffer id. Live upsert continues to identify buffers by id; stable existing-item replacement may be fixed separately without introducing a new sequence schema.

The UI does not display actual physical model execution provenance. It may show the applied target label and effort stored with a user message.

## Background Feature Removal

Remove the deprecated Background feature rather than porting it:

- BackgroundTaskRegistry and toolkit
- BackgroundTaskResultInjector
- background-completion publisher
- WorkerInputQueue used by completion delivery
- Runtime Coordination Store completion claim/publication APIs
- control-server publisher loop
- background Buffer/Event kinds and lowerers
- tests and `background-tool-call` product specification

Do not remove unrelated FastAPI background jobs, ordinary asyncio tasks, or Runtime exec/write-stdin behavior.

## Security and Permissions

- Existing workspace/session access checks remain mandatory before producer row locking and input acceptance.
- Human direct writes to subagent sessions remain rejected.
- Edit and pending delete retain current session ownership checks.
- Internal mailbox input remains reachable only through resolved SessionAgent relationships.
- Applied profile public projection allowlists target label and effort; integration ids, credentials, and physical model snapshots remain internal.
- Worktree validation continues to normalize Project paths and uses typed Runner operations rather than shell interpolation.

## Migration and Rollout

Use only new migrations; do not edit executed migrations.

Schema/data work includes:

1. Add Session current inference-state columns and backfill them from the existing Session last-used label/effort plus current Agent target configuration.
2. Rename/remove old Session last-used fields after backfill validation.
3. Remove AgentRun requested/resolved inference columns and related indexes/contracts.
4. Remove `edited_user_message` and `background_completion` Buffer enum values.
5. Remove `background_completion` Event enum value and stale rows.
6. Replace ActionExecution durable action-event identity with source Buffer identity.
7. Remove durable `action_message` production and migrate or remove historical envelope rows after preserving required ActionExecution source identity.
8. Remove generic Buffer idempotency key/index.
9. Remove retry/discard state and API surface that exists only for worktree preparation failure.

Before schema cutover, deployment must drain or verify zero pending `edited_user_message` rows; abort cutover rather than silently deleting an accepted edit replacement. Deprecated background pending data may be removed. No runtime compatibility fallback is added.

Deploy server/API/worker together because old workers do not understand the new processor contract or SessionInferenceState. Regenerate public clients and deploy frontend contract cleanup in the same release train.

## Observability

Add structured fields to processor logs and metrics:

- session id
- Buffer id and kind/action subtype
- processor name
- queue wait and processing duration
- TurnEffect
- handled failure code
- ActionExecution id for worktree
- whether the final boundary started, continued, or skipped a turn

Metrics should cover pending count/age, handled failure count by processor, unexpected processor errors, empty no-op Runner cycles, worktree claim age, and drain length.

## Test Strategy

### E2E primary verification matrix

E2E is the primary product-behavior evidence.

| Scenario | Expected evidence |
| --- | --- |
| Burst of normal messages during a run | FIFO durable user messages; queue empties; one subsequent turn uses the last applied Session profile |
| Model changes between turns in one AgentRun | Same run continues; next turn uses new SessionInferenceState; UI shows applied label/effort only |
| Final message profile resolution failure | Typed failure visible; Buffer removed; no turn; Session idle |
| Earlier failure followed by valid message | Failure persists; later eligible effect starts turn |
| Valid message followed by failure | Final failed effect suppresses turn |
| GoalAction success/failure | Correct Goal state/events and user message on success; final failure baseline on rejection |
| SkillAction success/failure | Skill snapshot plus non-duplicated user message; resolution failure is final and non-blocking |
| Setup-only worktree | Worktree and Project created; UI progress/result durable; no model turn without eligible input |
| Worktree with user message | Worktree prepared first; user message appended; turn starts with refreshed Project/Skill context |
| Worktree final failure | Durable final failure; no retry/discard; Buffer consumed; no turn when final effect |
| Goal continuation | Direct event append and eligible turn using unchanged Session inference state |
| Agent mailbox messages | Direct event append; producer wake semantics preserved; eventual eligible turn |
| Edit | No pending edit bubble; atomic history replacement; conflicting running/pending edit rejected |
| Delete before processing | Buffer disappears and no durable message is appended |
| Process wins delete race | Durable result remains; delete is idempotent; snapshot converges |
| Empty wake after deletion | No AgentRun created; Session returns idle |
| API retry and conflict | Same request returns same target; changed payload with same id fails |
| Worker takeover | FIFO head is not skipped; worktree claim is resumed, not duplicated |

### E2E plan

Extend the public chat E2E suite with deterministic model fixtures that expose received message order and chosen target/effort. Add controllable barriers for between-turn input, worktree completion, and processor failure. Assert REST history/live snapshots and user-visible timeline state, not only internal DB rows.

Run the matrix in CI against the standard Azents E2E environment. Scenarios requiring selectable model labels use fixture Agent target configurations rather than live provider credentials.

### Fixture and prerequisite support

Testenv needs:

- at least two deterministic model target labels with distinct observable identifiers;
- a processor-resolution failure target;
- a repository fixture suitable for worktree creation;
- a controllable Runner operation success/failure fixture;
- a session/run barrier that allows inputs to be accepted between turns;
- root/subagent fixtures for mailbox wake and no-wake paths.

No live external credentials are required for the mandatory matrix. If an optional provider smoke test is retained, it must skip only when its credential prerequisite snapshot is absent; product E2E failures must fail CI.

### Backend tests

- Processor unit tests for every success, handled failure, and unexpected exception path.
- Exhaustive registry tests for all Buffer kinds and action discriminators.
- TurnEffect fold table tests.
- Repository concurrency tests proving Session-lock serialization, FIFO head blocking, and atomic empty-boundary claim.
- REST idempotency tests for matching, conflicting, and cross-action retries.
- SessionInferenceState resolution/backfill tests.
- Worktree durable-claim recovery and final-failure tests.
- Migration tests for enum replacement, column backfill, and prohibited pending edit cutover.

### Frontend tests

- Existing pending-to-durable handoff tests remain.
- Remove edited/background/durable-action-message fixtures.
- Verify applied profile display without physical model identity.
- Verify worktree final failure has no retry/discard controls.
- Verify edit reload never renders a pending replacement.

### Evidence format and CI policy

Implementation PRs must include:

- backend Ruff, Pyright, and Pytest results;
- TypeScript format, lint, typecheck, and build results for affected workspaces;
- generated-client diff validation;
- E2E scenario names and CI job links;
- migration upgrade verification on a representative pre-change database snapshot.

Mandatory deterministic tests may not be skipped. Optional live-provider tests may skip only for a documented missing credential prerequisite; an available credential with a failing test is a CI failure.

## Implementation Phases

1. **Domain and schema foundation**
   - SessionInferenceState, TurnEffect/outcome ADT, enum removals, run schema changes, idempotency acceptance.
2. **Processor framework**
   - registry, orchestrator, direct atomic processors, failure contract, Session locking.
3. **TurnAction processors**
   - Goal, Skill, and durable worktree claim/finalization.
4. **Runner integration**
   - pre-turn drain, per-turn Session inference snapshot, empty-boundary turn claim, active-run continuation.
5. **REST producer and edit migration**
   - row-lock protocol, chat-write idempotency, direct edit, pending delete behavior.
6. **Background and legacy removal**
   - deprecated infrastructure, enum/event cleanup, worktree retry/discard removal.
7. **API/frontend/spec synchronization**
   - OpenAPI generation, minimal frontend contract cleanup, living specs.
8. **E2E and migration validation**
   - full matrix, takeover/race coverage, representative upgrade test.

## Alternatives Considered

### Keep compatible-profile chunks

Rejected because message semantics and profile boundaries remain coupled to queue storage.

### Create one AgentRun per model change

Rejected because Run is a multi-turn lifecycle and model selection is naturally per turn through Session state.

### Keep one conditional service

Rejected because each type has distinct dependencies, atomicity, and failure behavior.

### Add a per-session FIFO sequence

Deferred because it expands schema/API/frontend scope. UUIDv7 Buffer id ordering remains the current contract.

### Let delete update Session state

Rejected because SessionRunner already owns no-op wake and idle transition behavior.

## Open Questions

No blocking product decisions remain. Concrete class/module names may change during implementation while preserving the processor, transaction, TurnEffect, and SessionInferenceState boundaries in this design.
