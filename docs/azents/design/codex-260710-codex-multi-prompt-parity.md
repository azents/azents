---
title: "Codex Multi-Agent V2 Subagent Prompt Parity"
created: 2026-07-10
updated: 2026-07-10
implemented: 2026-07-10
tags: [agent, engine, prompt, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: codex-260710
migration_source: "docs/azents/design/codex-multi-agent-v2-prompt-parity.md"
historical_reconstruction: true
---

# Codex Multi-Agent V2 Subagent Prompt Parity

## Problem

Azents currently emits one generic subagent collaboration prompt for both the root agent and spawned children. The prompt mixes Azents-specific lifecycle guidance with collaboration policy, omits the Codex root/child distinction, and does not include the Codex shared-workspace or explicit-request-only guidance.

The requested change is prompt parity only. It must not redesign or replace the existing subagent runtime, mailbox, broker, input-buffer, terminal-result, or `wait_agent` implementation.

## Goal

Use the active Codex Multi-Agent V2 prompt text as the source of truth and make the Azents subagent collaboration prompt match it, leaving only wording required by actual Azents names and tool availability.

The implementation must fit in one focused PR.

## Source of Truth

The frozen reference is OpenAI Codex commit:

```text
1f0566d3f59298d1bb88820a0d35294f1eeb07ea
```

Authoritative prompt sources:

- `codex-rs/core/src/config/mod.rs`
  - `DEFAULT_MULTI_AGENT_V2_ROOT_AGENT_USAGE_HINT_TEXT`
  - `DEFAULT_MULTI_AGENT_V2_SUBAGENT_USAGE_HINT_TEXT`
  - `DEFAULT_MULTI_AGENT_V2_SHARED_USAGE_HINT_TEXT`
  - `default_multi_agent_v2_usage_hint_text`
- `codex-rs/core/src/context/multi_agent_mode_instructions.rs`
  - `EXPLICIT_REQUEST_ONLY_MULTI_AGENT_MODE_TEXT`
- `codex-rs/core/src/session_prefix_tests.rs`
  - root/child prompt selection and ordering coverage

Inactive V1 prompts and fallback spawn guidance are not sources for this change.

## Scope

### In Scope

- Root-specific collaboration usage text.
- Child-specific collaboration usage text.
- Shared direct-tool-call and shared-workspace text.
- Configured concurrency-slot text.
- Explicit-request-only delegation text.
- Selecting root or child text from the current `SessionAgent.kind`.
- Exact prompt regression tests.

### Non-Goals

- Collaboration tool names, parameter names, schemas, descriptions, validation messages, or return values.
- `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `list_agents`, or `interrupt_agent` behavior.
- Mailbox, broker, input-buffer, terminal-result, observation-cursor, run-finalization, or worker changes.
- System-prompt architecture, provider request roles, a new developer-prompt pipeline, or context-inspector UI/API changes.
- Database migrations, public API changes, generated clients, feature flags, compatibility layers, ADRs, or stacked PRs.
- Living-spec changes outside the existing Subagent Toolkit prompt paragraph.

## Current Prompt Drift

| Area | Current Azents prompt | Target |
|---|---|---|
| Agent identity | One generic prompt for every `SessionAgent` | Separate Codex root and child usage hints |
| Root identity | Root is described as a generic team agent | Root is explicitly `/root` and the primary agent |
| Child completion | Parent-delivery wording is included in the generic prompt and therefore also reaches root | Child-only wording states that the terminal result is observed through `wait_agent` |
| Message envelope | No message-envelope explanation | Root and child receive their supported `MESSAGE` / `NEW_TASK` forms; terminal results remain `wait_agent` output |
| Shared workspace | Not stated | State that agents share the same directory and see each other's edits |
| Direct tool calls | Not stated | Explain that collaboration tools are direct tool calls, not `exec_command` subcommands |
| Delegation policy | Capability text can be read as permission to spawn | Append the exact explicit-request-only policy |
| Concurrency | Included inside Azents-specific prose | Use the Codex concurrency sentence after the shared hint |
| Maximum depth | Included in the model-facing prompt | Remove from prompt; runtime enforcement remains unchanged |
| Tool availability | Implies broadly similar tools | Keep the necessary Azents exception for unavailable root/user-facing capabilities |
| Delivery terminology | Uses Azents-specific wake wording | Use Codex `trigger a turn` / `without triggering a turn` wording in prompt text |
| Prompt delivery | One static Toolkit prompt | Keep the existing static Toolkit prompt delivery and change only its selected text |

## Target Prompt Composition

Azents keeps the existing `SubagentToolkit.get_static_prompt()` boundary. It selects one role-specific usage hint and concatenates:

1. root or child usage hint;
2. shared direct-call and workspace hint;
3. configured concurrency sentence;
4. explicit-request-only delegation sentence.

This preserves the current prompt assembly architecture. No new prompt role or transport is introduced.

### Root Usage Hint

````text
You are `/root`, the primary agent in a team of agents collaborating to fulfill the user's goals.

At the start of your turn, you are the active agent.
You can spawn sub-agents to handle subtasks, and those sub-agents can spawn their own sub-agents.
All agents in the team, including the agents that you can assign tasks to, are equally intelligent and capable, and have access to almost the same set of tools, except for Azents root/user-facing capabilities that are not available in subagent mode.

You can use `spawn_agent` to create a new agent, `followup_task` to give an existing agent a new task and trigger a turn, and `send_message` to pass a message to a running agent without triggering a turn.
Child agents can also spawn their own sub-agents.
You can decide how much context you want to propagate to your sub-agents with the `fork_turns` parameter.
Use `wait_agent` to observe unread terminal child results when you need completion output from child agents.

You will receive messages in the model input in the form:
```
Message Type: MESSAGE
Task name: <recipient>
Sender: <author>
Payload:
<payload text>
```
They may be addressed as to=/root
````

### Child Usage Hint

````text
You are an agent in a team of agents collaborating to complete a task.

You can spawn sub-agents to handle subtasks, and those sub-agents can spawn their own sub-agents. All agents in the team, including the agents that you can assign tasks to, are equally intelligent and capable, and have access to almost the same set of tools, except for Azents root/user-facing capabilities that are not available in subagent mode.

You can use `spawn_agent` to create a new agent, `followup_task` to give an existing agent a new task and trigger a turn, and `send_message` to pass a message to a running agent.
Child agents can also spawn their own sub-agents.

When you provide a final response, that content is stored as a terminal child result for your parent to observe with `wait_agent`.

You will receive messages in the model input in the form:
```
Message Type: NEW_TASK | MESSAGE
Task name: <recipient>
Sender: <author>
Payload:
<payload text>
```
You may also see them addressed as to=/root/..., which indicates your identity is /root/...
````

### Shared Usage Hint

```text
Note that collaboration tools cannot be called from inside `exec_command`. Call `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents` only as direct tool calls using the recipient shown in their tool definitions, since they are intentionally absent from `exec_command`.

All agents share the same directory. In detail:
- All agents have access to the same container and filesystem as you.
- All agents use the same current working directory.
- As a result, edits made by one agent are immediately visible to all other agents.
```

### Concurrency Sentence

```text
There are {max_concurrency} available concurrency slots, meaning that up to {max_concurrency} agents can be active at once, including you.
```

### Delegation Policy

```text
Do not spawn sub-agents unless the user or applicable AGENTS.md/skill instructions explicitly ask for sub-agents, delegation, or parallel agent work.
```

## Intentional Azents Wording Differences

| Codex wording | Azents wording | Reason |
|---|---|---|
| `have access to the same set of tools` | `have access to almost the same set of tools, except for Azents root/user-facing capabilities that are not available in subagent mode` | Spawned Azents agents intentionally lack root/user-facing capabilities. |
| `analysis channel` | `model input` | Azents exposes the durable model-input envelope rather than a provider-specific analysis-channel contract. |
| `FINAL_ANSWER` mailbox delivery and `immediately delivered` | `wait_agent` terminal-result observation | Azents keeps its existing terminal-result delivery path; this prompt change does not replace it. |
| `functions.exec`, `functions.collaboration.*`, and `tools.*` namespace wording | `exec_command` and direct collaboration-tool calls | Azents tool names and namespaces differ. |

All other wording in the target blocks remains aligned with the frozen Codex source.

## Implementation Boundary

The implementation changes only the prompt definition, its focused tests, and the corresponding living-spec paragraph:

- `python/apps/azents/src/azents/engine/tools/subagent.py`
- `python/apps/azents/src/azents/engine/tools/subagent_test.py`
- `docs/azents/spec/domain/toolkit.md`

A small adjacent prompt-constant module is acceptable only if it makes exact-string tests clearer; it must not introduce a new prompt delivery pipeline.

## Test Strategy

### Primary Verification

Prompt behavior is deterministic, so focused component tests are the primary verification method. No new testenv fixture, seed data, credentials, or live provider is required.

| Scenario | Assertion |
|---|---|
| Root session | Full prompt equals the root target text, shared hint, concurrency sentence, and delegation policy in order |
| Child session | Full prompt equals the child target text, shared hint, concurrency sentence, and delegation policy in order |
| Root isolation | Root prompt does not contain the child parent-delivery sentence or `NEW_TASK` envelope form |
| Child isolation | Child prompt does not contain root-primary wording |
| Configured concurrency | The existing `max_subagents + 1` value is rendered in the Codex concurrency sentence |
| Runtime preservation | Existing collaboration-tool behavior tests remain unchanged and pass |

### Quality Gates

```console
cd python/apps/azents
uv run ruff format --check src/azents/engine/tools/subagent.py src/azents/engine/tools/subagent_test.py
uv run ruff check src/azents/engine/tools/subagent.py src/azents/engine/tools/subagent_test.py
uv run pyright src/azents/engine/tools/subagent.py src/azents/engine/tools/subagent_test.py
uv run pytest -q src/azents/engine/tools/subagent_test.py

cd ../../..
python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check
git diff --check
```

CI must run the focused tests without optional/live-test skips. Evidence is the exact-string test output and normal CI result.

## Delivery

Implementation is one focused PR containing this design, the prompt change, exact prompt regression tests, and the corresponding living-spec update. There is no stacked rollout or architecture phase.

## Risks

- Future Codex prompt changes can reintroduce drift; the frozen source SHA and full-string tests make that drift explicit.
- Copying Codex delivery or tool-namespace wording verbatim would misdescribe Azents; the four wording adaptations above remain necessary.
- Expanding implementation beyond the two prompt-focused code paths would violate this design and requires separate user approval.
