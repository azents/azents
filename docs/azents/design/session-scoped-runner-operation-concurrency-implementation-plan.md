---
title: "Session-Scoped Runner Operation Concurrency Implementation Plan"
created: 2026-07-10
updated: 2026-07-10
tags: [architecture, backend, runtime, performance, testing]
---
# Session-Scoped Runner Operation Concurrency Implementation Plan

## Feature Summary

Implement the approved [Session-Scoped Runner Operation Concurrency](session-scoped-runner-operation-concurrency.md) design and ADR-0098. Runtime Runner operations will carry common Session ownership, use per-owner FIFO queues with cross-owner round-robin scheduling, and enforce validated defaults of 10 active operations per Session, 10 active system operations, and 50 active operations per Runtime. Pending admission will be bounded, while termination and mandatory cleanup remain available through a dedicated control path.

## Scope and Boundaries

Included:

- common operation ownership in the Runner protocol and domain envelopes;
- bounded per-owner admission and fair Runner scheduling;
- independent control-path execution for termination and cleanup;
- ownership propagation from Session and agent-level callers;
- configuration, structured diagnostics, and deterministic validation;
- current-spec promotion after implementation evidence is complete.

Excluded:

- operation-type-specific capacity partitions;
- Skill projection scan deduplication or singleflight;
- Agent Runtime ownership changes;
- compatibility fallback for older operation payload ownership fields;
- frontend behavior changes.

## PR Stack

### PR 1 — Design

Records ADR-0098 and the approved detailed design. This PR changes no runtime behavior.

### PR 2 — Implementation plan

Records this phased plan, validation matrix, fixture needs, rollout constraints, and spec impact candidates. It is temporary and will be removed by the cleanup PR after spec promotion.

### PR 3 — Common ownership protocol and Runner scheduler

Introduce the scheduling identity and the authoritative Runner admission/scheduling implementation.

Runtime and protocol changes:

- add nullable common `owner_session_id` to `RunnerOperationRequest` and `RunnerOperationEnvelope`;
- remove duplicate scheduling ownership from process start/write payloads while retaining the termination target Session field;
- regenerate tracked Runtime Control protobuf bindings;
- replace the unbounded inbound operation handoff with direct, bounded scheduler admission;
- add per-Session and system FIFO queues, round-robin owner selection, per-owner active accounting, and Runtime-wide accounting;
- enforce defaults of 10 Session, 10 system, and 50 Runtime active ordinary operations;
- enforce pending defaults of 100 per owner and 1,000 per Runtime;
- return `operation_queue_full` at admission and `operation_timeout` for work that expires before execution;
- execute termination and mandatory cleanup through a separately bounded control path with default concurrency 4;
- add validated Runner configuration for all execution and pending limits.

Tests:

- common protobuf/domain ownership serialization;
- configuration defaults and invalid combinations;
- per-owner FIFO and cross-owner round-robin ordering;
- per-owner, system, and Runtime execution limits;
- both pending admission bounds and final overload results;
- deadline expiry without handler execution;
- termination during ordinary saturation;
- cancellation, shutdown, and generation replacement cleanup.

Dependency: PR 2.

### PR 4 — Caller ownership propagation and observability

Make every operation caller state its ownership explicitly and expose queue/execution diagnostics.

Runtime changes:

- require nullable `owner_session_id` in all server-side Runner operation client methods;
- propagate the invoking Session from model-visible process and file tools;
- propagate Session ownership from Skill projection lifecycle work, Session Project registration, Session Git worktree execution, and background operations;
- preserve each subagent's independent Agent Session ID;
- deliberately route Agent Workspace file management, Agent Project catalog refresh, and pre-Session Git ref preview through the system queue;
- preserve parent Session ownership through background completion and resume;
- add structured admission, scheduling, completion, timeout, and rejection logs;
- expose total/per-owner pending and active counts plus queue-wait and execution durations in Runner diagnostics.

Tests:

- required nullable ownership at every client boundary;
- Session-owned process, file, Git, Skill, Project registration, and worktree calls;
- system ownership for Agent-level callers;
- background and subagent ownership continuity;
- structured log and diagnostic fields;
- gRPC Control-to-Runner integration with common ownership.

Dependency: PR 3.

### PR 5 — Validation

Run deterministic integration/E2E validation and fix defects found by validation without changing current specs.

Validation work:

- execute the primary matrix below against one shared Runtime;
- record commands, environment, image revisions, structured-log evidence, and assertions;
- run Ruff, Pyright, and targeted Pytest suites for the Runner app, server app, and shared Runtime Control library; and
- compare implemented behavior strictly with the design, ADR, and current specs.

Dependency: PR 4.

### PR 6 — Spec promotion

Promote only behavior verified by PR 5 into the current specs.

Spec work:

- update `docs/azents/spec/flow/agent-runtime-control.md`;
- update `docs/azents/spec/flow/agent-execution-loop.md` only if overload results alter model-visible invocation semantics;
- record the strict implementation-to-spec comparison; and
- mark the design implemented after all required validation passes.

Dependency: PR 5.

### PR 7 — Cleanup

Remove this temporary implementation plan and any temporary validation-only references after implementation and spec promotion are complete. Do not include behavior changes.

Dependency: PR 6.

## Test Strategy

Deterministic E2E validation is the primary product-behavior gate. Unit and integration suites establish scheduler and protocol correctness before E2E runs. Required scenarios run in CI against repository-owned fixtures without external credentials; missing deterministic fixture support blocks validation rather than producing a skip. Optional live pressure checks are supplemental and may skip only when explicitly marked optional. Evidence records commands, revisions, structured logs, active and pending counts, queue timing, completion order, and final operation results.

