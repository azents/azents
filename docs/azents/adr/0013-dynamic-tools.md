---
title: "ADR-0013: Dynamic Tool Management — Toolkit State Machine"
created: 2026-03-29
tags: [engine, architecture]
---

# ADR-0013: Dynamic Tool Management

> 📌 **Related design document**: [toolkit-state-machine.md](../design/toolkit-state-machine.md)
>
> This document records design-stage discussion. Original title: dynamic-tools.

## Problems in the Current Structure

At run start, the engine synchronously waits for `create_tools()` from every toolkit, builds the system prompt, then starts the LLM call. The tool list and system prompt are fixed at run start and cannot change afterward.

1. **First response blocking**: one slow MCP server delays the start of the entire run, even when the user asks a question unrelated to MCP.
2. **Sandbox dependency**: stdio MCP sidecar Pod must be ready before list_tools can run. The engine becomes dependent on sandbox lifecycle.
3. **No dynamic changes**: tool additions/removals during a run are not reflected, such as after OAuth completion or MCP `list_changed`.

All three problems come from one constraint: **the tool list is fixed at run start**.

## Core Idea: Toolkit State Machine

### Active → Passive Transition

**Active, current**: engine calls `create_tools()` → waits for result → starts run after completion. The engine drives the process.

**Passive, proposed**: each toolkit is a state machine that manages its own state in the background. The engine only reads the current state each turn.

### Interface

```python
class ToolkitState:
    tools: list[FunctionTool]  # currently available tools; may be empty
    prompt: str                # natural-language prompt reflecting current state

class Toolkit:
    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Receive the current turn context and return state immediately.
        Do not perform heavy I/O here."""
        ...
```

### Responsibility Split

```text
Toolkit (state machine):
├── Background: manage connection, list_tools, retry, token refresh, etc.
├── update_context(ctx): receive context and immediately return (tools, prompt) from current state
│   └── Only light I/O, such as checking OAuth token existence in DB
└── Heavy work is handled by the background loop

Engine (consumer):
└── Every turn: collect update_context() from all toolkits → build CompletionRequest
```

### Example States

The engine does not need to structurally understand toolkit internal states such as loading/error/auth. The toolkit expresses state through a natural-language prompt, and the engine includes that prompt in the system prompt as-is.

| Situation | tools | prompt |
|------|-------|--------|
| MCP connecting | [] | "Loading Slack tools..." |
| MCP connected | [post_message, ...] | "Connected to Slack workspace 'nointern'." |
| MCP connection failed | [] | "Slack MCP server connection failed: connection refused" |
| OAuth authorization required | [request_authorization] | "Slack integration is required." |
| OAuth authorization complete | [post_message, ...] | "Connected to Slack workspace 'nointern'." |
| sidecar Pod preparing | [] | "Sandbox is preparing..." |

### Context Updates

Toolkit state changes have two kinds of triggers:

**Things the toolkit knows by itself**, through background loops:

- MCP server connection success/failure
- list_tools completion
- sidecar Pod ready
- token expiration → refresh

**External events**, checked in `update_context`:

- User completed OAuth authorization → query DB token by `user_id` from context
- Administrator changed toolkit configuration
- User completed account linking

The latter cannot be known by the toolkit on its own, so `update_context(ctx)` checks them with light DB reads based on context information.

## Discussion Point Conclusions

### 1. Should tool collection be separated from run start?

**Conclusion: Passive loading.** The toolkit loads itself in the background; the engine does not wait. Start the run with only built-in tools first, and use MCP tools from the next turn once they become ready.

Note: **Deferred loading**, such as Anthropic's `defer_loading: true` plus Tool Search, is a different-layer problem. It is not about when tools are collected, but how collected tools are passed efficiently into LLM context. It can be introduced separately if needed and is independent from passive loading.

### 2. Should the tool list be able to change during a turn sequence?

**Conclusion: yes.** Calling `update_context()` every turn naturally reflects changes. Breaking prompt cache is acceptable because tool changes are rare.

### 3. Should the system prompt also change dynamically?

**Conclusion: yes.** The toolkit returns prompt text every turn, so it is naturally dynamic. Cache breakage is the same as in point 2 and acceptable.

### 4. Should MCP connections become long-lived?

**Conclusion: toolkit internal implementation detail.** The engine does not need to know. Establish the state machine structure first, then migrate each toolkit gradually. No immediate decision is needed.

### 5. Tool count scaling strategy

**Conclusion: discuss later.** It may become a problem, such as accuracy degradation with 30+ tools. Deferred loading can address it, but this is a separate-layer concern.

### 6. stdio MCP sandbox dependency

**Conclusion: solved by state machine.** Pod creation happens in the background, and toolkit state transitions from loading → ready. The engine starts the run without waiting for the Pod.

### 7. Built-in tool integration

**Conclusion: build the state machine system first, then migrate built-in tools into built-in toolkits.**

Model information is included in TurnContext, so built-in toolkits can decide whether a tool is available for the current model. The image_generation migration into built-in tools can happen at the same time.

## Design Decisions (Phase 1.5)

### Toolkit Interface

Remove existing `create_tools()` + `render_config_prompt()`. Unify into `update_context(ctx) → ToolkitState`. Modify the existing Toolkit ABC directly and switch all at once without adapter wrapping.

### TurnContext

Include only information that changes per turn, such as user_id, workspace_id, and model. Infrastructure dependencies like DB session are injected into toolkit constructors.

### Background Loop Lifecycle

The lifecycle is `_SessionRunner`-scoped. Start toolkit background loops when the runner is created and clean them up when the runner idles out or exits. `_SessionRunner` needs an idle timeout, which is currently missing.

### engine.py Loop

The engine receives toolkit objects directly and calls `update_context()` every turn. Rebuild `tool_map` every turn.

### System Prompt

Compose `agent_prompt` (fixed) plus toolkit prompts collected every turn. This has the same role as the current `compose_toolkit_prompt()`, but runs every turn instead of at run start.

### RunRequest

Remove `tools: list[FunctionTool]` and `system_prompt`. Replace them with `toolkits: list[Toolkit]` and `agent_prompt`. The resolve stage becomes lighter because it no longer collects tools or builds the prompt.

### Implementation Order

**PR 1**: Change Toolkit ABC interface + engine.py loop + RunRequest + convert all toolkits at once as mechanical transformation.

**PR 2**: MCP toolkit state machine with background loop and dynamic state changes.

PR 1 alone completes the structure for recollecting tools every turn. PR 2 then incrementally adds dynamic behavior for MCP.
