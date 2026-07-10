---
title: "Session-Scoped Runner Operation Concurrency Validation Report"
created: 2026-07-10
updated: 2026-07-10
tags: [backend, runtime, performance, testing, testenv, documentation]
---
# Session-Scoped Runner Operation Concurrency Validation Report

## Summary

This report validates the Session-scoped Runtime Runner operation concurrency implementation against [ADR-0102](../adr/0102-session-scoped-runner-operation-concurrency.md), the [approved design](session-scoped-runner-operation-concurrency.md), and its implementation plan.

Validation found and fixed four implementation gaps:

- Runner state reports now expose current Runtime, system, per-Session, and control-path pending/active counts together with cumulative queue-rejection and pre-execution-timeout counts.
- Runtime Runner logs now use structured JSON so scheduling ownership, counts, queue wait, execution duration, and configured limits survive container log serialization.
- Docker and Kubernetes Runtime Providers now forward the six allowlisted Runner limit settings, replace existing Runtime workloads when an override changes or is removed, and keep Runner startup validation as the single validation authority.
- The process-termination ownership test now starts direct Python processes through shell `exec`, so terminating one process does not wait for an orphaned child and allow the unrelated process to exit during the assertion.

The scheduler matrix runs deterministically at the Runner/Control component boundary, where handlers can be held and released without external credentials or timing-dependent model behavior. Existing Azents Runtime process E2E remains the product-path regression gate. A local E2E attempt was blocked because this agent runtime has no Docker socket; GitHub CI is the required Docker-backed E2E environment.

## Validated Stack Scope

| PR | Branch | Scope |
| --- | --- | --- |
| #319 | `feature/session-runner-concurrency-design` | ADR-0102 and approved design |
| #320 | `feature/session-runner-concurrency-plan` | Phased implementation and validation plan |
| #328 | `feature/session-runner-concurrency-scheduler` | Common ownership protocol, bounded admission, fair scheduler, control path, cancellation fences, and transport backpressure |
| #330 | `feature/session-runner-concurrency-callers` | Explicit Session/system ownership at Runner operation callers |
| PR 5 | `feature/session-runner-concurrency-validation` | Deterministic validation, observability gap fixes, provider configuration wiring, and evidence |

## Deterministic Validation Matrix

The default-capacity case uses the production defaults. Overload and ordering cases use smaller validated limits where cardinality does not change the scheduler contract.

| Scenario | Evidence | Result |
| --- | --- | --- |
| Five Sessions saturate one Runtime | `test_default_limits_allow_five_sessions_to_fill_runtime_capacity` starts 10 held operations for each of five owners and asserts 50 active operations plus 10 per owner. | Pass |
| One owner has a deep backlog | `test_session_limit_does_not_block_another_session` holds Session A at its owner limit and asserts Session B starts before A drains. | Pass |
| Per-owner FIFO | `test_owner_queue_preserves_fifo_order` releases one owner slot repeatedly and asserts arrival order. | Pass |
| Cross-owner round-robin | `test_owner_backlogs_are_scheduled_round_robin` admits two backlogs before scheduling and asserts `a-1, b-1, a-2, b-2`. | Pass |
| System and Session fairness | `test_system_operations_use_independent_limit` fills the system allocation and asserts Session work still starts under the Runtime ceiling. | Pass |
| Per-owner pending overload | `test_rejects_operation_when_owner_pending_queue_is_full` uses a one-pending owner bound and asserts final `operation_queue_full` plus the rejection diagnostic counter. | Pass |
| Runtime pending overload | `test_rejects_operation_when_runtime_pending_queue_is_full` admits multiple owners against a two-pending Runtime bound and asserts final `operation_queue_full`, total pending, and rejection count. | Pass |
| Pending deadline expiry | `test_expired_pending_operation_is_not_executed` asserts final `operation_timeout`, no handler start, and the timeout diagnostic counter. | Pass |
| Saturated user stop | `test_control_operation_runs_while_ordinary_capacity_is_full` proves control scheduling bypasses ordinary saturation; `test_process_terminate_session_terminates_only_owned_processes` proves target-only process termination. | Pass |
| Root and subagent isolation | The five-owner and cross-owner tests use distinct Session IDs; caller tests prove model-visible tools propagate their injected Session ID. Scheduler allocation depends only on that ID, so child Sessions receive independent limits. | Pass |
| Background ownership | `test_background_operation_preserves_session_ownership` asserts background dispatch keeps the durable parent Session owner in the common request envelope. | Pass |
| Generation replacement | `test_run_loop_shutdown_discards_pending_generation_work` proves shutdown clears pending in-memory work before reuse; Control generation-fence and gRPC start/cancel tests prove stale work cannot start or finalize a replacement generation. | Pass |
| Configuration override | Runner entrypoint tests validate non-default values and invalid relationships; Docker/Kubernetes Provider tests prove exact six-key propagation and replacement after changed or removed overrides; scheduler tests enforce non-default low-cardinality limits. | Pass |
| Diagnostics and structured logs | `test_state_reports_expose_per_owner_and_runtime_counts` validates state diagnostics; `test_structured_log_formatter_keeps_runner_diagnostics` validates JSON preservation of owner, active-count, and duration fields. | Pass |

## Requirements-to-Implementation Comparison

