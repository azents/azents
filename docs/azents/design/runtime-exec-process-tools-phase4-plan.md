---
title: "Runtime Exec Process Tools Phase 4 Plan"
created: 2026-06-28
updated: 2026-06-28
tags: [backend, engine, runtime, toolkit]
---
# Runtime Exec Process Tools Phase 4 Plan

## Covered requirements

- R1. Replace `bash` with process tools
- R6. Keep Phase 1 pipe-based and defer PTY
- R7. Keep exec processes separate from background tool calls

## Source documents

- Design: [Runtime Exec Process Tools](./runtime-exec-process-tools.md)
- Multi-phase plan: [Runtime Exec Process Tools Implementation Plan](./runtime-exec-process-tools-implementation-plan.md)
- ADR: [ADR-0081: Runtime Exec Process Tools](../adr/0081-runtime-exec-process.md)
- Phase 3 plan: [Runtime Exec Process Tools Phase 3 Plan](./runtime-exec-process-tools-phase3-plan.md)

## Phase boundary

Phase 4 consumes the Phase 3 runner process manager and exposes model-visible runtime process tools. It replaces the runtime shell `bash` tool with `exec_command` and `write_stdin`, renders model-visible process snapshots in the runtime toolkit layer, and attaches structured metadata through the generic Phase 1 metadata boundary. It must not add PTY/TTY fields, add an LLM-visible `terminate_process`, or use the background tool-call framework for running process sessions.

## Implementation plan

### 1. Engine runtime I/O surface

Ensure the engine runtime I/O protocol and worker adapter expose:

- `start_process(...) -> RuntimeProcessResult`;
- `write_process_stdin(...) -> RuntimeProcessResult`;
- process status, exit code, stdout/stderr snapshots, truncation facts, missing reason, and final cursor.

### 2. Runtime toolkit schemas

Add LLM-visible input schemas:

- `exec_command(command, workdir?, yield_time_ms?, max_output_tokens?)`;
- `write_stdin(session_id, chars = "", yield_time_ms?, max_output_tokens?)`.

`yield_time_ms` is bounded and defaults to 10 seconds. `max_output_tokens` is converted to a Runner byte budget before dispatch.

### 3. Runtime toolkit handlers

Implement handlers that:

- reuse existing runtime readiness and peer toolkit environment collection;
- call `start_process` or `write_process_stdin`;
- treat unavailable/generation/runner failures as `FunctionToolError` tool observations;
- return `FunctionToolResult` with process metadata;
- never return `BackgroundHandle` for running processes.

### 4. Model-visible rendering

Render process snapshots in the runtime toolkit layer only. Include status, session id, exit code when available, missing reason, truncation facts, and stdout/stderr output. Keep engine core generic.

### 5. Tool catalog and prompt replacement

Replace the runtime shell tool catalog entry:

- expose `exec_command` and `write_stdin`;
- stop exposing `bash`;
- update runtime prompt guidance from `bash` to `exec_command` / `write_stdin`.

### 6. Tests

Add/update runtime toolkit tests for:

- tool catalog contains `exec_command` and `write_stdin` but omits `bash`;
- `exec_command` calls runner process start with env injection and returns metadata;
- `write_stdin` calls runner process write/poll and returns metadata;
- runtime readiness/start/failure paths still behave as tool observations;
- client tool result payload can carry process metadata.

## Files expected to change

- `python/apps/azents/src/azents/engine/tools/runtime_io.py`
- `python/apps/azents/src/azents/worker/runtime_io.py`
- `python/apps/azents/src/azents/engine/tools/builtin.py`
- `python/apps/azents/src/azents/engine/tools/builtin_test.py`
- `docs/azents/design/runtime-exec-process-tools-phase4-plan.md`

## Verification

Run targeted engine checks:

```bash
cd python/apps/azents
uv run pytest src/azents/engine/tools/builtin_test.py src/azents/engine/events/tools_test.py
uv run ruff check src/azents/engine/tools/builtin.py src/azents/engine/tools/runtime_io.py src/azents/worker/runtime_io.py src/azents/engine/tools/builtin_test.py
uv run pyright src/azents/engine/tools/builtin.py src/azents/engine/tools/runtime_io.py src/azents/worker/runtime_io.py src/azents/engine/tools/builtin_test.py
```

Also run repository diff validation:

```bash
git diff --check
```

## Completion criteria

- Runtime toolkit exposes `exec_command` and `write_stdin`, not `bash`.
- Process tool results are `FunctionToolResult` values with structured metadata.
- Running process sessions are resumed only by `write_stdin`; no `BackgroundHandle` is used.
- Tool schemas remain pipe-based and expose no PTY/TTY fields.
- Existing runtime unavailable/startup/provider failure behavior remains a tool observation.
