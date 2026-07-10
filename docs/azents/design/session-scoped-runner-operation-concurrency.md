---
title: "Session-Scoped Runner Operation Concurrency"
created: 2026-07-10
updated: 2026-07-10
implemented: 2026-07-10
tags: [architecture, backend, runtime, performance]
---
# Session-Scoped Runner Operation Concurrency

## Problem

One Agent Runtime Runner serves every Agent Session attached to the Agent. The current Runner run loop applies one default limit of four active operations to the entire Runtime. Operations from unrelated root and subagent Sessions therefore contend for the same slots, while the transport can continue accumulating work in an unbounded queue.

This is especially visible during Session initialization. The Skill projection hook scans Runtime filesystem roots through `file.list` and `file.read`. Concurrent new Sessions repeat that scan while model-driven process and file operations use the same Runner. Long-yield `process.start` operations can occupy all four slots and delay short filesystem operations for unrelated Sessions.

## Goals

- Enforce a default limit of 10 active ordinary operations per Agent Session.
- Enforce a default safety ceiling of 50 active ordinary operations per Runtime.
- Schedule Session-owned and system work fairly without cross-Session head-of-line blocking.
- Preserve FIFO order within one owner queue.
- Keep termination and mandatory cleanup available when ordinary capacity is saturated.
- Bound pending work and return explicit overload and timeout results.
- Carry operation ownership through Control, gRPC, Runner, background completion, and diagnostics.
- Make queue wait distinguishable from execution time in production telemetry.

## Non-Goals

- Partitioning execution capacity by operation type.
- Deduplicating or single-flighting Skill projection scans.
- Changing Agent Runtime ownership; one Runtime remains Agent-scoped and shared by its Sessions.
- Introducing a legacy protocol fallback.
- Guaranteeing one global FIFO order across Sessions.
- Inferring Runtime lifecycle from Runner operation pressure or Runner process signals.

## Current Behavior

`RunnerRunLoop` accepts one `max_concurrent_operations` value, defaulting to four. It tracks active tasks globally and claims additional operations while global capacity remains. The gRPC client receives operation requests into one unbounded `asyncio.Queue`. The common `RunnerOperationEnvelope` and common protobuf request do not contain Session ownership. Only process start, process write, and process termination payloads carry `owner_session_id`.

Runtime Control relays requests to the connected Runner without waiting for operation completion. Consequently, a routed-operation log records transport delivery rather than execution start, and queued work is not attributable to a Session at the Runner scheduler boundary.

## Proposed Design

### Common operation ownership

Add optional `owner_session_id` to the common Runner operation request and `RunnerOperationEnvelope`. Remove duplicate ownership fields from process start and process write payloads. Process termination continues to identify its target Session as control-plane command data rather than scheduling ownership.

Every Runtime operation client method accepts `owner_session_id: str | None` as a required nullable argument:

- Session-owned callers pass the invoking Agent Session ID.
- Background operations retain their durable parent Session ID.
- Subagents pass their own Agent Session ID and receive an independent allocation.
- Agent-level operations with no Session pass `None` and enter the Runtime system queue.

Known system-queue callers include Agent Workspace file management, Agent Project catalog refresh, and pre-Session Git ref preview.

### Owner queues

The Runner maintains one pending FIFO queue per Session owner and one system queue. It also maintains active counts per owner and globally.

Default ordinary execution limits are:

| Scope | Default |
| --- | ---: |
| Agent Session | 10 |
| System queue | 10 |
| Runtime total | 50 |

Process, file, and Git operations share these limits. No capacity is reserved by operation type.

### Round-robin scheduling

The scheduler visits owner queues in round-robin order. An owner is eligible when:

- it has pending work;
- its active count is below its owner limit; and
- the Runtime active count is below 50.

The scheduler skips an ineligible owner and continues to other owners. Dispatching one operation advances the round-robin cursor. Completion decrements active counts and wakes scheduling. Empty inactive queues are removed.

FIFO is guaranteed only within one owner queue. Cross-owner execution order is intentionally fair rather than globally FIFO.

### Control path

Session termination and mandatory Runner shutdown cleanup do not use ordinary owner queues. They execute through a separately bounded control path and do not consume the ordinary 10/50 slots. This ensures user stop and cleanup remain available when long ordinary operations saturate the Runtime.

The control path has a default concurrency of 4, allowing independent Session terminations to proceed concurrently while keeping cleanup pressure bounded. The limit is configurable and must be positive. The control path is restricted to explicit termination and mandatory cleanup operations; it is not a general priority mechanism for user operations.

### Pending admission

Default pending limits are:

| Scope | Default |
| --- | ---: |
| Per Session or system queue | 100 |
| Runtime total | 1,000 |

An operation that exceeds either bound receives a final `operation_queue_full` error. Control does not retry this result automatically. The Runner never silently drops an admitted operation.

Admission occurs at the Runner transport receive boundary, before an operation enters any unbounded intermediate queue. The gRPC receiver hands each decoded envelope directly to the scheduler admission API, which atomically checks per-owner and Runtime pending counts, enqueues accepted work, or emits the final rejection event. The current unbounded `GrpcRunnerControlClient` operation queue is removed rather than retained in front of the bounded owner queues. Transport flow control may delay delivery, but delivered work cannot accumulate outside the configured pending accounting.

