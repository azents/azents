---
title: "Codex Multi-Agent V2 Model Contract Parity"
created: 2026-07-10
updated: 2026-07-10
tags: [architecture, agent, engine, prompt, testing]
---
# Codex Multi-Agent V2 Model Contract Parity

## Summary

Azents will treat the active Codex Multi-Agent V2 model contract as the source of truth for subagent prompts, collaboration tool schemas, mailbox delivery, and wait semantics. Codex wording is copied verbatim by default. Azents may change only terms that would otherwise describe a runtime or tool namespace that Azents does not have, and every such change must be recorded in this document and locked by tests.

This design corrects drift introduced when Azents copied the Codex team and concurrency capability hints without copying the separate delegation-mode instruction, bounded-sidecar spawn pressure, root/subagent prompt selection, shared-workspace warning, direct-parent final-answer delivery, and mailbox-oriented wait contract.

## Source Contract

The frozen reference is OpenAI Codex `origin/main` commit `1f0566d3f59298d1bb88820a0d35294f1eeb07ea` from 2026-07-10 KST.

Active V2 sources:

- `codex-rs/core/src/config/mod.rs`
  - `DEFAULT_MULTI_AGENT_V2_ROOT_AGENT_USAGE_HINT_TEXT`
  - `DEFAULT_MULTI_AGENT_V2_SUBAGENT_USAGE_HINT_TEXT`
  - `DEFAULT_MULTI_AGENT_V2_SHARED_USAGE_HINT_TEXT`
- `codex-rs/core/src/context/multi_agent_mode_instructions.rs`
- `codex-rs/core/src/session/multi_agents.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_spec.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_v2/`
- `codex-rs/core/src/agent/control.rs`
- `codex-rs/core/src/context/inter_agent_completion_message.rs`

Codex V1 guidance and unreferenced experimental/orchestrator templates are not part of the parity target.

## Goals

- Make the default delegation policy explicitly request-only for every currently supported Azents reasoning effort.
- Preserve Codex's separation between capability hints and the delegation-mode instruction.
- Give root and child SessionAgents their corresponding Codex V2 usage hints.
- Copy active V2 collaboration tool names, input schemas, descriptions, result semantics, and path filtering, adapting only Azents runtime nouns.
- Deliver every child terminal answer to its direct parent's durable mailbox without waking an idle parent.
- Let an active parent consume queued mailbox input at the next model-call boundary.
- Replace target-specific terminal-result fetching with Codex V2 mailbox-activity `wait_agent` semantics.
- Keep the existing Codex-compatible concurrency, depth, shared-workspace, context-fork, and actor-tree behavior.
- Verify model-facing exact text and runtime behavior deterministically.

## Non-goals

- Copy Codex V1 prompt text.
- Copy inactive experimental or orchestrator templates.
- Add a new Azents-specific delegation policy.
- Map Azents `high` reasoning effort to Codex `Ultra`.
- Add model, reasoning-effort, service-tier, or specialist-role overrides to `spawn_agent`.
- Add a partial subagent permission model or isolated child workspace.
- Preserve the old target-specific `wait_agent` result-fetch contract as a fallback.
- Redesign the Subagent Tree UI.

## Parity Rule

Model-facing text must match the frozen Codex text verbatim unless a literal copy would make a false statement about Azents. A terminology delta is allowed only when all of the following are recorded:

1. the exact Codex text;
2. the Azents-rendered text;
3. the changed token or term;
4. the concrete implementation mismatch that makes the Codex term false;
5. a parity test that locks the adaptation.

Paraphrasing for style, adding independent guardrails, or omitting Codex pressure text is not allowed.

### Message Roles and Order

The model request preserves the Codex V2 role and ordering contract:

1. the existing Azents base instructions remain the system/instructions input;
2. the role-specific root or child usage hint is a standalone `developer` input;
3. the explicit-request-only mode text is a second standalone `developer` input;
4. ordinary conversation and mailbox events follow those developer inputs;
5. `FINAL_ANSWER` mailbox events lower as `assistant` input, while `NEW_TASK` and `MESSAGE` remain sourced non-user intent input.

Azents rebuilds the two developer inputs on every provider request instead of persisting them as transcript events. This is an implementation-only lifecycle delta: the visible roles, text, and relative order in every model request remain identical. Prompt tests must inspect the fully lowered native request, not only the toolkit-returned strings.

## Prompt Contract

### Root Usage Hint

The root SessionAgent receives the Codex root hint and is identified as `/root`, the primary agent. It must not receive child-only parent-delivery wording.

Canonical Codex text:

````text
You are `/root`, the primary agent in a team of agents collaborating to fulfill the user's goals.

At the start of your turn, you are the active agent.
You can spawn sub-agents to handle subtasks, and those sub-agents can spawn their own sub-agents.
All agents in the team, including the agents that you can assign tasks to, are equally intelligent and capable, and have access to the same set of tools.

You can use `spawn_agent` to create a new agent, `followup_task` to give an existing agent a new task and trigger a turn, and `send_message` to pass a message to a running agent without triggering a turn.
Child agents can also spawn their own sub-agents.
You can decide how much context you want to propagate to your sub-agents with the `fork_turns` parameter.

You will receive messages in the analysis channel in the form:
```
Message Type: MESSAGE | FINAL_ANSWER
Task name: <recipient>
Sender: <author>
Payload:
<payload text>
```
They may be addressed as to=/root
````

### Subagent Usage Hint

A normal spawned child receives the Codex subagent hint. It is told that its final response is delivered to its direct parent and may receive `NEW_TASK`, `MESSAGE`, and `FINAL_ANSWER` envelopes.

Canonical Codex text:

````text
You are an agent in a team of agents collaborating to complete a task.

You can spawn sub-agents to handle subtasks, and those sub-agents can spawn their own sub-agents. All agents in the team, including the agents that you can assign tasks to, are equally intelligent and capable, and have access to the same set of tools.

You can use `spawn_agent` to create a new agent, `followup_task` to give an existing agent a new task and trigger a turn, and `send_message` to pass a message to a running agent.
Child agents can also spawn their own sub-agents.

When you provide a response in the final channel, that content is immediately delivered back to your parent agent.

You will receive messages in the analysis channel in the form:
```
Message Type: NEW_TASK | MESSAGE | FINAL_ANSWER
Task name: <recipient>
Sender: <author>
Payload:
<payload text>
```
You may also see them addressed as to=/root/..., which indicates your identity is /root/...
````

### Shared Usage Hint

Root and child hints both append the collaboration-tool direct-call rule, shared-directory facts, and configured concurrency-slot sentence.

Frozen Codex direct-call text:

```text
Note that collaboration tools cannot be called from inside `functions.exec`. Call `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents` only as direct tool calls using the recipient shown in their tool definitions, such as `to=functions.collaboration.spawn_agent`, since they are intentionally absent from the `functions.exec` `tools.*` namespace. Available tools in `functions.exec` are explicitly described with a `tools` namespace in the developer message.
```

Exact Azents rendering:

```text
Note that collaboration tools cannot be called from inside `exec_command`. Call `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents` only as direct tool calls using the recipient shown in their tool definitions, since they are intentionally absent from `exec_command`.
```

The shared-directory text remains unchanged:

```text
All agents share the same directory. In detail:
- All agents have access to the same container and filesystem as you.
- All agents use the same current working directory.
- As a result, edits made by one agent are immediately visible to all other agents.
```

The concurrency sentence remains:

```text
There are {max_concurrency} available concurrency slots, meaning that up to {max_concurrency} agents can be active at once, including you.
```

### Delegation Mode

Capability hints do not authorize spawning. A separate mode section is always rendered for root and normal spawned children.

