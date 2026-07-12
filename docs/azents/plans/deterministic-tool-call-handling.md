---
title: "Deterministic Tool Call Handling Implementation Plan"
created: 2026-07-12
tags: [backend, engine, worker, runtime, reliability, testing]
---

# Deterministic Tool Call Handling Implementation Plan

## Feature Summary

Implement the approved [Deterministic Tool Call Handling and Worker Handover](../design/deterministic-tool-call-handling.md) design as a stacked PR series. PostgreSQL becomes the sole active-tool-call authority; tool admission, completion, cancellation, and takeover reconciliation become deterministic; Redis active projections and deprecated Background protocol surfaces are removed.

## Stack

All branches are stacked in this order and merge front to back.

| PR | Title | Scope | Depends on |
| --- | --- | --- | --- |
| 1 | `tool-call-handling [1/8]: Design` | Approved architecture and test strategy | `main` |
| 2 | `tool-call-handling [2/8]: Implementation plan` | Phases, validation matrix, prerequisites, rollout | PR 1 |
| 3 | `tool-call-handling [3/8]: Durable execution protocol` | Ownership generation, deterministic event identity, atomic admission/completion, TERM barrier, takeover reconciliation | PR 2 |
| 4 | `tool-call-handling [4/8]: PostgreSQL live projection` | Remove Redis active state and reconstruct/broadcast active projections from PostgreSQL | PR 3 |
| 5 | `tool-call-handling [5/8]: Remove Background protocol` | Remove remaining Background fields, APIs, coordination metadata, protobuf surface, and tests | PR 4 |
| 6 | `tool-call-handling [6/8]: Validation` | Deterministic integration/E2E validation, evidence, drift audit, and discovered fixes | PR 5 |
| 7 | `tool-call-handling [7/8]: Spec promotion` | Spec review, Living Spec updates, design implementation marker, ADR proposal if required | PR 6 |
| 8 | `tool-call-handling [8/8]: Cleanup` | Delete this completed implementation plan and stale references only | PR 7 |

## Phase 1 — Durable Execution Protocol

### Data changes

- Add a durable Session execution ownership generation and expose it through the Session ownership acquisition boundary.
- Add `owner_generation` to active tool-call JSON state.
- Remove the obsolete `background` value from the active tool-call domain shape as part of the coordinated model transition.
- Use deterministic external identities for every client tool call and its single terminal result.
- Add a new migration for durable ownership-generation schema changes. Do not modify executed migrations.

### Engine and worker changes

- Commit completed tool-call events and active ownership before handler task creation.
- Add an admission barrier that is serialized with TERM observation.
- Finalize parallel calls independently and atomically append the result while removing that call's ownership.
- Reconcile durable calls, results, active ownership, and ownership generation before resumed model execution.
- Never re-execute prior-generation or pre-admission orphan calls; append `cancelled` instead.
- Use the same idempotent cancellation finalizer for shutdown, takeover, and duplicate recovery.
- Keep explicit user stop aligned with ADR-0052 while sharing deterministic result identity and durable reconciliation primitives.

### Tests

- Repository and engine transaction tests for admission and per-call completion.
- External-id uniqueness races across normal completion and cancellation.
- Full recovery matrix tests.
- TERM before admission, during execution, within grace, and after grace.
- Parallel partial-completion and duplicate-wakeup cases.

## Phase 2 — PostgreSQL Live Projection

### API and projection changes

- Stop writing active tool calls into Redis broker activity and `RedisLiveEventStore`.
- Keep active ownership only in `agent_runs.active_tool_calls`.
- Reconstruct current active `client_tool_call` live event shapes from the running AgentRun in REST `/live` responses so the frontend timeline contract remains stable.
- Broadcast active-call upsert/removal actions after the corresponding PostgreSQL commit without using Redis as state.
- Remove Redis client-tool-call input from user-stop cancellation candidate selection.
- Keep Redis streaming assistant/reasoning partial storage and Redis Pub/Sub delivery.

### Tests

- REST `/live` returns active calls when the Redis live hash is absent.
- Redis active entries are never written.
- WebSocket actions follow PostgreSQL commit ordering.
- User stop ignores stale Redis tool events and uses durable reconciliation.
- Redis TTL expiry and explicit key deletion do not affect active execution state.

## Phase 3 — Remove Background Protocol

### Runtime and engine changes

- Remove active-call `background` fields and live/spec projection metadata not already removed by Phase 1.
- Remove `RuntimeBackgroundOperationContext`, Runtime background metadata, `RuntimeOperationReceipt`, and `start_background_operation()`.
- Remove background serialization from the Runtime Coordination Store.
- Remove the Runner operation envelope and protobuf `background` field; reserve protobuf field number 7.
- Regenerate Runtime Control protobuf modules with the repository generator.
- Keep explicit Runner exec process lifecycle unchanged.

