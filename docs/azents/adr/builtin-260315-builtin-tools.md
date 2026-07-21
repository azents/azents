---
title: "Built-in Tool Support Discussion"
created: 2026-03-15
tags: [backend, engine, frontend, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: builtin-260315
historical_reconstruction: true
migration_source: "docs/azents/adr/0011-builtin-tools.md"
---

# builtin-260315/ADR: Built-in Tool Support Discussion

> 📌 **Related design document**: [builtin-260315-builtin-tools.md](../design/builtin-260315-builtin-tools.md)
>
> This document records design-stage discussion.

## Background

LLM providers offer **built-in tools** that run server-side. For example, Gemini's Google Search does not require us to implement a function; the provider performs search on the server and includes the result in the response. The client only declares the tool and does not need a handler.

NoIntern's current tool system is structured as `Tool = ToolSpec + ToolHandler`, requiring a client-side handler for every tool. Supporting built-in tools requires a way to represent handlerless tools and to process server-side execution results.

### Provider-Specific Built-in Tools

| Provider | Tool | Declaration Shape | Server-Side Execution |
|-----------|------|---------|--------------|
| Google Gemini | Google Search, Code Execution, URL Context | `{"google_search": {}}` | returns results in groundingMetadata |
| Anthropic | Web Search | `{"type": "web_search_20250305", ...}` | server_tool_use + web_search_tool_result blocks |
| OpenAI | Web Search | `{"type": "web_search"}` | web_search_call output item |

Common pattern:

1. Declaration is minimal config; no JSON Schema-based parameter definition is needed.
2. The provider executes on the server and includes the result; no client handler is needed.
3. Citation/grounding metadata is included.
4. The exact format differs by provider.

## Discussion 1: LiteLLM Compatibility

### Conclusion: implementation examples exist, but the concrete method needs research

Other projects have implemented Google Search integration through LiteLLM. The concrete path for passing declarations and parsing responses needs research during implementation.

## Discussion 2: Abstraction Level

All three providers support web search, but their names and config differ:

| Provider | Name | Config Options |
|---|---|---|
| Google | `google_search` | Almost none |
| Anthropic | `web_search_20250305` | `max_uses`, `allowed_domains`, `blocked_domains`, `user_location` |
| OpenAI | `web_search` | `filters.allowed_domains`, `user_location` |

Options considered:

- **(A) Unified abstraction**: one `name: "web_search"` mapped automatically per provider
- **(B) Separate abstraction**: separate tool per provider
- **(C) Hybrid**: semantic name plus provider-specific namespaces in config

### Conclusion: (B) separate abstraction

Provider-specific config options differ, and built-in tools themselves are provider-dependent. Manage them as separate tools such as `google_search`, `anthropic_web_search`, and `openai_web_search`. There is no reason to force unification.

## Discussion 3: Relationship to Existing Image Generation

Current image generation is hardcoded through `LLMProviderModel.image_generation` boolean → `RunRequest.image_generation` → provider-specific branching in `build_responses_kwargs()`. This is effectively a built-in tool pattern.

Options considered:

- **(A) Unify**: migrate `image_generation` into the `builtin_tools` system for a consistent pattern.
- **(B) Keep**: leave the existing path unchanged and put only new built-in tools into the `builtin_tools` system.

### Conclusion: (B) keep

Minimize changes to existing code. Document a future unification migration as a separate issue.

→ [image_generation migration issue](../design/issues/image-generation-builtin-migration.md)

## Discussion 4: Citation Data Handling

Provider citation formats differ:

- Google: segment-index based (`startIndex`/`endIndex` → `groundingChunkIndices`)
- Anthropic: inline citations (`cited_text`, `encrypted_index`)
- OpenAI: annotations (`url_citation`, `start_index`/`end_index`)

Options considered:

- **(A) Normalized common model**: frontend renders citations provider-independently.
- **(B) Store raw**: frontend branches by provider for rendering.
- **(C) Normalize and store raw together**.

### Conclusion: store raw, no FE rendering needed

The LLM already incorporates citations into the text response. Raw round-trip preserves context for the next turn, so the frontend does not need a separate citation UI. Source display is delegated to the LLM text response.

## Discussion 5: DB Schema and Engine Handling

How should server-side tool execution results be stored and handled by the engine?

### 5-1. Storage Shape

Options considered:

- **(A) New `DurableServerToolUse` event type**: extend `MessageRole` enum and add DB migration.
- **(B) Store as `UnknownEvent`**: no schema change, round-trip by `source_model`.
- **(C) Reuse existing `DurableToolCall` + `DurableToolResult`**: no schema change.

(B) has a problem when switching models: if `source_model != model`, the event is skipped, breaking the tool call/result pair and causing the LLM to error because there is no matching tool result.

#### Conclusion: (C) reuse existing DurableToolCall + DurableToolResult

- No DB schema change.
- Reuse the model-switch fallback in `build_input_items()` that normalizes function_call ↔ function_call_output.
- Store masking text, such as `"[server-executed tool result]"`, in normalized columns so that model-switch normalization fallback works with the masked value.

### 5-2. Skip Engine Handler Execution

When parsing the LLM response, server-side tools are immediately stored as paired `DurableToolCall` + `DurableToolResult`. The engine tool execution loop runs handlers **only for tool calls without a result**, so server tool calls that already have results are naturally skipped.

### 5-3. Additional Turn After Server Tool Use

Server tool calls are also added to `tool_calls`. The existing logic, "if there are tool_calls, run another turn," works unchanged. No separate branch is needed; handler execution only needs to filter for tool calls that lack results.

## Discussion 6: Multi-turn Preservation

### Conclusion: solved by discussion 5

- Same model: `raw_output` round-trip preserves provider-specific data such as Anthropic `encrypted_content`.
- Different model: normalized fallback + masking text.

## Discussion 7: Provider Availability and Agent Settings UX

If an Agent has `google_search` configured and the provider is changed to Anthropic, the configuration becomes incompatible.

Options considered:

- **(A) Ignore**: silently skip incompatible built-in tools.
- **(B) Error**: validation error when saving/running the Agent.
- **(C) Warning**: allow execution but return a warning.

### Conclusion: (B) validation error

Block incompatible built-in tools with validation errors when saving the Agent.

## Discussion 8: Cost Tracking

### Conclusion: pass

Existing `TokenUsage.raw` already stores provider-native usage and is sufficient. Anthropic fields such as `server_tool_use.web_search_requests` are also included in raw.

## Discussion 9: Implementation Scope

Initial implementation candidates:

- Google Search (Gemini): simple config, implementation examples exist
- Anthropic Web Search: rich config, high practicality
- OpenAI Web Search: native to Responses API

### Conclusion: start with Google Search (Gemini)

It has the simplest config and known implementation examples.

## Discussion 10: Built-in Tool UX Constraints

### 10-1. Model Compatibility Mapping

Not all Gemini models support Google Search. Declare the list of supported built-in tools in `LLMProviderModel` metadata and map them when registering models in admin.

### 10-2. Tool Combination Constraint: Exclusive Rule

Gemini Google Search cannot be used together with other tools; the API rejects that combination. Each built-in tool needs constraint rules such as "exclusive."

### 10-3. Subagent-Only Pattern

If an exclusive tool like Google Search is attached directly to the main Agent, Shell and other toolkits become unusable. It should be separated into a Subagent registered with `shell_enabled=False` and no additional toolkit.

### Conclusion: system-enforced validation + plugin-style rules

- Define validation rules per built-in tool as plugins. For example, `GoogleSearchRule` can express `exclusive=True`, `subagent_only=True`, `requires_shell_disabled=True`, and similar constraints.
- Design validation so additional rules can be attached polymorphically as plugins.
- FE should provide a model-specific add-on settings section and show validation errors for each add-on in that section.
- Admin UI needs redesign to add supported built-in tool mapping UI to `LLMProviderModel` settings.

## Migration provenance

- Historical source filename: `0011-builtin-tools.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