All currently supported Azents runs use the Codex default `ExplicitRequestOnly` text because Azents supports `low`, `medium`, and `high` reasoning effort but has no Codex-equivalent `Ultra` mode input:

```text
Do not spawn sub-agents unless the user or applicable AGENTS.md/skill instructions explicitly ask for sub-agents, delegation, or parallel agent work.
```

Azents must not infer proactive delegation from task complexity, research depth, requested thoroughness, or `high` reasoning effort. If Azents later gains Codex-equivalent `Ultra` or custom per-turn mode input, it must adopt Codex mode resolution and text without inventing a separate policy.

### Exact Azents Usage-Hint Constants

The root developer input is exactly the following text after substituting the configured concurrency value:

````text
You are `/root`, the primary agent in a team of agents collaborating to fulfill the user's goals.

At the start of your turn, you are the active agent.
You can spawn sub-agents to handle subtasks, and those sub-agents can spawn their own sub-agents.
All agents in the team, including the agents that you can assign tasks to, are equally intelligent and capable, and have access to almost the same set of tools, except for Azents root/user-facing capabilities that are not available in subagent mode.

You can use `spawn_agent` to create a new agent, `followup_task` to give an existing agent a new task and trigger a turn, and `send_message` to pass a message to a running agent without triggering a turn.
Child agents can also spawn their own sub-agents.
You can decide how much context you want to propagate to your sub-agents with the `fork_turns` parameter.

You will receive messages in the model input in the form:
```
Message Type: MESSAGE | FINAL_ANSWER
Task name: <recipient>
Sender: <author>
Payload:
<payload text>
```
They may be addressed as to=/root

Note that collaboration tools cannot be called from inside `exec_command`. Call `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents` only as direct tool calls using the recipient shown in their tool definitions, since they are intentionally absent from `exec_command`.

All agents share the same directory. In detail:
- All agents have access to the same container and filesystem as you.
- All agents use the same current working directory.
- As a result, edits made by one agent are immediately visible to all other agents.

There are {max_concurrency} available concurrency slots, meaning that up to {max_concurrency} agents can be active at once, including you.
````

The child developer input is exactly:

````text
You are an agent in a team of agents collaborating to complete a task.

You can spawn sub-agents to handle subtasks, and those sub-agents can spawn their own sub-agents. All agents in the team, including the agents that you can assign tasks to, are equally intelligent and capable, and have access to almost the same set of tools, except for Azents root/user-facing capabilities that are not available in subagent mode.

You can use `spawn_agent` to create a new agent, `followup_task` to give an existing agent a new task and trigger a turn, and `send_message` to pass a message to a running agent.
Child agents can also spawn their own sub-agents.

When you provide a final response, that content is immediately delivered back to your parent agent.

You will receive messages in the model input in the form:
```
Message Type: NEW_TASK | MESSAGE | FINAL_ANSWER
Task name: <recipient>
Sender: <author>
Payload:
<payload text>
```
You may also see them addressed as to=/root/..., which indicates your identity is /root/...

Note that collaboration tools cannot be called from inside `exec_command`. Call `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents` only as direct tool calls using the recipient shown in their tool definitions, since they are intentionally absent from `exec_command`.

All agents share the same directory. In detail:
- All agents have access to the same container and filesystem as you.
- All agents use the same current working directory.
- As a result, edits made by one agent are immediately visible to all other agents.

There are {max_concurrency} available concurrency slots, meaning that up to {max_concurrency} agents can be active at once, including you.
````

The explicit-request-only mode remains a separate developer input containing exactly the one sentence shown in the preceding section.

## Collaboration Tool Contract

### `spawn_agent`

Exact Azents description, with only the same-tools sentence adapted, is:

