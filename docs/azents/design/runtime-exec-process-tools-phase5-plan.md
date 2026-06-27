---
title: "Runtime Exec Process Tools Phase 5 Plan"
created: 2026-06-28
updated: 2026-06-28
tags: [backend, engine, runtime, toolkit, e2e]
---
# Runtime Exec Process Tools Phase 5 Plan

## Covered requirements

- R1. Replace `bash` with process tools
- R2. Keep process ownership in Runner
- R3. Add generic tool-result metadata
- R4. Stream and buffer output in Runner
- R5. Enforce bounded process lifecycle
- R6. Keep Phase 1 pipe-based and defer PTY
- R7. Keep exec processes separate from background tool calls

## Source documents

- Design: [Runtime Exec Process Tools](./runtime-exec-process-tools.md)
- Multi-phase plan: [Runtime Exec Process Tools Implementation Plan](./runtime-exec-process-tools-implementation-plan.md)
- ADR: [ADR-0081: Runtime Exec Process Tools](../adr/0081-runtime-exec-process.md)
- Phase 4 plan: [Runtime Exec Process Tools Phase 4 Plan](./runtime-exec-process-tools-phase4-plan.md)

## Phase boundary

Phase 5 adds product-facing verification for the runtime exec process tool stack. It may add or update testenv fixtures and E2E tests. It must not change the product runtime process implementation except for defect fixes that are clearly necessary to make the implemented behavior match prior phases.

## Verification plan

### 1. Deterministic AIMock fixture updates

Update the deterministic E2E fixture so shell-enabled product flows call `exec_command` instead of the removed `bash` tool. Add fixture turns for:

- a quick `exec_command` that exits and returns output;
- a `write_stdin` call against a nonexistent process session to verify missing-process observations.

### 2. Product E2E scenario

Add a runtime-provider-backed E2E test that creates a shell-enabled agent, starts a Runtime Runner, sends deterministic chat messages, and verifies REST history contains:

- `client_tool_call` for `exec_command` and no `bash` call;
- `client_tool_result` output containing stdout and `exit_code: 0`;
- process metadata with `kind=exec_command_result`, `status=exited`, and `exit_code=0`;
- `client_tool_call` for `write_stdin`;
- missing process output and metadata with `status=missing` and `missing_reason=not_found`.

This scenario covers catalog replacement, metadata persistence, process output observation, missing-process observation, and the no-legacy-`bash` surface.

### 3. Existing E2E compatibility

Update existing file/resource lifecycle fixture entries that previously used `bash` to use `exec_command`. The existing file/resource lifecycle E2E remains evidence that runtime-backed shell/file product flows continue to work through the new process tool surface.

## Files expected to change

- `testenv/azents/e2e/src/support/aimock_fixtures/agents_md_loader.json`
- `testenv/azents/e2e/src/tests/azents/public/test_runtime_exec_process_tools.py`
- `docs/azents/design/runtime-exec-process-tools-phase5-plan.md`

## Verification

Run targeted checks:

```bash
cd testenv/azents/e2e
uv run pytest src/tests/azents/public/test_runtime_exec_process_tools.py -q
```

Run static checks for touched test files:

```bash
cd testenv/azents/e2e
uv run ruff check src/tests/azents/public/test_runtime_exec_process_tools.py
uv run pyright src/tests/azents/public/test_runtime_exec_process_tools.py
```

Also run repository diff validation:

```bash
git diff --check
```

## Completion criteria

- Deterministic E2E fixtures no longer request the removed `bash` tool.
- Product E2E evidence verifies `exec_command` and `write_stdin` through REST/chat history.
- Tool result metadata is visible in persisted client tool result payloads.
- Missing process is a completed tool observation, not an assistant/system failure.
- No PTY/TTY or background-handle process behavior is introduced.