### E2E Primary Validation Matrix

| Scenario | Setup | Expected result | Required evidence |
| --- | --- | --- | --- |
| Five Sessions saturate one Runtime | Five Sessions each submit 10 deterministic blocking ordinary operations | 50 ordinary operations become active; no Session exceeds 10 | active counts by owner and Runtime, release/completion assertions |
| One owner has a deep backlog | Session A queues more than its active allocation; Session B submits one short file operation | Session B starts without waiting for Session A's backlog to drain | scheduling order and queue-wait timestamps |
| Per-owner FIFO | One Session queues labeled operations while its slots are held | That Session's queued operations start in arrival order | ordered request IDs |
| System and Session fairness | Fill the system queue and at least two Session queues | System work stays at or below 10 and participates in round-robin scheduling | per-owner schedule sequence and active counts |
| Per-owner pending overload | Hold execution and submit more than 100 pending operations for one owner | Excess operation returns final `operation_queue_full` | final error payload and rejection counter |
| Runtime pending overload | Admit pending work across owners until the Runtime reaches 1,000 | Excess operation returns final `operation_queue_full` | Runtime pending count and final error payload |
| Pending deadline expiry | Queue a short-deadline operation behind held capacity | Operation returns `operation_timeout`; handler never starts | timeout event and absent execution-start record |
| Saturated user stop | Occupy all 50 ordinary slots, then terminate one Session | Termination starts through the control path without waiting for ordinary release | control active record and prompt process termination |
| Root and subagent isolation | Root Session and subagent Session share a Runtime | Each receives an independent 10-operation allocation | distinct owner IDs and active counts |
| Background ownership | Start background work from a Session and complete/resume it | Parent Session ownership remains stable end to end | request, completion, and resume correlation |
| Generation replacement | Queue operations, replace the Runner generation, reconnect | Old pending work is invalidated and is not replayed into the new generation | generation-specific final/cleanup evidence |
| Configuration override | Start a fixture Runner with non-default validated limits | Scheduler enforces the configured values | startup diagnostics and active-count assertions |

### Fixture and Prerequisite Support

Primary validation must be deterministic and must not depend on external credentials or live integrations.

Required fixture capabilities:

- one Agent Runtime shared by at least five independently addressable Agent Sessions;
- a deterministic blocking operation or synchronization primitive that can hold and release Runner handlers without consuming external services;
- request labels or IDs that make scheduling order observable;
- configurable Runner limits for focused low-cardinality tests;
- access to structured Runner and Control logs plus operation final results;
- a deterministic way to replace Runner generation for cleanup verification.

Prefer extending the existing Azents E2E Runtime fixture. Add testenv prerequisite support only if the current fixture cannot expose deterministic hold/release and generation replacement. Fixture setup must seed the Agent, shared Runtime, root Sessions, and subagent Session without requiring user credentials. Capture the exact server, Runner, and Runtime Control revisions used for evidence.

Optional live production-like pressure checks may supplement the deterministic suite but must never replace it. Missing optional infrastructure may skip only those explicitly marked live checks. Missing deterministic fixture prerequisites must fail or block PR 5 rather than silently skip required scenarios.

### Quality Checks by Phase

PR 3:

- `cd python/libs/azents-runtime-control && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`
- `cd python/apps/azents-runtime-runner && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`
- targeted server Runtime Control tests needed by protocol serialization.

PR 4:

- `cd python/apps/azents && uv run ruff check . && uv run ruff format --check . && uv run pyright`
- targeted tests for Runtime tools, Skill projection, workspace services, Project catalog, background operations, and Git worktrees;
- shared Runtime Control integration tests.

PR 5:

- repeat all affected project quality checks;
- run the deterministic E2E matrix;
- run `/code-review` and `/spec-review` through the shipping workflow;
- record failures, fixes, and final evidence in the PR body or an attached validation report.

## Blockers and External Actions

No design blocker is open.

PR 3 is blocked if protobuf generation cannot run from the repository-pinned toolchain. PR 5 is blocked until deterministic hold/release support exists in the E2E Runtime fixture. PR 6 is blocked until PR 5 records complete passing validation evidence. A coordinated deployment of server and Runner images is required because the internal ownership protocol intentionally has no legacy fallback; this is a rollout prerequisite, not an implementation blocker.

## Spec Impact Candidates

Primary:

- `docs/azents/spec/flow/agent-runtime-control.md`
  - common Session ownership;
  - 10/10/50 active defaults;
  - per-owner FIFO and round-robin fairness;
  - bounded pending admission and errors;
  - dedicated termination/cleanup control path;
  - queue and execution observability.

Conditional:

- `docs/azents/spec/flow/agent-execution-loop.md`
  - only if overload or timeout behavior creates a new model-visible tool observation contract beyond existing Runner failure handling.

No OpenAPI or generated public client change is expected.

## Rollout and Recovery

- Build and publish server and Runner images from the same protocol revision.
- Deploy Runtime Control/server components and Runtime Runner support as one coordinated release.
- Allow or trigger existing Runtime Runners to reconnect on the new generation before enabling production pressure validation.
- Start with defaults 10/10/50, pending 100/1,000, and control concurrency 4.
- Watch queue-wait percentiles, active/pending counts, queue rejection/timeout rates, Session initialization duration, and Runner CPU/memory.
- If resource pressure is unacceptable, lower configured execution limits without rolling back ownership or fairness semantics.
- Do not infer Runtime lifecycle changes or restart server/runtime resources solely from Runner pressure signals.

## Cleanup

After PR 5 verifies the implementation and PR 6 promotes current specs, PR 7 deletes this plan. Durable sources of truth remain the current specs, ADR-0098, the implemented design document, and code/tests.
