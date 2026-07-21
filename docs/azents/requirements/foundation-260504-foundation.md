---
title: "Agent Runtime and Session Foundation Historical Requirements Reconstruction"
created: 2026-05-04
implemented: 2026-05-04
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: foundation-260504
historical_reconstruction: true
migration_source: "docs/azents/design/agent-session-foundation.md"
---

# Agent Runtime and Session Foundation Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `foundation-260504`
- Source: `docs/azents/design/foundation-260504-foundation.md`
- Historical source date basis: `2026-05-04`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

This document is design document for #3331. Since #3332 ExternalWatch stack created bridge through which Slack/Discord/Scheduler input can enter agent-dedicated execution flow, durable ownership of runtime is now organized around agent.

Initial discussion tried to represent “one active session per agent” as single `agent_sessions` row, but using session itself as long-term runtime identity is unnatural when considering long-term session reset/new/compaction. This design separates long-term runtime identity and conversation segment.

Core principles are as follows.

- Discard `raw session` vocabulary.
- **1 Agent = 1 AgentRuntime**.
- **1 AgentRuntime = multiple AgentSessions**, and exactly one active AgentSession.
- Events belong to AgentSession.
- Worker run state, SDK run state, and sandbox runtime state belong to AgentRuntime.
- Reset/new is active AgentSession rotation, not AgentRuntime deletion or events deletion.
- Sandbox availability is determined not by separate policy enum but by whether Agent has **Sandbox config** attached.
- Do not create sandbox toolkit/provider path for Agent without Sandbox config.
- Existing subagent execution remains compatibility path and preserves parent sandbox sharing.
- task-scoped ephemeral agent spawn is designed separately in follow-up issue #3363.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

1. Existing Agent compatibility
   - Seed existing Agent.
   - Confirm one AgentRuntime and one active AgentSession are created.
   - Confirm Sandbox config is attached to Agent.
   - Confirm shell/file tool is exposed and sandbox is created on-demand on first use.

2. No Sandbox config
   - Create Agent without Sandbox config.
   - Confirm shell/file/recreate tool is not exposed in chat runtime.
   - Confirm internal path attempting to bypass through direct sandbox ensure fails.

3. Agent session rotation
   - Accumulate events in active AgentSession.
   - Perform reset/new.
   - Confirm new AgentSession becomes active and previous events were not deleted.
   - Confirm model context includes only new active AgentSession events.

4. AgentRuntime invariant
   - Send multiple inputs (Web/Slack/Discord/Scheduler) and confirm they enqueue to same AgentRuntime.
   - After reset, confirm same AgentRuntime points to new active AgentSession.

5. Subagent parent sandbox sharing
   - Attach Sandbox config to parent Agent.
   - Parent creates file in sandbox.
   - Invoke subagent tool.
   - Confirm subagent can see same sandbox/file state.

6. Completion review
   - Confirm items in #3364 follow-up tracker are organized at implementation end.

## Supporting Scenarios

1. Existing Agent compatibility
   - Seed existing Agent.
   - Confirm one AgentRuntime and one active AgentSession are created.
   - Confirm Sandbox config is attached to Agent.
   - Confirm shell/file tool is exposed and sandbox is created on-demand on first use.

2. No Sandbox config
   - Create Agent without Sandbox config.
   - Confirm shell/file/recreate tool is not exposed in chat runtime.
   - Confirm internal path attempting to bypass through direct sandbox ensure fails.

3. Agent session rotation
   - Accumulate events in active AgentSession.
   - Perform reset/new.
   - Confirm new AgentSession becomes active and previous events were not deleted.
   - Confirm model context includes only new active AgentSession events.

4. AgentRuntime invariant
   - Send multiple inputs (Web/Slack/Discord/Scheduler) and confirm they enqueue to same AgentRuntime.
   - After reset, confirm same AgentRuntime points to new active AgentSession.

5. Subagent parent sandbox sharing
   - Attach Sandbox config to parent Agent.
   - Parent creates file in sandbox.
   - Invoke subagent tool.
   - Confirm subagent can see same sandbox/file state.

6. Completion review
   - Confirm items in #3364 follow-up tracker are organized at implementation end.

## Goals

**Decision:** #3331 keeps existing subagent execution path.

Important current subagent use is parent sandbox sharing. This constraint is preserved.

- Existing subagent invocation does not create separate sandbox.
- If parent Agent has Sandbox config, subagent shares parent sandbox context.
- If parent Agent does not have Sandbox config, subagent also has no sandbox toolkit/provider path.
- In final spawned subagent model, default is also parent sandbox sharing.

Final goal is task-scoped ephemeral agent spawn. Each subagent call creates ephemeral Agent, and that Agent has exactly one AgentRuntime and active AgentSession. This larger work is handled in #3363.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
