---
title: "Runtime Exec Process Tools Phase 3 Plan"
created: 2026-06-27
updated: 2026-06-27
tags: [backend, engine, runtime, toolkit]
---
# Runtime Exec Process Tools Phase 3 Plan

## Covered requirements

- R2. Keep process ownership in Runner
- R4. Stream and buffer output in Runner
- R5. Enforce bounded process lifecycle
- R7. Keep exec processes separate from background tool calls

## Source documents

- Design: [Runtime Exec Process Tools](./runtime-exec-process-tools.md)
- Multi-phase plan: [Runtime Exec Process Tools Implementation Plan](./runtime-exec-process-tools-implementation-plan.md)
- ADR: [ADR-0081: Runtime Exec Process Tools](../adr/0081-runtime-exec-process.md)
- Phase 2 plan: [Runtime Exec Process Tools Phase 2 Plan](./runtime-exec-process-tools-phase2-plan.md)

## Phase boundary

Phase 3 consumes the Phase 2 runner/control protocol contracts inside the Runtime Runner. It adds runner-local process ownership, pipe drain, stdin/poll, output snapshots, and bounded lifecycle. It must not expose `exec_command` or `write_stdin` to the model, remove `bash`, add PTY/TTY fields, implement runtime toolkit rendering, or add background-tool completion injection.

## Implementation plan

### 1. Runner process capabilities

Register `process.start` and `process.write` as Runner capabilities so Control can route the Phase 2 operation types to capable Runner processes.

### 2. Runner-owned process registry

Add an in-memory process registry owned by `RunnerOperations`.

Requirements:

- process ids are opaque runner-generated ids;
- OS process handles, stdin writers, drain tasks, unread buffers, and lifecycle timestamps live only in Runner memory;
- registry entries are scoped to the current runner generation;
- Runner shutdown terminates tracked processes.

### 3. Process start

Implement `process.start` handling:

- validate `command` and optional `workdir`;
- start a pipe-based subprocess with stdin/stdout/stderr pipes;
- create continuous stdout/stderr drain tasks immediately;
- wait up to `yield_time_ms` for process exit;
- return a final process snapshot with status, process id, output, exit code when exited, truncation facts, and missing reason when applicable.

### 4. Process stdin and poll

Implement `process.write` handling:

- validate `process_id`;
- when `stdin` is non-empty and process is running, write to stdin pipe;
- when `stdin` is empty, treat the operation as a poll;
- wait up to `yield_time_ms`;
- drain unread output into the final snapshot;
- missing/consumed/terminated/expired process ids return normal final-success process observations, not Runner operation errors.

### 5. Output drain and truncation

Maintain bounded unread stdout/stderr buffers in Runner memory.

Requirements:

- drain stdout/stderr continuously to avoid pipe backpressure;
- drop oldest unread bytes when the per-stream buffer exceeds the configured cap;
- drain snapshots are bounded by `max_output_bytes`;
- final payloads and `process_output` events include truncation and omitted-byte facts.

### 6. Lifecycle bounds

Implement bounded lifecycle controls:

- process count quota pruning;
- idle timeout cleanup;
- max lifetime cleanup;
- consumed state after an exited process snapshot is returned;
- recent missing-state records for subsequent observations;
- shutdown termination.

### 7. Tests

Add/update Runner tests for:

- quick process exit snapshot;
- long-running process poll and stdin continuation;
- missing-after-consumed observation;
- bounded output and truncation facts;
- quota pruning;
- existing bash and file operation behavior remaining unchanged.

## Files expected to change

- `python/apps/azents-runtime-runner/src/azents_runtime_runner/operations.py`
- `python/apps/azents-runtime-runner/src/azents_runtime_runner/main.py`
- `python/apps/azents-runtime-runner/tests/operations_test.py`

## Verification

Run targeted Runner checks:

```bash
cd python/apps/azents-runtime-runner
uv run pytest tests/operations_test.py
uv run pytest
uv run ruff check src tests
uv run pyright src tests
```

Also run repository diff validation:

```bash
git diff --check
```

## Completion criteria

- Runner handles `process.start` and `process.write` through Phase 2 protocol payloads.
- Runner owns all OS process handles and unread output buffers in memory.
- Empty `process.write` polls without sending stdin.
- Exited, missing, terminated, and expired states are observations in final process snapshots.
- Output snapshots and live `process_output` events are bounded and carry truncation facts.
- Runner shutdown and lifecycle cleanup terminate/prune tracked processes.
- No PTY/TTY, model-visible process tools, `bash` removal, or background-tool completion behavior is introduced in this phase.