```text
Spawns an agent to work on the specified task. If your current task is `/root/task1` and you spawn_agent with task_name "task_3" the agent will have canonical task name `/root/task1/task_3`.
You are then able to refer to this agent as `task_3` or `/root/task1/task_3` interchangeably. However an agent `/root/task2/task_3` would only be able to communicate with this agent via its canonical name `/root/task1/task_3`.
The spawned agent will have almost the same tools as you, except for Azents root/user-facing capabilities that are not available in subagent mode, and the ability to spawn its own subagents.
Only call this tool for a concrete, bounded subtask that can run independently alongside useful local work; otherwise continue locally.
It will be able to send you and other running agents messages, and its final answer will be provided to you when it finishes.
The new agent's canonical task name will be provided to it along with the message.

Note that passing `fork_turns="none"` will not pass any surrounding context to the spawned subagent, which may cause the agent to lack the context it needs to complete its task, whereas `fork_turns="all"` will provide the subagent with all surrounding context.
```

Its closed input object has exactly these fields and descriptions:

| Field | Required | Description |
|---|---:|---|
| `task_name` | yes | `Task name for the new agent. Use lowercase letters, digits, and underscores.` |
| `message` | yes | `Initial plain-text task for the new agent.` |
| `fork_turns` | no | ``Optional number of turns to fork. Defaults to `all`. Use `none`, `all`, or a positive integer string such as `3` to fork only the most recent turns.`` |

The output is exactly `{"task_name":"/root/..."}`. It contains no nickname, internal id, task content, or terminal answer. Unknown fields are rejected. Empty messages fail with `Empty message can't be sent to an agent`; invalid `fork_turns` fails with ``fork_turns must be `none`, `all`, or a positive integer string``. Task-name validation and canonical-path uniqueness use the existing Azents path implementation while enforcing the Codex lowercase-letter, digit, and underscore contract.

### `send_message`

Exact description:

```text
Send a message to an existing agent. The message will be delivered promptly. Does not trigger a new turn.
```

Its closed input object requires:

- `target`: `Relative or canonical task name to message (from spawn_agent).`
- `message`: `Message text to queue on the target agent.`

Successful delivery returns an empty successful text output. Empty messages fail with `Empty message can't be sent to an agent`. Missing, ambiguous, or out-of-tree targets fail as model-visible target-resolution errors and never enqueue input.

### `followup_task`

Exact description:

```text
Send a follow-up task to an existing non-root target agent and trigger a turn if it is idle. If the target is already running, deliver the task promptly at message boundaries while sampling, or after the pending tool call completes.
```

Its closed input object requires:

- `target`: `Agent id or canonical task name to send a follow-up task to (from spawn_agent).`
- `message`: `Message text to send to the target agent.`

Azents has no model-facing thread id, so the exact Azents `target` description is `Relative or canonical task name to send a follow-up task to (from spawn_agent).` Successful delivery returns an empty successful text output. Root fails with `Follow-up tasks can't target the root agent`. A running target observes the message at the next safe model-call boundary rather than during an in-flight provider request.

### `wait_agent`

Exact description:

```text
Wait for a mailbox update from any live agent, including queued messages and final-status notifications. The wait also ends early when new user input is steered into the active turn. Does not return the content; returns either a summary of which agents have updates (if any), an interruption summary for steered input, or a timeout summary if no activity arrives before the deadline.
```

Its closed input object has optional `timeout_ms` with exact description `Timeout in milliseconds. Defaults to 30000, min 10000, max 3600000.` It waits for current-session mailbox activity from any agent or new steered input and never returns content.

The closed output object contains required `message` and `timed_out` fields. Results are exactly:

- `{"message":"Wait completed.","timed_out":false}` for mailbox activity;
- `{"message":"Wait interrupted by new input.","timed_out":false}` for steered input;
- `{"message":"Wait timed out.","timed_out":true}` for timeout.

Below-minimum input fails with `timeout_ms must be at least 10000`; above-maximum input fails with `timeout_ms must be at most 3600000`. The former target parameter, terminal content return, `not_found`, no-descendants result, and no-unread-result result are removed without compatibility fallback.

