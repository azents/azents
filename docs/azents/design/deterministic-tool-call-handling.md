---
title: "Deterministic Tool Call Handling and Worker Handover"
created: 2026-07-12
updated: 2026-07-12
implemented: 2026-07-12
tags: [architecture, backend, engine, worker, runtime, reliability]
---

# Deterministic Tool Call Handling and Worker Handover

## Summary

Azents will treat a completed foreground client tool call as durable run work owned by exactly one admitted run loop. PostgreSQL event transcript and `agent_runs` state form the execution authority. Redis remains a delivery, lease, and streaming-partial mechanism and no longer stores active tool-call truth.

Tool execution is admitted durably before a handler starts. Completion appends one deterministic terminal result and removes active ownership atomically. A worker that takes over a run reconciles durable calls, results, active ownership, and ownership generation before any model dispatch. Work left by a previous owner is never re-executed; it converges to `client_tool_result(status=cancelled)`.

Shutdown closes tool admission immediately, waits a bounded grace interval for admitted work, then requests cancellation on a best-effort basis. Both the shutting-down worker and takeover recovery use the same idempotent terminal-result identity.

The deprecated Background tool model and remaining Runtime background-operation protocol surface are removed. Runner-owned exec processes remain explicit resources observed through `exec_command` and `write_stdin`; they are not background tool calls.

## Goals

- Ensure every completed model-emitted client tool call is handled within its current run boundary.
- Prevent automatic re-execution of a tool whose prior execution outcome cannot be proven after worker loss.
- Make admission, completion, cancellation, and takeover deterministic from PostgreSQL state.
- Remove Redis active-tool-call state and stale-projection recovery decisions.
- Make graceful TERM behavior explicit and bounded.
- Make duplicate cancellation and recovery idempotent through deterministic event identity.
- Remove the deprecated Background tool and Runtime background-operation protocol surface completely.

## Non-goals

- Guarantee exactly-once effects in external systems.
- Add database-write fencing against a stale worker. Ownership generation is recovery evidence, not a write fence.
- Change user-stop semantics from ADR-0052. User stop remains a terminal run interruption; shutdown and handover remain non-terminal recovery boundaries.
- Add a separate `unknown` tool-result status. Unresolved takeover work is represented as `cancelled`.
- Automatically retry read-only or apparently idempotent tools after takeover.
- Treat Runner-owned exec processes as active background tool calls.
- Select a longer shutdown grace duration in isolation. Any duration change must preserve cancellation and teardown margin within the workload termination grace period.

## Terminology

- **Completed tool call**: a normalized `client_tool_call` with a complete name, call id, and arguments. Streaming function-call deltas are not executable calls.
- **Admission**: the durable transition that appends the call and records active execution ownership before handler creation.
- **Active ownership**: a PostgreSQL `agent_runs.active_tool_calls` entry proving that one ownership generation accepted responsibility for the call.
- **Ownership generation**: a monotonically increasing durable session execution generation assigned when a worker takes ownership. It distinguishes current-loop work from work left by a previous owner but does not fence writes.
- **Terminal result**: the one durable `client_tool_result` for a call, with status `success`, `error`, or `cancelled`.

## Durable State

### Event transcript

The event transcript records completed model output and terminal tool observations:

- `client_tool_call`
- `client_tool_result`

Each semantic call and result has a deterministic external identity scoped by run and call id:

- `tool-call:{run_id}:{call_id}`
- `tool-result:{run_id}:{call_id}`

All terminal statuses use the same result identity. Success, error, and cancellation must not use independent ids because that would permit more than one terminal result for one call.

### AgentRun active ownership

`agent_runs.active_tool_calls` is the only active-tool-call authority. Each entry contains:

- `call_id`
- `name`
- redacted or summarized `arguments`
- `started_at`
- `owner_generation`

The removed `background` field is not part of the model.

An active entry means the owning run loop durably admitted the call and may create its handler. It does not merely mean that the model emitted a call or that the UI displayed a partial call.

### Ownership generation

A worker acquisition increments a durable Session execution ownership generation. Newly admitted calls copy that generation into their active ownership entry. Recovery compares the current generation with the active entry generation.

This generation is observational recovery state. The design deliberately does not introduce stale-writer fencing. Correctness therefore continues to rely on the existing ownership lease, TERM barrier, graceful release, and takeover ordering.

## Admission Protocol

For all completed client tool calls in one model step, the run loop performs one admission transaction:

1. Append deterministic `client_tool_call` events.
2. Set the run phase to `executing_tools`.
3. Record every call in `agent_runs.active_tool_calls` with the current ownership generation.
4. Commit.
5. Only after commit, create tool handler tasks.

Parallel calls are admitted as one set before any member starts.

A crash after admission commit but before handler creation produces a false-positive cancellation during recovery. This is intentional: losing an execution that may not have started is safer than replaying an execution that may already have produced side effects.