### Deadline, cancellation, and generation behavior

An admitted operation retains its existing end-to-end `deadline_at`. Before execution, the scheduler checks the deadline. Expired pending work receives `operation_timeout` without consuming an active slot.

Runner disconnection, cancellation, and generation fencing invalidate affected pending work consistently with active work. Reconnection does not replay a stale generation's in-memory queue.

### Configuration

Runner configuration exposes:

- per-Session active limit;
- system active limit;
- Runtime active limit;
- per-owner pending limit; and
- Runtime pending limit; and
- control-path active limit.

Defaults are 10, 10, 50, 100, 1,000, and 4 respectively. Configuration validation requires positive values, owner active limits no greater than the Runtime active limit, and pending limits no smaller than their corresponding active limits.

### Observability

Structured logs and Runner diagnostics distinguish transport routing, queue admission, scheduling, execution, and completion. They include:

- request ID, Runtime ID, Runner generation, and ownership class;
- owner Session ID where permitted by the existing logging policy;
- total and per-owner pending counts;
- total and per-owner active counts;
- queue wait duration and execution duration; and
- queue rejection and pre-execution timeout counts.

Session ownership identifiers remain operator diagnostics and are not exposed in model-visible tool output.

## Error Handling

| Condition | Result |
| --- | --- |
| Per-owner pending limit exceeded | `operation_queue_full` |
| Runtime pending limit exceeded | `operation_queue_full` |
| Deadline expires while pending | `operation_timeout` |
| Stale Runner generation | existing generation error semantics |
| Runner route unavailable | existing unavailable semantics |
| Operation handler failure | existing typed final operation error |

Overload and timeout remain tool observations. They do not become assistant/system failures, and they do not trigger Runtime lifecycle changes.

## Security and Isolation

Control constructs and forwards the common ownership field from trusted server-side Session context. The Runner uses it only for scheduling and diagnostics, not as authorization proof. Existing service and tool authorization remains authoritative.

Agent-level callers must deliberately pass `None`; required nullable client parameters prevent accidental omission. Session-scoped callers must not downgrade themselves to the system queue.

## Rollout

The protobuf, shared runtime-control library, Control server, Worker callers, and Runner move together as one internal protocol transition. There is no compatibility fallback for old process payload ownership fields. Deployment must update server and Runner images as a coordinated release and allow existing Runtime Runners to reconnect on the new generation.

Rollout telemetry should compare:

- queue wait percentiles by ownership class;
- active and pending counts;
- `operation_queue_full` and `operation_timeout` rates;
- Session initialization hook duration; and
- Runner CPU and memory utilization.

If the higher Runtime ceiling creates unacceptable resource pressure, operators can lower configured limits without reverting the ownership protocol or scheduler.

## Test Strategy

### Unit tests

- Common ownership serialization and deserialization for every operation family.
- Required nullable ownership at Runtime operation client call sites.
- Per-owner and Runtime active accounting.
- Per-owner FIFO and cross-owner round-robin behavior.
- Temporarily ineligible owner skipping and wake-up after completion.
- System queue limit and fair scheduling.
- Pending admission at both bounds.
- Deadline expiry before execution.
- Cancellation, disconnection, and generation replacement cleanup.
- Termination and mandatory cleanup while all ordinary slots are occupied.
- Configuration default and validation behavior.
- Queue and execution telemetry fields.

### Integration tests

- gRPC propagation of common ownership through Control and Runner client.
- Background operation ownership through completion publication and resume.
- Session-owned file, process, Git, Skill projection, and worktree operations.
- Agent-level Workspace, catalog refresh, and Git preview operations entering the system queue.

### E2E primary validation matrix

| Scenario | Expected result |
| --- | --- |
| Five Sessions share one Runtime and each submits 10 blocking operations | Up to 50 ordinary operations become active; each Session remains capped at 10 |
| One Session has a backlog while another submits a short file operation | The second Session is scheduled without waiting for the first backlog to drain |
| System queue and Session queues are active together | System work is capped at 10 and participates fairly |
| Runtime pending capacity is exceeded | Excess request returns `operation_queue_full` |
| Pending request deadline expires | Request returns `operation_timeout` without handler execution |
| User stops a saturated Session | Termination executes through the control path and is not blocked by ordinary capacity |
| Root Session and subagent Session share a Runtime | Each receives an independent 10-operation allocation |

E2E evidence consists of structured Runner logs and assertions over active counts, queue wait, completion order, and final tool results. Tests should use deterministic blocking test operations rather than external credentials or live integrations.

### Fixtures and prerequisites

Extend the existing Azents E2E Runtime fixture only if it cannot deterministically hold and release Runner operations. No external credentials are required. The fixture must expose a shared Agent Runtime with at least five Sessions and deterministic synchronization points for saturation and release.

Mandatory local and CI checks cover the affected Python applications and shared library with Ruff, Pyright, and targeted Pytest suites. Optional live-environment pressure checks must be reported separately and must not replace deterministic CI coverage.

## Spec Impact

After implementation and validation, update `docs/azents/spec/flow/agent-runtime-control.md` with common operation ownership, dual concurrency limits, fair scheduling, bounded pending admission, and control-path termination. Update the execution-loop spec only if model-visible overload behavior or tool invocation semantics change.