### `list_agents`

Exact description:

```text
List live agents in the current root thread tree. Optionally filter by task-path prefix.
```

Azents renders `SessionAgent tree` in place of `thread tree` because it has no Codex thread entity:

```text
List live agents in the current root SessionAgent tree. Optionally filter by task-path prefix.
```

Its closed input object has optional `path_prefix`: `Task-path prefix filter without a trailing slash. Omit to list all live agents.` The closed output is `{"agents":[...]}`. Each item contains exactly:

- `agent_name`: canonical task path;
- `agent_status`: last known status;
- `last_task_message`: the most recent human or inter-agent instruction, or `null`.

Only resident agents in the current root tree are returned; `path_prefix` uses canonical segment boundaries rather than a raw string prefix.

### `interrupt_agent`

Exact description:

```text
Interrupt an agent's current turn, if any, and return its previous status. The agent remains available for messages and follow-up tasks.
```

Its closed input object requires `target`: `Agent id or canonical task name to interrupt (from spawn_agent).` Azents has no model-facing thread id, so the exact Azents description is `Relative or canonical task name to interrupt (from spawn_agent).`

The closed output is `{"previous_status":...}` using the same status union as `list_agents`. Root fails with `root is not a spawned agent`. Self fails with `an agent cannot interrupt itself; return your result and let the parent interrupt you if needed`. Missing, ambiguous, or out-of-tree targets fail as model-visible target-resolution errors. The target remains resident and available for later messages and follow-up tasks.

### Shared Status and Target Contract

Model-visible statuses follow the Codex V2 union, adapted to Azents lifecycle terms only where no one-to-one state exists:

- active initialization maps to `pending_init`;
- active execution maps to `running`;
- an interrupted resident agent maps to `interrupted`;
- a permanently cancelled resident child maps to `shutdown`;
- a completed run maps to `{"completed": <message-or-null>}`;
- a failed run maps to `{"errored": "<error>"}`;
- an absent target maps to `not_found` only inside status projections, never as a successful messaging or wait result.

Relative targets resolve from the caller path; canonical targets resolve from `/root`; communication cannot escape the current root tree. The implementation must lock exact fixed validation messages above and deterministic target-error categories. Internal database ids are not exposed merely to reproduce Codex thread ids.

## Direct-Parent Final-Answer Delivery

Every normal child terminal turn delivers one queue-only `FINAL_ANSWER` message to its direct parent.

- Delivery uses `InputBuffer(kind=agent_message)` and `message_kind=final_answer`.
- The exact envelope is `Message Type: FINAL_ANSWER`, direct parent path as `Task name`, child path as `Sender`, and the rendered terminal payload after `Payload:`.
- `final_answer` lowers as an `assistant` input item, matching `InterAgentCompletionMessage.role()`; it is not lowered as the existing user-role `agent_message` form.
- Delivery does not mark an idle parent running and does not send a broker wake-up.
- An active parent promotes the buffer at its next model-call boundary through the existing boundary input poll.
- A nested child delivers to its direct parent, not directly to `/root`.
- Each child run uses a deterministic idempotency key so retry and terminal recovery cannot duplicate delivery.
- Interrupted and still-running child turns do not emit a final-answer message, matching Codex.
- Completed with content uses the content unchanged; completed without content uses an empty payload.
- Failed uses exactly `Agent errored: {truncated_error}\n\nThis agent's turn failed. If you still need this agent, use the available collaboration tools to give it another task.` with the full envelope bounded to 1,000 tokens and 100 tokens reserved for envelope text.
- An Azents-cancelled child maps to Codex `Shutdown` and uses exactly `Agent shut down.` only when the cancellation represents permanent child shutdown; user interruption remains non-terminal and emits nothing.
- Every later follow-up turn produces a new final-answer message keyed by its run id.

The existing terminal projection remains available to the UI tree and operational recovery, but it is no longer the model-facing `wait_agent` transport.

