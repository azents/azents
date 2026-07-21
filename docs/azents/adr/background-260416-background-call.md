---
title: "Background Tool Call Design Discussion"
created: 2026-04-16
tags: [engine, backend, architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: background-260416
historical_reconstruction: true
migration_source: "docs/azents/adr/0010-background-tool-call.md"
---

> 📌 **Related design document**: [background-tool-call.md](../design/background-tool-call.md)
>
> This document records design-stage discussion. See the linked document for the final design and implementation state.

# background-260416/ADR: Background Tool Call Design Discussion

## Overview

Support a **general background tool call mechanism** at the engine level so tool execution can be separated from blocking flow, allowing the parent agent to keep working without waiting for the result. Subagents are the first application of this mechanism.

### References

- GitHub Issue: [#2559](https://github.com/azents/azents/issues/2559)
- Initial Discussion (OUTDATED): [#2562](https://github.com/azents/azents/discussions/2562) — approached as subagent-only scope, then closed because generalization was needed
- Main discussion: [#2591](https://github.com/azents/azents/discussions/2591)

## Background

Claude Code's `run_in_background` feature lets the LLM dispatch a long-running tool and immediately continue other work. In current nointern, tool execution is **always blocking**: `engine.run()` waits for the tool handler to complete. This hurts UX for subagent calls that delegate research/analysis and for long-running shell commands.

## Scope Redefinition

The initial request in issue #2559 was "subagent background execution," but review showed that this should be treated as one application of a **general background tool call** mechanism:

- Claude Code implements this as a per-tool pattern for Bash and Agent, not as a subagent-only feature.
- Candidate tools in nointern are `subagent` and `shell__execute_code`.
- A framework-based design is needed for future long-running tools, such as large MCP calls.

Therefore the design scope expanded from "subagent background execution" to "general background tool call mechanism plus subagent application."

## Discussion Points and Decisions

### 1. Result Injection Mechanism, decided in Discussion #2562

**Decision**: When a background task completes, inject a `SessionMessage` into the parent session with `broker.send_message`, triggering a new `engine.run()`.

- 👍 Minimal changes to `engine.py`; the existing broker → runner → engine path remains unchanged.
- 👍 Same proven pattern as scheduled tasks, queued independently of parent run state.

**Rejected alternatives**:

- Extend `poll_messages` type — requires changing `engine.py` signatures and cannot work after the parent run has ended.
- Dedicated callback + `BrokerMessage` union extension — adds message-type complexity.

### 2. Parent Run End Timing, decided in Discussion #2562

**Decision**: End `engine.run()` immediately after the parent LLM's final response. The background task continues independently as an `asyncio.Task`.

- 👍 Prioritizes UX, which is the core value of background execution.
- 👍 Proven Claude Code pattern.
- 👍 Simple implementation; no need to change `engine.run()` termination conditions.

**Rejected alternative**: wait for background completion before ending the parent run. This is no different from blocking and worsens UX.

### 3. Tool Declaration + Execution Interface

**Decision**:

- **No spec-level flag** — do not add background-related fields to `FunctionToolSpec`.
- **Runtime dispatch**: detect by handler return type, `BackgroundHandle`.
- **LLM discovery**: if the tool `input_schema` has a `run_in_background` property, the LLM can call it in the background.
- **Ergonomics**: `make_tool(..., supports_background=True)` injects schema and auto-wraps the handler. This option is internal to `make_tool` and is not stored in `FunctionToolSpec`.

Layer separation:

- **Tool layer**: background semantics, returning `BackgroundHandle`.
- **Engine layer**: infrastructure, registry, result injection, cancel; dispatches by return type.
- **make_tool layer**: optional ergonomics helper, enabling most tools with one line: `supports_background=True`.

**Rationale**:

- Compared with E1, where the engine hooks `run_in_background`, the abstraction lives at the correct layer.
- Return type + input_schema becomes the single source of truth; a spec-level flag would duplicate information.
- The ergonomics helper in `make_tool` removes duplicated tool-level code.
- Tools that need custom pre-background setup can opt out by returning `BackgroundHandle` directly from the handler.

**Rejected alternatives**:

- E1, engine hooking — the engine intervenes in tool semantics and needs a trick to remove parameters from args.
- Engine-level allowlist — hardcodes tool names and is costly to maintain.
- `FunctionToolSpec.supports_background` flag — duplicates return-type information; removed after PR #2601 review.

### 4. Invocation Model

**Decision**: Use a unified per-call `run_in_background: bool` parameter, following the Claude Code Bash pattern.

- The LLM decides on every call.
- `make_tool` injects the parameter into the schema automatically for tools with `supports_background=True`.

**Rejected alternatives**:

- Use a frontmatter-style setting such as `AgentSubagent.run_in_background` — less aligned with nointern's domain model; can be added later if needed.
- Separate tools such as `background_subagent` — doubles tool count and increases prompt burden.

### 5. Background Task Registry Location

**Decision**: Engine-level in-memory registry. Extract a `BackgroundTaskRegistry` class and inject it into `SessionHost`.

- Manage `task_id → BackgroundTask` with an in-memory dict.
- Aligns with existing fire-and-forget patterns such as `_generate_title_background`.
- Sticky sessions are guaranteed, so cross-worker lookup is unnecessary.

**Rejected alternatives**:

- Redis-backed — adds implementation complexity beyond current requirements.
- DB-backed — resume strategy does not fit the existing pattern and is over-designed.

### 6. Output Inspection, so the LLM can check running task status

**Decision**: Add a `task_status` tool, but **exclude `partial_output` in Phase 1**. Extend in Phase 2+.

Phase 1 return fields:

- `task_id`, `status` (running/completed/failed), `elapsed_seconds`, `tool_name`, `started_at`

Phase 2+ additions:

- `partial_output` — intermediate subagent LLM response or current shell stdout
- Monitor-style stream subscription, if needed

**Rationale**: Corresponds to Claude Code's `BashOutput`. Supports scenarios where the LLM says, "the investigation is taking too long, check intermediate status." However, `partial_output` needs tool-specific semantics, so it is deferred.

### 7. Cancellation

**Decision**: Add a `task_stop` tool. The LLM can stop a running background task by `task_id`.

- Look up the task in the registry → `asyncio.Task.cancel()` + broker notification.
- Permission check: only tasks from the same parent session can be stopped.

**Rationale**: Corresponds to Claude Code's `TaskStop`/`KillShell`. The LLM must be able to correct mistaken delegation for background execution to be valuable.

### 8. Initial Application Scope

**Decision**: Use a phased approach.

- **Phase 1**: Generic framework + apply to subagent.
- **Phase 2**: Enable `supports_background=True` for `shell__execute_code` + validation.
- **Phase 3+**: Apply to other tools as needed.

**Rationale**:

- Prioritize the original request in issue #2559, subagent background execution.
- Since the framework is generic, applying it to shell in Phase 2 should require only a flag change and tests.
- Use real usage data to decide whether to apply it to other tools.

## Follow-up Decisions Revealed by Adopting E2

Adopting the E2 execution structure also fixed these points:

1. **Redesign `check_stop`**: Remove `parent_task.done()` from the stop signal for background tasks. Background tasks must survive after the parent run ends. Stop signals are limited to parent session deletion, user stop, and worker shutdown.
2. **Rewire `publish_event`**: Background tasks do not go through the parent's `RunContext`; they use the broker's session-level publish path directly. The `publish_event` callback injected into handlers is replaced with broker publish.
3. **Standardize the initial LLM response**: All background tools return an initial format of `{"task_id": "...", "status": "running", "tool": "...", "note": "..."}`. Tools may add custom fields.

## Reference: Major Framework Comparison

| Dimension | Claude Code | nointern (this design) |
|------|-------------|-------------------|
| Background-capable tools | Bash, Agent (subagent), Monitor | Phase 1: subagent; Phase 2: shell |
| Declaration method | Per-tool schema: Bash as param, subagent as frontmatter | Unified: handler return type + input_schema `run_in_background` property |
| Invocation method | `run_in_background: bool` parameter for Bash; `background: true` frontmatter for Agent | Unified `run_in_background: bool` parameter |
| Result delivery | System-reminder injection | `broker.send_message` → trigger new run |
| Output inspection | `BashOutput` (diff-based) | `task_status` in Phase 1 for status only; Phase 2+ output |
| Cancellation | `KillShell`, `TaskStop` | `task_stop` |
| Stream observation | `Monitor` dedicated tool | Consider in Phase 2+ if needed |

## Migration provenance

- Historical source filename: `0010-background-tool-call.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
