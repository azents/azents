---
title: "Runtime Exec Process Tools Phase 2 Plan"
created: 2026-06-27
updated: 2026-06-27
tags: [backend, engine, runtime, toolkit]
---
# Runtime Exec Process Tools Phase 2 Plan

## Covered requirements

- R2. Keep process ownership in Runner
- R4. Stream and buffer output in Runner
- R6. Keep initial implementation pipe-based and defer PTY

## Source documents

- Design: [Runtime Exec Process Tools](./runtime-exec-process-tools.md)
- Multi-phase plan: [Runtime Exec Process Tools Implementation Plan](./runtime-exec-process-tools-implementation-plan.md)
- ADR: [ADR-0081: Runtime Exec Process Tools](../adr/0081-runtime-exec-process.md)

## Phase boundary

Phase 2 adds protocol contracts for future Runner-owned process operations. It must not implement a process manager, expose `exec_command` or `write_stdin` to the model, remove `bash`, add PTY/TTY, or change UI projection behavior.

The protocol is intentionally pipe-based:

- no `tty` field;
- no terminal resize or screen state;
- stdout/stderr output is represented as structured text deltas and bounded final snapshots.

## Implementation plan

### 1. Runner gRPC schema

Extend `runtime_runner_control.proto` with protocol messages for:

- `process.start` requests;
- `process.write` requests, where empty `stdin` is the poll primitive;
- structured process output deltas;
- final process snapshots that can represent running, exited, missing, terminated, or expired states.

Required request fields:

- `command` for process start;
- optional `workdir` for process start;
- `process_id` and `stdin` for process write/poll;
- `yield_time_ms` and `max_output_bytes` for both operations.

Required result fields:

- `process_id`;
- process `status`;
- optional `exit_code`;
- stdout/stderr snapshots;
- stdout/stderr truncation facts;
- optional `missing_reason`.

### 2. Shared Runner-side event enum

Add a `process_output` event type to the shared runner/control event enums. This is a protocol-level event type only. Phase 3 will decide when the Runner emits these events from a real process manager.

### 3. gRPC bridge mapping

Update both sides of the Runner gRPC bridge:

- Control-to-Runner mapping for `process.start` and `process.write` operation requests;
- Runner-to-Control mapping for `process_output` events;
- process final-success payload encoding/decoding.

The mapping must keep existing bash/file operation behavior unchanged.

### 4. High-level operation client

Add typed high-level client helpers for protocol callers:

- `start_process(...) -> RuntimeProcessResult`;
- `write_process_stdin(...) -> RuntimeProcessResult`;
- `resume_process(...) -> RuntimeProcessResult`.

These helpers only dispatch and fold protocol events. They do not create local process handles and do not manage process lifecycle.

### 5. Tests

Add/update protocol tests for:

- dispatching `process.start` payloads through the coordination request envelope;
- dispatching empty-stdin `process.write` as a poll request;
- folding process output deltas and final snapshots into `RuntimeProcessResult`;
- gRPC Control-to-Runner process operation mapping;
- gRPC Runner-to-Control `process_output` mapping;
- gRPC client process final-success encoding/decoding.

## Files expected to change

- `proto/azents/runtime_control/v1/runtime_runner_control.proto`
- `python/libs/azents-runtime-control/src/azents_runtime_control/proto/runtime_runner_control_pb2.py`
- `python/libs/azents-runtime-control/src/azents_runtime_control/runner.py`
- `python/libs/azents-runtime-control/src/azents_runtime_control/grpc_runner_client.py`
- `python/libs/azents-runtime-control/tests/grpc_runner_client_test.py`
- `python/apps/azents/src/azents/runtime/coordination/data.py`
- `python/apps/azents/src/azents/runtime/control_protocol/runner_operations.py`
- `python/apps/azents/src/azents/runtime/control_protocol/runner_operations_test.py`
- `python/apps/azents/src/azents/runtime/control_protocol/grpc/runner_server.py`
- `python/apps/azents/src/azents/runtime/control_protocol/grpc/runner_server_test.py`

## Verification

Run targeted tests:

```bash
cd python/apps/azents
uv run pytest src/azents/runtime/control_protocol/runner_operations_test.py src/azents/runtime/control_protocol/grpc/runner_server_test.py
uv run ruff check src/azents/runtime/control_protocol/runner_operations.py src/azents/runtime/control_protocol/runner_operations_test.py src/azents/runtime/control_protocol/grpc/runner_server.py src/azents/runtime/control_protocol/grpc/runner_server_test.py src/azents/runtime/coordination/data.py
uv run pyright src/azents/runtime/control_protocol/runner_operations.py src/azents/runtime/control_protocol/runner_operations_test.py src/azents/runtime/control_protocol/grpc/runner_server.py src/azents/runtime/control_protocol/grpc/runner_server_test.py src/azents/runtime/coordination/data.py

cd ../../libs/azents-runtime-control
uv run pytest tests/grpc_runner_client_test.py tests/runner_test.py
uv run ruff check src/azents_runtime_control/runner.py src/azents_runtime_control/grpc_runner_client.py tests/grpc_runner_client_test.py tests/runner_test.py
uv run pyright src/azents_runtime_control/runner.py src/azents_runtime_control/grpc_runner_client.py tests/grpc_runner_client_test.py tests/runner_test.py
```

Also run docs/diff checks from the repository root:

```bash
python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check
git diff --check
```

## Completion criteria

- Protocol schemas include process start, stdin/poll, output delta, and final snapshot contracts.
- Protocol schemas do not expose PTY/TTY fields.
- Runner process ownership remains a future Runner implementation concern; no worker/control process handles are introduced.
- Existing bash/file protocol tests remain green.
- New process protocol mappings are covered by unit tests.