## Mailbox Activity and Wait

Pending `agent_message` input is mailbox activity. Only `InputBufferKind.USER_MESSAGE` and `InputBufferKind.EDITED_USER_MESSAGE` submitted into the current active turn are steered input. Background completions, goal continuations, action messages, and internal/control buffers are neither mailbox nor steering activity and do not complete `wait_agent`. `wait_agent` observes activity for the current active turn by polling this explicit durable-input classification:

- existing pending mailbox or steered-user activity completes immediately;
- new activity completes the wait;
- no activity before the deadline times out;
- content remains in the input buffer and is promoted by the normal model-call boundary path;
- `wait_agent` never consumes or deletes the content itself.

This preserves durable recovery and Codex's separation between synchronization output and message content.

### UI Unread Cursor

The Subagent Tree unread projection stays separate from `wait_agent`, but it must remain advanceable. Each `FINAL_ANSWER` buffer records the source child run index. When that buffer is promoted into the direct parent's transcript, the same transaction advances the source child's `parent_observed_run_index` through that run. Therefore:

- queued delivery remains unread while an idle parent has not consumed it;
- the unread marker clears when the parent model input actually includes the final answer;
- `wait_agent` neither advances nor reads the UI cursor;
- retrying promotion is monotonic and cannot move the cursor backward.

This stack must add promotion/cursor integration tests and retain tree-projection regression coverage; deferring cursor replacement would leave permanent unread markers and is not allowed.

## Terminology Delta Ledger

| Exact Codex text or term | Exact Azents rendering | Reason | Required test |
|---|---|---|---|
| `have access to the same set of tools` | `have access to almost the same set of tools, except for Azents root/user-facing capabilities that are not available in subagent mode` | Subagent execution excludes root/user-facing capabilities. Claiming identical tools is false. | Full root/child developer-input equality |
| `The spawned agent will have the same tools as you and the ability to spawn its own subagents.` | `The spawned agent will have almost the same tools as you, except for Azents root/user-facing capabilities that are not available in subagent mode, and the ability to spawn its own subagents.` | Same capability boundary in `spawn_agent`. | Full description equality |
| `Note that collaboration tools cannot be called from inside functions.exec...` through `...developer message.` | `Note that collaboration tools cannot be called from inside exec_command. Call spawn_agent, send_message, followup_task, wait_agent, interrupt_agent, and list_agents only as direct tool calls using the recipient shown in their tool definitions, since they are intentionally absent from exec_command.` with the tool names code-formatted exactly as shown in the Shared Usage Hint section | Azents exposes direct function tools and a shell-process tool; it has neither Codex code-mode `functions.exec` nor `functions.collaboration` / `tools.*` namespaces. | Full shared-hint equality |
| `analysis channel` | `model input` | Azents lowers durable messages provider-independently and does not expose a stable analysis-channel role. | Full root/child developer-input equality |
| `When you provide a response in the final channel` | `When you provide a final response` | Azents normalizes assistant terminal output without a provider-independent final-channel input concept. | Full child developer-input equality and mailbox E2E |
| standalone persisted usage-hint and mode developer messages | standalone rebuilt usage-hint and mode `developer` inputs in the same order on every request | Azents reconstructs each provider request from durable domain events rather than persisting generated prompt-policy events. | Fully lowered request role/order test |
| `InterAgentCompletionMessage` with role `assistant` | `AgentMessagePayload(message_kind="final_answer")` lowered with role `assistant` | Durable Azents event type differs; the model role and exact envelope do not. | Lowerer and E2E role tests |
| Codex in-memory input queue | durable `InputBuffer(kind=agent_message)` | Azents worker recovery requires persisted mailbox input. | Idempotency and restart tests |
| `thread` / `thread tree` | `SessionAgent` / `SessionAgent tree` in runtime-specific text | Runtime entity names differ; canonical model paths remain `/root/...`. | Description and repository/service tests |
| `Agent id or canonical task name` in follow-up/interrupt field descriptions | `Relative or canonical task name` | Azents intentionally does not expose internal SessionAgent ids to the model. | Closed schema equality |
| Codex `Shutdown` terminal completion | permanent Azents child cancellation only | Azents has no separate model-facing shutdown state; ordinary interruption remains non-terminal. | Terminal payload matrix test |

