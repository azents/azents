---
title: "ADR-0131: Keep Action Messages Buffer-Only"
created: 2026-07-12
tags: [architecture, agent, backend, engine, events]
---

# ADR-0131: Keep Action Messages Buffer-Only

## Context

`action_message` is an input-buffer envelope that carries a typed TurnAction, optional user-authored text, and inference overrides into preparation. Earlier designs and the current implementation also promote that envelope into a durable `action_message` transcript event before appending action-specific events.

The sequential preparation model does not need that intermediate durable representation. Once the action has been interpreted, durable history should contain the semantic preparation results and the model-visible user message rather than the queue envelope that transported them.

## Decision

Keep `action_message` as an input-buffer kind only. It is consumed during preparation and is never appended as a durable transcript event.

A successfully prepared model-producing TurnAction decomposes into:

- action-specific durable state and events, such as `skill_loaded` or `goal_updated`; and
- one durable `user_message` containing the user-authored instruction and the resolved inference configuration applied by the action.

The generated events use deterministic external identifiers derived from the source buffer id so retries remain idempotent. The source buffer is deleted in the same atomic preparation result as its semantic events, domain-state changes, and session inference update.

For SkillAction specifically, successful preparation produces `skill_loaded` and `user_message`. The Skill snapshot belongs only to `skill_loaded`; the user-authored instruction belongs only to `user_message`. The action envelope itself is discarded after decomposition.

Handled failures follow ADR-0129 and produce only the durable typed failure representation required for the failed preparation. They do not preserve a durable `action_message` envelope.

This decision supersedes ADR-0086-D9 and ADR-0086-D10 where they require a durable `action_message` event or use that event as the execution identity. It also supersedes the durable action-message event shape described in ADR-0128 and ADR-0130. Those ADRs continue to define GoalAction and SkillAction as model-producing preparation.

## Rejected Alternatives

### Preserve the action envelope as a durable event

This exposes a queue transport representation in transcript history and duplicates information already represented by the action-specific event and generated user message.

### Store the user instruction inside the action-specific event

This couples generic user-message semantics, attachments, and inference configuration to every action-specific event schema. A normal durable `user_message` provides one consistent model-input representation.

## Consequences

- `EventKind.ACTION_MESSAGE` is removed when no other durable producer requires it.
- Pending live projection may still identify the buffer as `action_message`; that is live queue state, not durable history.
- TurnAction processors produce semantic event bundles rather than promoting their buffer envelope.
- SkillAction success produces `skill_loaded` plus `user_message` without duplicated user text.
- GoalAction success produces Goal state/events plus `user_message`; its exact event order is defined in the feature design.
- Operation execution identity must derive from the buffer or generated semantic event instead of a durable action-message event.
- History, frontend rendering, run input association, and action execution projections must stop depending on durable `action_message` events.

## References

- [ADR-0086: Introduce Typed Chat Action Messages](./0086-chat-action-messages.md)
- [ADR-0128: Treat Goal Actions as Model-Producing Preparation](./0128-treat-goal-actions-as-model-producing-preparation.md)
- [ADR-0130: Treat Skill Actions as Model-Producing Preparation](./0130-treat-skill-actions-as-model-producing-preparation.md)
