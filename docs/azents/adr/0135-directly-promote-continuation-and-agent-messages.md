---
title: "ADR-0135: Directly Promote Continuation and Agent Messages"
created: 2026-07-12
tags: [architecture, agent, backend, engine, goal, subagent]
---

# ADR-0135: Directly Promote Continuation and Agent Messages

## Context

`goal_continuation` and `agent_message` input buffers already represent complete semantic messages. Unlike TurnAction envelopes, they require no decomposition into action-specific state plus a generated user message. Neither carries a human inference-profile override that changes session configuration.

## Decision

Process `goal_continuation` and `agent_message` as direct one-to-one durable event appends.

For successful preparation of either kind:

1. Validate and construct the typed event payload.
2. Append one durable event with the same semantic kind and a deterministic external id derived from the buffer.
3. Preserve the AgentSession's current resolved inference configuration without modification.
4. Delete the source input-buffer row in the same atomic preparation result.
5. Return the `eligible` turn effect.

The event lowerer remains responsible for model-facing representation:

- `goal_continuation` lowers to the Goal continuation reminder;
- `agent_message` lowers to the typed inter-agent message representation.

Wake policy remains owned by each producer. Goal continuation and wake-producing mailbox operations schedule session processing. A mailbox `send_message` operation may queue an `agent_message` without waking an idle target; when that message is later drained, it is still model-facing and turn-eligible.

Handled payload or semantic failures use the shared `failed` effect under ADR-0129. Unexpected infrastructure failures roll back and retain the buffer.

## Rejected Alternative

### Add message-specific preparation state machines

These messages already contain the semantic payload required by history and model lowering. Additional decomposition or session configuration mutation would duplicate state without adding behavior.

## Consequences

- Both remaining internal message kinds use the simplest buffer processor shape.
- Their successful processing does not alter model or effort selection.
- Producer-specific wake behavior remains separate from event promotion and turn eligibility.
- Typed lowerers continue to control model visibility independently of durable storage.

## References

- [ADR-0062: Goal Continuation Uses Idle Hook and Input Buffer](./0062-goal-continuation-idle-hook.md)
- [ADR-0096: Redesign Subagents Around the Codex Model](./0096-codex-first-subagent-redesign.md)
- [ADR-0129: Consume Failed Buffer Items Without Starting a Turn](./0129-consume-failed-buffer-items-without-starting-a-turn.md)
- [ADR-0132: Separate Durable Events, Model Lowering, and Turn Eligibility](./0132-separate-durable-events-model-lowering-and-turn-eligibility.md)
- [ADR-0133: Fold Turn Eligibility with Failure Veto](./0133-fold-turn-eligibility-with-failure-veto.md)