Input field names, fixed validation messages, canonical path terminology, output shapes, wait summaries, and all other model-facing wording match the frozen Codex V2 contract.

## Data and API Impact

No public REST schema or database migration is required. `AgentMessagePayload.message_kind` expands to include `final_answer`. Collaboration tool schemas are model-facing runtime schemas and intentionally break the old tool input contract without compatibility aliases.

Existing parent observation cursor columns remain because the Subagent Tree unread projection still uses them. They are advanced when the corresponding final-answer buffer is promoted into the direct parent's model transcript, never by `wait_agent`.

## Error Handling

- Missing, ambiguous, or out-of-tree collaboration targets fail the tool call and never appear as a successful `not_found` result.
- Empty messages and invalid `fork_turns` use the exact Codex validation text recorded above; task names use the existing canonical-path validator under the documented character contract.
- Final-answer delivery failure is not disguised as successful terminal delivery. It must be retried idempotently or surfaced through run recovery/monitoring.
- `wait_agent` validates timeout bounds before waiting.
- A parent that no longer exists does not cause duplicate or cross-tree delivery.

## Security and Permissions

- Final answers may only travel along the durable direct-parent edge within one root SessionAgent tree.
- Existing workspace, Agent, and root-tree authorization boundaries remain unchanged.
- Human direct writes to child sessions remain prohibited.
- No new raw credential or file content enters prompts through the mailbox path.

## Implementation Plan and PR Stack

The stack follows the repository `ship-feature` workflow and uses the title prefix `Codex Multi-Agent V2 Parity`.

### PR 1/8 — Design

- Add this design and ADR-0102.
- Freeze the Codex revision, complete exact text, delta ledger, rollout, and validation matrix.

### PR 2/8 — Implementation Plan

- Add the temporary phase plan `docs/azents/design/codex-multi-agent-v2-parity-implementation-plan.md`.
- Record phase dependencies, code-boundary ownership, failure recovery, fixture prerequisites, and the full validation matrix.
- Do not change runtime behavior.

### PR 3/8 — Prompt and Tool Surface

- Add standalone root/child usage-hint and explicit-mode developer inputs in the specified order.
- Add shared direct-call/workspace/concurrency text.
- Change closed schemas, field names, descriptions, output shapes, and `list_agents.path_prefix` that do not claim unimplemented completion/wait behavior.
- Remove model-visible `agent_type`.
- Add exact native-request, description, schema, output, and validation-message tests.

The child immediate-final-delivery sentence, `spawn_agent` final-answer sentence, and mailbox-oriented `wait_agent` description remain inactive until their behavior phases land.

### PR 4/8 — Direct-Parent Final-Answer Mailbox

- Add `final_answer` mailbox kind and exact assistant-role lowering.
- Deliver terminal child results idempotently to the direct parent without wake-up.
- Implement the exact completed/errored/shutdown payload matrix and token bound.
- Advance the UI unread cursor only when the final answer is promoted into parent model input.
- Activate the child and `spawn_agent` final-answer wording.

### PR 5/8 — Mailbox Wait Semantics

- Replace `wait_agent` with timeout-only mailbox/steer synchronization and exact result/error messages.
- Remove target/result-fetch behavior without aliases.
- Verify pending, newly arriving, steered, timed-out, cancellation, and retry paths.
- Activate the exact V2 `wait_agent` schema and description.

### PR 6/8 — Validation