### Tests

- Runtime Control and Runner operation tests compile without Background fields.
- Protobuf generation is clean and field 7 remains reserved.
- Source scan finds no current-product Background tool symbols outside immutable history and executed migrations.
- Exec process tests continue to pass through `exec_command`/`write_stdin` observation.

## Phase 4 — Validation

### Deterministic validation environment

Extend existing test fixtures only where necessary to control these boundaries without timing-only sleeps:

- admission committed, handler not started;
- handler side effect recorded, result not committed;
- one of multiple parallel handlers completed;
- cancellation acknowledged or intentionally ignored;
- active worker terminated and replacement owner acquired.

The fixture records invocation count and an idempotency-neutral side-effect marker. It must not require external credentials.

### E2E primary validation matrix

| Behavior | Setup | Required assertion |
| --- | --- | --- |
| Normal tool | Deterministic immediate handler | One call, one result, empty active ownership |
| Parallel completion | Independently released handlers | Completed calls leave active state individually |
| TERM within grace | Release handler before timeout | Normal result, no cancellation result, no idle continuation |
| TERM timeout | Keep handler blocked | Best-effort cancel and exactly one cancelled result |
| Post-admission crash | Terminate before handler start | Invocation count zero, cancelled result one |
| Post-side-effect crash | Terminate before result commit | Side effect one, invocation one, cancelled result one, no retry |
| Stale active | Seed result plus active entry | Preserve result, remove active only |
| Orphan call | Seed call without result/active | Cancelled result, invocation zero |
| Duplicate recovery | Deliver repeated wake-ups | One result by deterministic external id |
| Redis loss | Delete live/activity keys | `/live` and recovery converge from PostgreSQL |
| User stop | Stop blocked handler | Interrupted run plus one cancelled result |
| Exec process | Start and later poll process | No Background completion injection |

### Evidence

Record in the validation PR:

- exact commands and commit SHA;
- local or CI environment description;
- test results and durations;
- redacted worker transition logs for TERM and takeover;
- REST history/live snapshots for Redis-loss scenarios;
- fixture invocation and side-effect counts;
- implementation-versus-design/spec comparison table.

### Failure policy

Core deterministic scenarios must fail rather than skip. Optional live Runtime/MCP checks may skip only when their declared prerequisite is absent. Any discovered correctness defect is fixed in the validation PR or moved to the responsible earlier phase followed by stack rebase.

## Phase 5 — Spec Promotion

Run `/spec-review` against the complete implementation.

Likely Living Spec updates:

- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/run-resume.md`
- `docs/azents/spec/domain/conversation.md`
- `docs/azents/spec/flow/agent-runtime-control.md`

Promotion must document:

- PostgreSQL active ownership and ownership generation;
- deterministic call/result identities;
- admission/completion transactions;
- TERM barrier and best-effort cancellation;
- takeover reconciliation matrix;
- PostgreSQL-backed active live projection;
- removal of current Background protocol surfaces.

Mark the design implemented only after validation passes. Determine during spec review whether the durable ownership and at-most-once recovery policy requires a new ADR. Existing adopted ADRs remain immutable.

## API and Client Impact

The preferred Phase 2 path preserves the current event-shaped `/live.partial_history` contract by synthesizing active events from PostgreSQL. If implementation requires a schema change instead, regenerate OpenAPI and both generated public clients; never edit generated clients manually.

Runtime protobuf generation is mandatory in Phase 3.

## Deployment and Rollout

- Deploy server, worker, Runtime Control, and Runner from the coordinated final stack.
- Reserve removed protobuf field number 7; do not add compatibility readers or legacy fallback.
- Existing Redis activity/live keys expire naturally and require no migration.
- Add only the new database migration required for durable ownership generation.
- Preserve Kubernetes termination grace margin for cancellation, persistence, lease release, and process teardown. Do not increase the worker wait in isolation.
- No feature flag is planned because mixed active-state authorities would undermine the invariant being introduced.

## Blockers and External Actions

No design blocker is open.

Potential implementation prerequisite:

- If current worker ownership acquisition cannot atomically increment a durable generation without coupling Redis and PostgreSQL transactions, Phase 1 must introduce a PostgreSQL ownership-generation claim before active admission. The generation remains observational and must not be expanded into write fencing without a new design decision.

No external credentials or manual provider setup blocks core implementation or validation.

## Cleanup

After implementation, validation, and spec promotion:

- delete this plan;
- remove stale plan references and temporary validation scaffolding not required for regression coverage;
- retain deterministic tests, current specs, adopted ADRs, and the implemented design record.