A handler must never start before durable admission. The implementation needs a TERM-aware admission barrier so shutdown and handler creation cannot cross each other unnoticed.

## Completion Protocol

Each parallel call is finalized as soon as its handler reaches a terminal observation. Completion does not wait for unrelated parallel calls.

One completion transaction:

1. Append the deterministic `client_tool_result` if it does not already exist.
2. Remove that call from `agent_runs.active_tool_calls`.
3. Update the run phase when appropriate.
4. Commit.

If the result already exists, it wins and only stale active ownership is removed. A later success, error, or cancellation cannot replace an existing terminal result.

## TERM and Graceful Shutdown

TERM immediately closes the worker and session admission barrier:

- do not start new sessions;
- do not dispatch another model request;
- do not create a new tool handler;
- continue waiting only for work admitted before the barrier closed.

During the bounded graceful interval, a normally completing tool uses the ordinary completion transaction. Once the interval expires:

1. Cancel in-process tasks.
2. Request tool-, MCP-, or Runtime-specific cancellation when available.
3. Treat external cancellation as best effort and do not wait indefinitely for confirmation.
4. Converge unresolved admitted calls to the deterministic cancelled result.
5. Preserve recoverable PostgreSQL state if shutdown prevents finalization.

A call completed by the old worker and a cancellation attempted by the takeover worker share one result identity, so only one terminal observation is retained.

The configured wait must leave explicit time for cancellation requests, durable reconciliation, session/lease release, dependency teardown, and process exit before Kubernetes sends SIGKILL.

## Takeover Recovery

Recovery runs after ownership acquisition and before any model dispatch or tool handler creation. It loads:

- durable `client_tool_call` events;
- durable `client_tool_result` events;
- PostgreSQL active ownership entries;
- each active entry's ownership generation;
- the current ownership generation.

Redis live projections are not recovery input.

### Reconciliation matrix

| Durable call | Active ownership | Durable result | Ownership relation | Recovery action |
| --- | --- | --- | --- | --- |
| present | present | absent | current generation | Current run-loop work; do not recover as an orphan |
| present | present | absent | previous generation | Request best-effort cancellation, append `cancelled`, remove active ownership |
| present | present | present | any | Preserve result and remove stale active ownership |
| present | absent | absent | none | Pre-admission/orphan boundary; append `cancelled` without executing |
| present | absent | present | any | Normal terminal state |
| absent | present | any | invariant violation; never execute, remove invalid ownership, surface an internal consistency failure |

Recovery writes use the deterministic result identity and are safe under duplicate wake-ups. Before the next model request, the run must have neither previous-generation active entries nor durable tool calls without terminal results.

After reconciliation, the same non-terminal run may continue with the cancelled results in its transcript. Recovery does not add a user-stop `interrupted` marker and does not automatically terminate the run.

## User Stop

ADR-0052 remains authoritative for explicit user stop:

- user stop preempts the run;
- cancel requests are fire-and-forget/best-effort;
- unresolved foreground calls receive `cancelled` results;
- the run becomes `interrupted`;
- the next model input receives the existing interruption control event.

User-stop cancellation candidates come only from PostgreSQL active ownership and durable call/result reconciliation. Redis client-tool-call projections are not candidates.

Streaming assistant partial preservation remains a separate Redis-backed stop concern. Streaming reasoning and partial function calls are not promoted as executable work.

## Live State and Redis Boundary

### PostgreSQL-backed live state

The following `/live` fields are reconstructed from PostgreSQL:

- active tool calls from `agent_runs.active_tool_calls`;
- run phase, status, and retry state from `agent_runs`;
- Session run state from `agent_sessions`;
- pending input from `input_buffers`;
- Goal and Todo from `toolkit_states`;
- action execution projections from their durable repository.

To preserve the existing frontend timeline contract, the API may project PostgreSQL active entries into transient `client_tool_call` event shapes at read time.

### Redis-backed transient state

Redis retains only:

- streaming assistant partials;
- streaming reasoning partials;
- WebSocket Pub/Sub delivery;
- Session wake-up routing, ownership lease, and heartbeat.

Tool admission broadcasts `live_event_upserted` only after the PostgreSQL commit. Completion/cancellation broadcasts `live_event_removed` only after result and active removal commit. A missed Pub/Sub action converges through REST `/live` resync from PostgreSQL.

Remove active calls from both Redis state copies:

- `SessionActivity.active_tool_calls` in the broker activity key;
- `client_tool_call` entries in `RedisLiveEventStore`.

## Background Feature Removal

Remove all current-product Background tool surfaces:

- `ActiveToolCall.background` and live/spec fields;
- background task registry/toolkit and completion-input remnants;
- `RuntimeBackgroundOperationContext`;
- `RuntimeOperationReceipt` and `start_background_operation()`;
- Runtime operation and metadata `background` fields;
- Redis background metadata serialization;
- Runner envelope and protobuf `background` field;
- related tests and current Living Spec claims.