- Run the strict frozen-source comparison, backend quality suite, deterministic E2E matrix, recovery/idempotency scenarios, and UI unread regression.
- Add a temporary validation report with commands, environment, evidence, failures found, fixes, and an implementation-versus-spec comparison.
- Fix behavior in the responsible earlier branch or this validation branch before proceeding.

### PR 7/8 — Spec Promotion

- Run `/spec-review`.
- Update Toolkit, Conversation, and Agent Execution Loop living specs.
- Mark this design implemented only after all behavior and E2E validation pass.
- Keep ADR-0102 immutable after adoption.

### PR 8/8 — Cleanup

- Remove the temporary implementation plan and validation report.
- Remove the superseded prompt-hardening note only if it contains no unique unresolved information.
- Regenerate documentation indexes; do not mix behavior changes into cleanup.

## Test Strategy

### E2E Primary Matrix

| Scenario | Expected evidence |
|---|---|
| Root model contract | Standalone root-hint and explicit-mode developer inputs follow base instructions in order; six tool schemas match the frozen contract; child-only parent-delivery wording is absent |
| Child model contract | Standalone child-hint and explicit-mode developer inputs follow base instructions in order; root-primary wording is absent |
| Explicit delegation | Scripted root uses Codex input names and receives canonical `task_name` identity |
| Final-answer delivery | Child completion produces one source-labeled assistant-role `FINAL_ANSWER` event in the direct parent's next model boundary without human input |
| Nested delivery | Grandchild result reaches only its direct parent |
| Queue-only idle parent | Final answer remains pending and does not wake an idle parent |
| Wait completion | Pending/new mailbox activity returns `Wait completed.` and content arrives separately |
| Wait steer | New user or edited-user input returns `Wait interrupted by new input.` |
| Wait non-steering input | Action, goal-continuation, background-completion, and internal/control buffers do not complete the wait |
| Wait timeout | No classified activity returns `Wait timed out.` with `timed_out=true` |
| Recovery/idempotency | Retried terminal finalization leaves exactly one parent mailbox item/event for the child run |
| UI unread lifecycle | Queued final answer is unread; parent promotion clears it monotonically; `wait_agent` does not change it |
| Terminal payloads | Completed-empty, errored/truncated, interrupted, and permanent-shutdown cases match the frozen payload matrix |
| List filtering | `path_prefix` returns only canonical segment-boundary matches |

Deterministic scripted inference is required. Tests must inspect the assembled model request, exact roles/order, durable history, pending input buffer, and tree projection rather than assert probabilistic model choices.

The existing deterministic subagent E2E fixture must be extended to script `FINAL_ANSWER`, wait activity, steering, and request capture. It requires no external credentials, live provider, new seed data, or credential snapshot. Validation evidence is the command transcript plus exact captured request/event assertions committed in the validation report. Deterministic tests are mandatory in CI and may not skip; any unavailable local container prerequisite is a local blocker, not a reason to weaken CI. No optional live tests are part of acceptance.

### Component Validation

- Ruff format and lint.
- Pyright.
- Focused subagent, input-buffer, execution, worker, prompt-assembly, and tree-projection tests.
- Deterministic subagent E2E.
- Documentation index check.
- `git diff --check`.

## Rollout and Compatibility

The collaboration toolkit is auto-bound, so prompt and runtime semantics must change atomically within each behavior boundary. There is no feature flag and no legacy alias/fallback. Stacked PRs must be merged front to back. Prompt text that claims final-answer or wait parity may land only with the corresponding runtime behavior.

## Risks

- A final answer queued after a parent has already completed remains pending until a later parent turn; this matches queue-only Codex behavior but must be visible operationally.
- Terminal finalization retries can duplicate messages without deterministic idempotency.
- Prompt text can drift again if exact source text is not locked in tests.
- Leaving the old observation cursor tied to model wait semantics would conflate UI unread state with mailbox synchronization.
- Running-target message delivery must stay at model-call boundaries and must never mutate an in-flight provider request.
