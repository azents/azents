---
title: "ADR-0102: Codex Multi-Agent V2 Model Contract Parity"
created: 2026-07-10
tags: [architecture, agent, engine, prompt]
---
# ADR-0102: Codex Multi-Agent V2 Model Contract Parity

## Context

ADR-0096 adopted a Codex-first SessionAgent actor tree, and ADR-0099 adopted Codex-compatible concurrency, depth, and bounded-sidecar pressure. The implementation copied the team capability and concurrency hints but did not copy the separate default delegation-mode instruction, active V2 `spawn_agent` pressure, root/subagent prompt selection, or shared-workspace warning.

The implementation also retained an Azents-specific model contract in which `wait_agent` targets descendants and returns terminal result content. Codex V2 instead delivers child final answers to the direct parent mailbox and uses `wait_agent` only to synchronize mailbox or steered-input activity.

This produced a model-facing contract that appeared Codex-compatible while applying substantially more proactive delegation pressure and different completion/wait semantics.

## Decision

Azents adopts the active Codex Multi-Agent V2 model contract at OpenAI Codex commit `1f0566d3f59298d1bb88820a0d35294f1eeb07ea` as the source of truth for subagent prompts, collaboration tool schemas/descriptions, direct-parent final-answer delivery, and wait behavior.

Codex wording is copied verbatim by default. A wording change is allowed only when a literal copy would falsely describe an Azents implementation detail. Every allowed terminology delta must be recorded with the exact Codex text, Azents rendering, concrete reason, and parity test in the current design or living spec.

The effective policy for every currently supported Azents reasoning effort is Codex `ExplicitRequestOnly`:

```text
Do not spawn sub-agents unless the user or applicable AGENTS.md/skill instructions explicitly ask for sub-agents, delegation, or parallel agent work.
```

Azents does not map `high` reasoning effort to Codex `Ultra` and does not invent an Azents-specific proactive trigger. If an equivalent Ultra or custom per-turn mode source is added later, its resolution and wording must follow Codex rather than defining a separate policy.

Root and normal spawned child SessionAgents receive separate Codex V2 usage hints plus the shared direct-call, shared-directory, concurrency, and delegation-mode guidance. The role-specific hint and mode are separate developer inputs after base instructions and before conversation input. Active V2 tool schemas and descriptions are adopted, including canonical task paths, `spawn_agent` bounded independent-sidecar pressure, `list_agents.path_prefix`, and timeout-only `wait_agent`.

Each normal child terminal turn queues one idempotent `FINAL_ANSWER` mailbox item for its direct parent without waking an idle parent. It lowers as an assistant-role completion envelope, matching Codex rather than ordinary agent-message input. An active parent consumes it at the next model-call boundary, which also advances the child run's UI unread observation cursor. `wait_agent` synchronizes pending/new mailbox activity or new steered input, returns only Codex summary text, never returns child content, and never mutates the UI cursor. The previous target-specific terminal-result-fetch contract is removed without a compatibility fallback.

Existing AgentRun terminal projections remain available for UI projection and recovery. Existing SessionAgent concurrency, depth, shared workspace, context fork, permissions, and human child-write boundaries are unchanged.

This ADR supersedes only ADR-0096's model-facing terminal-result observation and `wait_agent` details. ADR-0096's actor/session architecture and ADR-0099's concurrency and pressure decisions remain in force.

## Consequences

- Ordinary Azents runs no longer infer delegation permission from complexity, research depth, or requested thoroughness alone.
- Root agents are explicitly identified as primary agents and integrators; child-only delivery wording is no longer shown to roots.
- Prompt drift, including developer/assistant roles and injection order, becomes detectable through exact native-request/source-contract tests.
- Collaboration tool input names and wait behavior change without legacy aliases.
- Child final answers become durable direct-parent mailbox input and can arrive during an active parent run at the next safe model-call boundary.
- Idle parents are not woken solely by child completion.
- UI unread-result projection remains separate from model mailbox synchronization.
- Future Codex prompt updates require an explicit source revision update and delta review rather than partial phrase copying.