Historical adopted ADRs, implemented design records, and executed migrations remain immutable history.

Runner-owned exec processes remain explicit process resources. The `exec_command` call terminates with a process observation and optional process id. Later `write_stdin` calls observe the process. Process exit does not inject a background completion input.

## Failure Semantics

- External cancellation is best effort.
- External effects may have occurred before a cancelled result is recorded; Azents still represents the unresolved tool observation as `cancelled` and never automatically re-executes it.
- Loss of Redis live projection does not change execution or recovery decisions.
- Loss of a WebSocket action is repaired by REST resync.
- PostgreSQL persistence failure leaves the run recoverable and blocks the next model dispatch until reconciliation succeeds.
- Duplicate recovery and old/new worker cancellation races converge through deterministic event uniqueness.

## Observability

Structured logs should include:

- session id and run id;
- call id and tool name;
- owner generation and current generation;
- admission, completion, cancellation, and recovery transition;
- shutdown grace expiration;
- cancellation request outcome without treating best-effort failure as a server failure;
- invariant violation classification.

Logs must not include raw credentials or unredacted sensitive tool arguments.

## Test Strategy

### E2E primary validation matrix

| Scenario | Expected behavior | Evidence |
| --- | --- | --- |
| Normal foreground tool | One call, one terminal result, no remaining active ownership | History, `/live`, DB projection, worker logs |
| Parallel calls with staggered completion | Each completed result persists independently; only unfinished calls remain active | History ordering and active ownership snapshots |
| TERM during tool within grace | Normal result persists; no cancellation result or idle continuation | History and shutdown logs |
| TERM timeout | Best-effort cancel and one cancelled result, or equivalent takeover finalization | History and old/new worker logs |
| Crash after admission before handler | Takeover appends cancelled result and never invokes the handler | Fixture invocation count and history |
| Crash after external effect before result | Takeover appends cancelled result and does not retry | Side-effect marker count and history |
| Result committed with stale active ownership | Takeover preserves result and removes only active ownership | DB before/after evidence |
| Durable call without active ownership/result | Takeover appends cancelled result without execution | Fixture invocation count and history |
| Duplicate recovery wake-ups | Exactly one result event | External-id uniqueness evidence |
| Redis live key loss | `/live` restores active calls from PostgreSQL and recovery remains correct | Redis deletion plus REST snapshot |
| WebSocket event loss | REST resync converges to PostgreSQL state | Browser/network resync evidence |
| User stop during tool | Existing ADR-0052 interruption plus one cancelled result | History and run status |
| Exec process continuation | Process remains observable through `write_stdin` without Background completion | Tool observations |

### E2E plan

Use the existing Azents E2E environment with deterministic fixture tools capable of:

- blocking until released;
- recording invocation count and a side-effect marker;
- completing calls at independently controlled times;
- ignoring or acknowledging cancellation;
- triggering worker termination after a named durable boundary.

The test runner must be able to replace or terminate the active worker and wait for a different worker to acquire the Session. Evidence must capture redacted worker logs, REST history/live responses, and deterministic fixture counters.

### Fixture and prerequisite support

New fixture support is required because ordinary tools cannot deterministically crash a worker between admission, side effect, result append, and active removal. The fixture must expose boundary synchronization without relying on sleep-only timing. Kubernetes or Docker worker replacement support is required for takeover scenarios.

No external credentials are required for the core matrix. Optional live MCP/Runtime cancellation checks may use existing prerequisite snapshots but must not block deterministic correctness coverage.

### Unit and integration coverage

- Repository transaction tests for admission and completion atomicity.
- Event external-id uniqueness tests across success/error/cancel races.
- Recovery matrix tests for every call/active/result/generation combination.
- Supervisor tests for TERM barrier, grace completion, timeout cancellation, and teardown margin.
- REST `/live` and WebSocket projection tests with Redis active state removed.
- User-stop tests proving Redis tool projections are not cancellation input.
- Runtime protocol tests proving Background fields and APIs are absent.
- Redis-loss tests proving PostgreSQL remains authoritative.

### CI policy

All deterministic unit, integration, and E2E tests are required CI checks. Tests requiring an unavailable optional external provider may skip only when their declared prerequisite is absent; core PostgreSQL/Redis/worker-takeover scenarios must fail rather than skip.

## Rollout and Cleanup

The implementation ships as a coordinated server, worker, Runtime Control, and Runner update. Protobuf field number 7 is reserved after removing `RunnerOperationRequest.background`; no compatibility reader or legacy fallback is retained.

Short-lived Redis live/activity keys require no data migration. Existing `active_tool_calls` JSON objects are rewritten naturally by active run updates; a database migration is required only for the new durable ownership generation fields.

After validation, Living Specs for the execution loop, run resume, conversation live state, and Runtime Control are promoted. The implementation plan is deleted in the final cleanup phase.
