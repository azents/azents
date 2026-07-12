---
title: "Deterministic Tool Call Handling Validation Report"
created: 2026-07-12
tags: [agent, engine, runtime, testing]
---

# Deterministic Tool Call Handling Validation Report

## Scope

This report validates the implementation of [Deterministic Tool Call Handling and Worker Handover](deterministic-tool-call-handling.md) through the durable execution, PostgreSQL live projection, and Background protocol removal phases.

The validation uses deterministic repository, engine, worker, REST projection, Runtime Control, and Runner integration tests. It does not use timing-only sleeps or external credentials.

## Environment

- Python: CPython 3.14.6
- Database fixtures: testcontainers PostgreSQL and Redis where required
- Runtime Control protobuf: regenerated from `proto/azents/runtime_control/v1/runtime_runner_control.proto`
- External providers or credentials: none

## Commands and Results

| Project | Command | Result |
| --- | --- | --- |
| Azents backend | `cd python/apps/azents && uv run ruff check .` | Passed |
| Azents backend | `cd python/apps/azents && uv run ruff format --check .` | Passed |
| Azents backend | `cd python/apps/azents && uv run pyright` | Passed with 0 errors |
| Azents backend | `cd python/apps/azents && uv run pytest -q` | 1196 passed, 365 skipped |
| Runtime Control | `cd python/libs/azents-runtime-control && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q` | Passed; 31 tests passed |
| Runtime Runner | `cd python/apps/azents-runtime-runner && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q` | Passed; 42 tests passed |
| Protobuf generation | `cd python/libs/azents-runtime-control && uv run python scripts/generate_proto.py` | Passed; generated Runner descriptor reserves field 7 |

The skipped backend tests are existing optional or environment-specific tests. No deterministic tool-call correctness test was skipped.

## Validation Matrix

| Behavior | Deterministic evidence | Result |
| --- | --- | --- |
| Normal foreground tool | Engine execution tests assert one durable call, one result, and empty active ownership after completion | Passed |
| Parallel completion | `test_parallel_calls_finalize_independently` releases calls independently and observes per-call active removal | Passed |
| Admission closed by TERM | `test_closed_admission_barrier_prevents_call_and_handler_start` records zero handler starts and no admitted ownership | Passed |
| TERM after admission within grace | `test_term_after_admission_keeps_normal_result_and_run_recoverable` preserves the normal terminal result | Passed |
| Cancellation after admission | `test_shutdown_tool_cancellation_repairs_before_reraising` converges unresolved calls to deterministic cancellation | Passed |
| User stop during tool | `test_tool_user_stop_appends_cancelled_result_and_interrupts` and user-stop finalizer tests assert one cancellation result and interrupted run state | Passed |
| Previous-owner active call | Recovery tests request best-effort cancellation, append the deterministic cancelled result, and do not execute the handler | Passed |
| Durable orphan call | `test_orphan_tool_call_without_state_is_cancelled_before_lowering` appends cancellation with zero execution | Passed |
| Result with stale active ownership | `test_stale_active_entry_with_result_is_removed_without_replacement` preserves the result and removes ownership only | Passed |
| Duplicate completion/recovery | Repository external-ID uniqueness and recovery tests retain one terminal result identity | Passed |
| Redis active-state loss | REST live-state tests reconstruct active calls from `agent_runs.active_tool_calls` without a Redis live hash | Passed |
| WebSocket convergence | Projector tests broadcast PostgreSQL-backed upsert/removal actions without writing active calls to Redis | Passed |
| Stale Redis tool projection on stop | `test_finalize_ignores_redis_tool_call_without_durable_ownership` excludes it from cancellation candidates | Passed |
| Background protocol removal | Runtime Control and Runner suites compile and pass without Background fields, receipts, or dispatch APIs | Passed |
| Exec process continuation | Runtime Runner operation tests retain process start/write observation semantics after protocol removal | Passed |

## E2E Coverage Decision

The failure boundaries are validated at the engine transaction and worker-supervisor integration layers rather than by killing a container from a browser E2E test. These layers expose the exact admission, commit, side-effect, cancellation, and takeover boundaries without sleep-based race selection. REST and WebSocket contract tests cover the user-visible convergence boundary.

A process-level replacement test would duplicate the same state machine with less deterministic boundary control. No additional testenv fixture or external prerequisite is required for this implementation.

## Implementation-to-Design Comparison

| Design requirement | Implemented behavior | Status |
| --- | --- | --- |
| Complete-set admission before handler creation | Model output, call events, active ownership, and phase commit before task creation | Matches |
| Independent atomic completion | Each result append removes only its matching active entry in one transaction | Matches |
| No prior-owner re-execution | Recovery cancels unresolved previous-generation and orphan calls | Matches |
| Deterministic terminal identity | Tool results use a unique deterministic external ID | Matches |
| TERM admission barrier | TERM closes admission before waiting for admitted work | Matches |
| PostgreSQL active authority | `agent_runs.active_tool_calls` drives recovery, REST live state, and stop cancellation | Matches |
| Redis transient-only boundary | Redis retains assistant/reasoning partials, routing, leases, and Pub/Sub; no active tool-call state | Matches |
| Background protocol removal | Domain, coordination, Runner envelope, and protobuf surfaces removed; field 7 reserved | Matches |
| Runner exec lifecycle unchanged | Process observation remains explicit through process events and `write_stdin` | Matches |

## Current Spec Drift

The implementation matches the approved design, but the current living specs still describe pre-implementation behavior. The spec-promotion phase must update these claims before the design is marked implemented.

| Spec | Drift requiring promotion |
| --- | --- |
| `spec/domain/conversation.md` | `active_tool_calls` still includes `background`; live-state Redis wording does not identify PostgreSQL as the sole active-call source |
| `spec/flow/agent-execution-loop.md` | Active-call shape and Background tool behavior are stale; missing-result handling does not state deterministic no-reexecution reconciliation |
| `spec/flow/agent-runtime-control.md` | Still lists background operation completion claims |
| `spec/flow/run-resume.md` | Says an unresolved foreground call may execute after interruption; recovery now cancels orphan and previous-owner calls without execution |

## Conclusion

The implementation satisfies the approved deterministic handling design at all transaction, recovery, shutdown, live-state, and Runtime protocol boundaries. Validation found no implementation defect. Living-spec drift is isolated to the planned spec-promotion phase.
