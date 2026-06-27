---
title: "Runtime Exec Process Tools Phase 1 Plan"
created: 2026-06-27
updated: 2026-06-27
tags: [backend, engine, runtime, toolkit]
---
# Runtime Exec Process Tools Phase 1 Plan

## Covered requirements

- R3. Add generic tool-result metadata

## Source documents

- Design: [Runtime Exec Process Tools](./runtime-exec-process-tools.md)
- Multi-phase plan: [Runtime Exec Process Tools Implementation Plan](./runtime-exec-process-tools-implementation-plan.md)
- ADR: [ADR-0081: Runtime Exec Process Tools](../adr/0081-runtime-exec-process.md)

## Phase boundary

Phase 1 adds the generic metadata foundation required by later exec process tools. It must not add `exec_command`, `write_stdin`, process protocol operations, runner process management, `bash` removal, UI process projection, or PTY/TTY behavior.

## Implementation plan

### 1. Reuse shared JSON object type

Use the existing shared `azcommon.types.JSONObject` type for generic tool metadata rather than adding exec-specific payload classes or a duplicate JSON alias.

### 2. Function tool result metadata

Extend `FunctionToolResult` with:

```python
metadata: JSONObject = Field(default_factory=dict)
```

Requirements:

- default metadata is `{}`;
- metadata dicts are not shared between instances;
- non-object metadata is rejected by Pydantic validation;
- existing callers that pass only `output` continue to work.

### 3. Client tool result payload metadata

Extend `ClientToolResultPayload` with:

```python
metadata: JSONObject = Field(default_factory=dict)
```

Requirements:

- metadata is preserved in durable/projected client tool result payloads;
- model-visible output lowering remains based only on `output`;
- no exec-specific metadata keys are interpreted by event core.

### 4. Tool executor propagation

Update `ToolCatalogClientToolExecutor` result conversion:

- string tool results keep default empty metadata;
- `FunctionToolResult` metadata is copied into `ClientToolResultPayload.metadata`;
- output hard-cap behavior remains unchanged.

### 5. Tests

Add or update tests for:

- `FunctionToolResult.metadata` defaulting and validation;
- `ClientToolResultPayload.metadata` validation;
- metadata propagation from a tool handler result into a client tool result payload;
- model-visible output stability, proving metadata does not change `function_call_output.output` lowering.

## Files expected to change

- `python/apps/azents/src/azents/engine/run/types.py`
- `python/apps/azents/src/azents/engine/events/types.py`
- `python/apps/azents/src/azents/engine/events/tools.py`
- `python/apps/azents/src/azents/engine/events/tools_test.py`
- `python/apps/azents/src/azents/engine/events/types_test.py`

## Verification

Run:

```bash
cd python/apps/azents
uv run pytest src/azents/engine/events/tools_test.py src/azents/engine/events/types_test.py
uv run ruff check src/azents/engine/run/types.py src/azents/engine/events/types.py src/azents/engine/events/tools.py src/azents/engine/events/tools_test.py src/azents/engine/events/types_test.py
uv run pyright
```

Also run docs validation from the repository root:

```bash
python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check
git diff --check
```

## Completion criteria

- Existing tools remain compatible without specifying metadata.
- Metadata is a generic JSON object carrier.
- Metadata propagates through client tool result events.
- Model-visible function tool output remains unchanged by metadata.
- Engine core does not gain exec-specific branches or renderers.
