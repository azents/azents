---
title: "Adopt Runtime Hook System"
created: 2026-05-18
tags: [backend, engine, toolkit, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: hook-260518
historical_reconstruction: true
migration_source: "docs/azents/adr/0033-runtime-hook-system.md"
---

# hook-260518/ADR: Adopt Runtime Hook System

## Context

[toolkit-260514/ADR](./toolkit-260514-toolkit-hooks-for-agents-md.md) introduced Toolkit hooks and Toolkit State with AGENTS.md loading as the first consumer. That decision enabled tool-call observation and provider-owned state/prompt updates, but it did not finalize a general hook taxonomy for the whole runtime across session, run, turn, tool, and sandbox lifecycle.

Beyond AGENTS.md, nointern runtime needs providers to observe runtime lifecycle or initialize, clean up, and compact their owned state. For example, providers may prepare state at first session start, inject additional user prompt at turn start, perform policy-like deny before tool calls, and sync provider-owned state on sandbox hibernate/restore. If these needs are added as branches in individual code paths, hook authors get a complex mental model and runtime adapter accumulates provider-specific special logic.

At the same time, external plugin runtime, model-call interception, and arbitrary mutation/continuation framework are larger and riskier than current needs. Therefore, keep the current Toolkit boundary as provider boundary, while acknowledging that the name may more accurately become runtime capability provider long term, and define a simple runtime hook system.

## Decision

Keep current `Toolkit` as the runtime capability provider boundary and let it register lifecycle callbacks through `Toolkit.hooks() -> RuntimeHooks`. `RuntimeHooks` is `TypedDict(total=False)` and maps lifecycle names to callback functions.

- Do not add many no-op methods directly to Toolkit.
- Do not discover hooks through duck typing or method existence checks.
- Each lifecycle key has at most one callback per provider. If provider-local composition is needed, the provider does it internally.
- Provider order per lifecycle uses the provider snapshot available at dispatch time as source of truth. Session/run hooks use resolved `RunRequest.toolkits` order. Turn/tool hooks use active provider order finalized by that turn's `update_context()` result. Sandbox hooks can happen outside run request, so they resolve the current provider snapshot from sandbox `agent_runtime_id` / `session_id`; resolve failure does not block hibernate/restore and is traced then skipped.
- Hook runner automatically records provider, lifecycle, result, exception, duration, and short-circuit status in structured logs and test trace sink. It does not store raw args, raw output, prompt, or credentials in trace.

First implementation is limited to these lifecycles:

- Session: `on_session_start`, `on_session_clear`, `on_session_compact`
- Run: `on_run_start`, `on_run_end`
- Turn: `on_turn_start`, `on_turn_end`
- Tool: `on_before_tool_call`, `on_after_tool_call`
- Sandbox: `on_sandbox_hibernate`, `on_sandbox_restore`

Model lifecycle hooks are excluded from the first implementation and reserved. Do not define `on_before_model_call` or `on_after_model_call`. Memory, external event, and attachment lifecycle are still conceptually unclear, so exclude them entirely from the taxonomy.

Do not create one universal `HookResult`; instead, define small result types needed per lifecycle. Observation-only hooks return `None`. Arbitrary mutation, continuation, and retry wrapper models are not provided.

Tool lifecycle follows these policies:

- `on_before_tool_call` returns discriminated union `ToolCallDecision`.
- MVP variants are only `allow` and `deny(message)`.
- Deny message must be English user/model-facing text.
- The first deny in active provider order short-circuits the tool call.
- Hook exception is logged and treated as allow. Cancellation propagates.
- In MVP, `on_after_tool_call` can modify only model-facing normalized text output.
- After hook runs after normalizing the handler result into the text channel delivered to the model, not on raw handler result. This includes `FunctionToolError`, unexpected error message, `BackgroundHandle.initial_message`, and text `FunctionToolResult`. For image/list output, MVP treats only the text channel as replacement target; the image artifact itself is not modified by the hook.
- After hook pipeline runs before output cap is applied, and existing output cap is reapplied to pipeline result.
- After hooks run as a pipeline; each hook receives output text modified by the previous hook.
- Result union is `unchanged` and `replace_output(output_text)`.
- After hook exception is logged and treated as unchanged. Cancellation propagates.

Turn lifecycle follows these policies:

- `on_turn_start` can inject additional user prompt.
- Hook chooses prompt persistence between `visible_user_input` and `hidden_internal_input`.
- Both persistence modes are included in the first implementation.
- Additional prompt is stored in event-based history so replay/resume can see it. Visible prompt is stored through the existing `UserInputEvent` family with hook/provider source metadata. Hidden prompt is not exposed in UI transcript, but add an internal event type that model input formatter converts to user-role input.
- `on_turn_end` receives mandatory reason.
- A started turn must dispatch `on_turn_end` exactly once within a single-process execution scope through turn scope or try/finally. A durable exactly-once ledger covering worker crash/recovery is out of scope for first implementation; recovery boundaries may have at-least-once or missing trace, handled by trace and idempotent hook authoring guidance.
- If reason is unset, record `unknown` reason with warning.

Run lifecycle has only `on_run_start` and `on_run_end`. Do not create separate `on_run_error` or `on_run_cancel`; instead, `on_run_end.reason` is `completed`, `error`, `cancelled`, or `unknown`. A started run must dispatch `on_run_end` exactly once within a single-process execution scope. Durable hook completion ledger for crash-safe exactly-once is out of scope for first implementation.

Session lifecycle supports one-time first start over session lifetime and session-scoped provider state reset/compact. First dispatch claim for `on_session_start` uses conditional update on a session row marker such as `agent_sessions.lifecycle_started_at`, not event store lookup. `on_session_clear` and `on_session_compact` cannot block or alter session operations.

Sandbox lifecycle uses sandbox terminology, not session terminology. `on_sandbox_hibernate` and `on_sandbox_restore` are observation/state-update only and cannot change hibernate/restore behavior. This runtime hook system does not replace the existing sandbox manager lifecycle hook family such as `AFTER_START`, `BEFORE_STOP`, and `ON_IDLE_TIMEOUT`. The new sandbox hook is a callback that notifies providers after sandbox manager has made lifecycle decisions.

Prompt/context model does not introduce `PromptBlock` or `ContextBlock`. Hooks do not directly own prompt assembly. Providers may update provider-owned internal/persistent state in hooks and expose prompts through existing `update_context()` and `ToolkitState.prompt`. AGENTS.md remains a stateful observer + prompt provider following this pattern.

This decision supersedes [toolkit-260514/ADR](./toolkit-260514-toolkit-hooks-for-agents-md.md)'s observation-only tool hook constraint only within explicit deny in `on_before_tool_call` and text output replacement in `on_after_tool_call`. Provider-owned state/prompt ownership, `update_context()` prompt assembly, and AGENTS.md stateful observer pattern from [toolkit-260514/ADR](./toolkit-260514-toolkit-hooks-for-agents-md.md) remain in effect.

## Consequences

- Runtime needs lifecycle-specific hook context/result types and a common dispatcher.
- `Toolkit` interface gets a `hooks()` registration surface instead of no-op lifecycle methods.
- A marker column may be needed on `agent_sessions` for first session start claim.
- Turn start prompt injection must connect to an event or message storage path readable by replay/resume.
- Because tool deny and output replacement become possible, provider order, trace, and user/model-facing message policy become runtime contracts.
- Hook exceptions are mostly fail-open, but cancellation propagates, so hook authors must consider cancellation safety.
- Durable DB audit and OTel export remain future extensions; initial evidence source is structured log and test trace sink.

## Considered Options

### Option A — Add no-op methods per lifecycle to Toolkit

Each lifecycle can be represented by an explicit method, improving IDE discoverability. But as lifecycles grow, every Toolkit subclass inherits a large no-op surface, and it becomes hard to distinguish unsupported hooks from implementation omissions. This option is not adopted.

### Option B — Method existence check through duck typing

This reduces class shape changes. However, runtime capabilities are not explicitly registered, so typos and signature drift are detected late, and hook author mental model depends on implicit per-provider method lists. This option is not adopted.

### Option C — Universal HookResult and continuation/retry wrapper

Handling every lifecycle with one result protocol generalizes the dispatcher. But it unnecessarily broadens possible effects per lifecycle and mixes arbitrary mutation, retry, and continuation semantics, making safe failure policy hard to explain. This option is not adopted.

### Option D — Include model lifecycle hooks

Model-call before/after hooks directly connect to prompt, sampling, provider payload, streaming events, and token usage. Permission, security, deterministic replay, and prompt secrecy policies must be finalized first, so they are not included in the first runtime hook taxonomy.

### Option E — Use current Toolkit boundary as provider boundary

The name Toolkit suggests tool bundle, but in current runtime it is the execution boundary that provides tools, prompt, credential, and context. We can define the hook system contract without introducing a separate provider abstraction first, and leave long-term rename possibility as a conceptual note. This option is adopted.

## Acceptance Criteria

- Runtime hook registration is defined as `Toolkit.hooks() -> RuntimeHooks`.
- `RuntimeHooks` is described as `TypedDict(total=False)` lifecycle-to-callback mapping.
- First lifecycle taxonomy is limited to session, run, turn, tool, and sandbox.
- Model, memory, external event, and attachment lifecycle are excluded from the first taxonomy.
- Only lifecycle-specific result types are used, without universal `HookResult`.
- Observation-only hooks return `None`.
- Before-tool allow/deny short-circuit, exception fail-open, and cancellation propagation policies are specified.
- After-tool text-only replacement pipeline and failure policy are specified.
- Turn/run end are defined as dispatched exactly once per started scope within a single-process execution scope.
- Session start first dispatch claim is defined as session row marker conditional update, not event store scan.
- Hook trace is automatically recorded through structured log and test trace sink, and does not store raw args/output/prompt/credential.

## Migration provenance

- Historical source filename: `0033-runtime-hook-system.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
