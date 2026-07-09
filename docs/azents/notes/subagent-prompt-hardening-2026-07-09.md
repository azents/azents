---
title: "Subagent Prompt Hardening Notes"
created: 2026-07-09
tags: [agent, engine, documentation]
---
# Subagent Prompt Hardening Notes

These notes capture the accepted prompt direction before implementation. They are a temporary implementation note; current shipped behavior must still be reflected in living specs when the code changes.

## Baseline

Azents should adopt the Codex v2 multi-agent prompt set as the baseline and only adjust text for Azents implementation differences. Do not add extra guardrails, remove Codex concepts, or invent unsupported runtime concepts in this pass.

Prompt sources to mirror conceptually:

- Root agent usage hint
- Subagent usage hint
- Shared collaboration tool usage hint
- Tool descriptions for `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `list_agents`, and `interrupt_agent`
- Explicit-request-only behavior for delegation

## Accepted Azents-specific deltas

### Tool access wording

Codex says all agents have the same set of tools. Azents subagents do not literally have every root/user-facing capability. Use a softened statement:

```text
All agents are similarly capable and have access to almost the same set of tools, except for Azents root/user-facing capabilities that are not available in subagent mode.
```

The implementation wording can be tightened, but it must preserve the `almost the same set of tools` decision.

### `fork_turns` default

Change `spawn_agent.fork_turns` default from `none` to `all` to match Codex v2.

Tool schema and model-visible descriptions should say that `fork_turns` accepts:

- `none`
- `all`
- a positive integer string such as `1`, `3`, or `10`

and that it defaults to `all`.

### `wait_agent` wording

Codex v2 `wait_agent` is mailbox/activity-oriented and does not return final-answer content as the direct tool result. Azents currently returns unread terminal child results through `wait_agent`.

Azents prompt/tool wording must reflect the current implementation:

```text
Use `wait_agent` to observe unread terminal child results.
```

or equivalent wording that tells the parent agent to call `wait_agent` after spawning/following up when it needs child completion results.

### Final answer delivery wording

Do not use `immediately delivered` in the Azents prompt in this pass.

Codex implementation research found that Codex forwards a child final answer to the direct parent by enqueueing an `InterAgentCommunication` with `trigger_turn = false` during the child terminal turn event. This is immediate as mailbox transport, but it does not automatically trigger a parent turn.

Until Azents matches that Codex parent-mailbox enqueue behavior for child final answers, use wording such as:

```text
When you provide a final response, that content is delivered back to your parent agent as a terminal child result.
```

Backlog: after Azents matches Codex mailbox enqueue semantics for child final answers, reconsider reintroducing Codex-style `immediately delivered` wording.

### Concurrency slots

Codex has prompt text for available concurrency slots. Azents does not support that model-visible concurrency-slot concept yet. Do not include the concurrency slots sentence in this pass.

Backlog: add concurrency-slot prompt text only after Azents implements an equivalent scheduling/concurrency concept.

Next-phase accepted decision: implement Codex-compatible multi-agent concurrency and nesting limits before reintroducing the concurrency-slot prompt text. Match Codex defaults and semantics: `max_concurrent_threads_per_session = 4` counts the parent/root agent, so the default active subagent capacity is `3`; `agent max_depth = 1` permits root-to-child spawning by default. Both values must be configurable through agent settings. When active subagent capacity is exhausted, normal `spawn_agent` should fail with a clear limit error rather than queueing; any job-style retry loop must be a separate scheduler concern.

### Proactive delegation

Do not add proactive delegation behavior in this pass. Current Azents behavior remains explicit-request-only unless a later design changes this.

## Draft prompt shape

Root usage hint should communicate:

```text
You are `/root`, the primary agent in a team of agents collaborating to fulfill the user's goals.

At the start of your turn, you are the active agent.
You can spawn sub-agents to handle subtasks, and those sub-agents can spawn their own sub-agents.
All agents in the team are similarly capable and have access to almost the same set of tools, except for Azents root/user-facing capabilities that are not available in subagent mode.

You can use `spawn_agent` to create a new agent, `followup_task` to give an existing agent a new task and wake it, and `send_message` to pass a message to a running agent without waking it.
Child agents can also spawn their own sub-agents.
You can decide how much context you want to propagate to your sub-agents with the `fork_turns` parameter, which defaults to `all`.
Use `wait_agent` to observe unread terminal child results when you need completion output from child agents.
```

Subagent usage hint should communicate:

```text
You are an agent in a team of agents collaborating to complete a task.

You can spawn sub-agents to handle subtasks, and those sub-agents can spawn their own sub-agents.
All agents in the team are similarly capable and have access to almost the same set of tools, except for Azents root/user-facing capabilities that are not available in subagent mode.

You can use `spawn_agent` to create a new agent, `followup_task` to give an existing agent a new task and wake it, and `send_message` to pass a message to a running agent.
Child agents can also spawn their own sub-agents.

When you provide a final response, that content is delivered back to your parent agent as a terminal child result.
```

Shared usage hint should preserve the Codex idea that collaboration tools must be called directly as tools, not from inside shell commands or `functions.exec`-style subprocesses. Adapt the exact recipient text to Azents' current tool namespace.

## Implementation checklist

- Update `SubagentToolkit.get_static_prompt` or equivalent model-facing static prompt assembly.
- Update tool descriptions/schema descriptions for all six collaboration tools.
- Change `SpawnAgentInput.fork_turns` default to `all`.
- Update tests that assert tool schema defaults or prompt text.
- Keep final-answer `immediately` wording out of the implemented prompt.
- Record the final shipped behavior in living specs after code changes.