| Requirement | Observed implementation | Status |
| --- | --- | --- |
| Common nullable Session ownership | Protobuf request, Control/Runner envelopes, adapters, and callers carry `owner_session_id`; `None` is an explicit system owner. | Implemented |
| Defaults 10 Session / 10 system / 50 Runtime | Runner constructor and entrypoint defaults match ADR-0102; full 50-active deterministic validation passes. | Implemented |
| FIFO per owner and fair cross-owner scheduling | Owner deques and round-robin rotation are covered by explicit FIFO, backlog bypass, and alternating-backlog tests. | Implemented |
| Pending bounds 100 per owner / 1,000 Runtime | Direct transport admission atomically checks both configured bounds; low-cardinality equivalent overload tests assert final errors and counters. | Implemented |
| Deadline before handler execution | Scheduler checks the end-to-end deadline before the start fence and does not invoke the handler after expiry. | Implemented |
| Cancellation before side effects | Start authorization occurs immediately before handler task creation; canceled admitted work is removed without calling `handle`. | Implemented |
| Dedicated bounded termination path | `process.terminate_session` uses a separately bounded queue with default concurrency 4 and does not consume ordinary capacity. | Implemented |
| Generation/disconnect invalidation | Runner shutdown cancels active work and clears pending queues; Control generation fencing rejects stale start/final races. | Implemented |
| Explicit Session/system caller ownership | Session process/file/Skill/Project/worktree callers pass their Session ID; Agent Workspace, catalog, pre-Session preview, and file-storage callers deliberately pass `None`. | Implemented |
| Operator observability | Structured JSON logs expose ownership, pending/active counts, queue wait, execution duration, rejection, timeout, and configured limits. State reports expose aggregate and per-owner snapshots and cumulative counters. | Implemented after validation fix |
| Configurable deployed Runner limits | The Runner validates six environment settings. Docker/Kubernetes Providers forward only those settings, and Helm exposes typed positive integer values for Kubernetes deployments. | Implemented after validation fix |
| Model-visible behavior | Queue-full and timeout remain ordinary final Runner operation errors/tool observations; ownership and diagnostic identifiers are not added to tool output. | Preserved |
| Runtime lifecycle boundary | Scheduler pressure and Runner diagnostics do not trigger Runtime/server restart or lifecycle inference. | Preserved |

No implementation-to-ADR conflict was found after the validation fixes. No new hard-to-reverse decision was introduced, so ADR-0102 remains unchanged.

## Validation Commands and Environment

Local environment:

- repository worktree: `/workspace/agent/.azents/worktrees/bullet-barrel-scout/azents`;
- Python: repository-managed `uv` environments (CPython 3.14 in this agent runtime);
- external credentials: none;
- Docker socket: unavailable;
- Helm binary: unavailable.

| Command | Result |
| --- | --- |
| `cd python/libs/azents-runtime-control && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q` | Pass — 26 tests |
| `cd python/apps/azents-runtime-runner && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q` | Pass — 41 tests |
| `cd python/apps/azents-runtime-provider-docker && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q` | Pass — 15 tests |
| `cd python/apps/azents-runtime-provider-kubernetes && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q` | Pass — 42 tests |
| `cd python/apps/azents && uv run ruff check . && uv run ruff format --check . && uv run pyright` | Pass |
| `cd python/apps/azents && uv run pytest src/azents/runtime/control_protocol src/azents/engine/tools/builtin_test.py src/azents/engine/tools/skill_test.py src/azents/services/agent_project_catalog/service_test.py src/azents/services/chat/workspace_test.py src/azents/services/session_git_worktree/service_test.py src/azents/services/session_workspace_project/service_test.py src/azents/worker/input/background_completion_publisher_test.py -q` | Pass — 107 passed, 38 skipped |
| `cd testenv/azents/e2e && uv run pytest src/tests/azents/public/test_runtime_exec_process_tools.py -q` | Blocked locally before test execution — Docker socket absent; required in GitHub CI |
| `cd infra/charts/azents && python -m pytest tests/runtime_provider_kubernetes_render_test.py -q` | Skipped locally — Helm binary absent; required in GitHub CI |
| `cd infra/charts/azents && python -m json.tool values.schema.json` | Pass |

## Fixture Assessment

No external credential or live integration is required. The existing product E2E fixture can start a real Runtime Runner and validates process tool results, but it does not expose deterministic handler hold/release, request labels, or generation replacement controls. Adding a test-only model-visible operation or production control API solely for scheduler synchronization would expand the product surface and weaken the Runner boundary.

The validation therefore keeps the complete concurrency matrix in the shared Runtime Control/Runner test harness, which uses the same `RunnerRunLoop`, direct transport admission handler, start fence, operation envelopes, and final event contract as the deployed Runner. Docker-backed product E2E remains a regression check for the actual Control → Provider → Runner → tool-result path. Missing Docker or Helm locally does not count as a skip for acceptance: the corresponding GitHub CI jobs must pass before spec promotion.

## Spec Promotion Decision

PR 6 should update only `docs/azents/spec/flow/agent-runtime-control.md` and mark the approved design implemented after Docker-backed CI passes. `docs/azents/spec/flow/agent-execution-loop.md` does not require a change because overload and pre-execution timeout use the existing failed Runner operation/tool observation path rather than introducing a new invocation contract.
