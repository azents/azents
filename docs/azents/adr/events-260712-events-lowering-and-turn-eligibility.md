---
title: "Separate Durable Events, Model Lowering, and Turn Eligibility"
created: 2026-07-12
tags: [architecture, agent, backend, engine, events, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: events-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0132-separate-durable-events-model-lowering-and-turn-eligibility.md"
---

# events-260712/ADR: Separate Durable Events, Model Lowering, and Turn Eligibility

## Context

Input-buffer preparation can produce durable events for UI, audit, recovery, or model context. Event persistence does not by itself imply that the event is model-facing: the event lowerer explicitly drops UI-only event kinds. Likewise, producing a durable or model-facing event does not by itself define whether the buffer-drain cycle should start a turn.

Conflating these concerns makes action-specific UI events accidentally control model input or run creation.

## Decision

Treat the following as independent outputs of input-buffer preparation:

1. **Durable state and events** — persisted facts used by UI, audit, recovery, and later projections.
2. **Model lowering** — the event lowerer independently decides which durable events become model input and how they are represented.
3. **Turn eligibility** — the preparation result explicitly decides whether the drain cycle is eligible to start a turn after the buffer becomes empty.

A durable UI-only event remains in the Event Store while the lowerer drops it from model input. A model-facing event is durable only when its domain requires durable history; model visibility must not be inferred from the fact that an event was appended.

SessionRunner must not infer turn eligibility from the existence or kind of appended events. Each buffer processor returns an explicit structured preparation outcome, including success or handled failure and its turn-eligibility effect. [consume-260712/ADR](./consume-260712-consume-failed-buffer-items-without-starting-a-turn.md) still applies: a handled failure clears immediate turn eligibility, and a final failed item leaves the session idle without starting a turn.

The terms "model-producing action" in [goal-260712/ADR](./goal-260712-goal-actions-as-producing-preparation.md) and [skill-260712/ADR](./skill-260712-skill-actions-as-producing-preparation.md) mean that a successful GoalAction or SkillAction establishes turn eligibility. They do not mean that every durable event produced by those actions is model-facing. Their `goal_updated`, `skill_loaded`, `user_message`, failure, and UI projection events remain subject to explicit lowerer rules.

## Rejected Alternatives

### Treat every durable event as model-facing

UI, progress, audit, and recovery events would pollute model context and require event storage choices to follow prompt-format concerns.

### Infer turn eligibility from model-facing event presence

This hides control flow inside the lowerer and cannot express preparation-only actions, final handled failures, or explicit context refresh requirements cleanly.

### Avoid durable UI-only events

Operational and action progress state still needs durable recovery and history even when it is irrelevant to model context.

## Consequences

- Buffer processors need a structured outcome separate from their event append results.
- Event lowerers remain the sole authority for model-facing projection.
- UI-only durable events can be added without causing model calls or model-context changes.
- Turn start logic uses explicit preparation outcome state after the queue is empty.
- Message-kind review must specify durable outputs, model-lowering behavior, and turn-eligibility behavior separately.

## References

- [drain-260712/ADR: Drain Input Buffers Sequentially Before Turn Start](./drain-260712-drain-input-buffers-before-turn-start.md)
- [goal-260712/ADR: Treat Goal Actions as Model-Producing Preparation](./goal-260712-goal-actions-as-producing-preparation.md)
- [consume-260712/ADR: Consume Failed Buffer Items Without Starting a Turn](./consume-260712-consume-failed-buffer-items-without-starting-a-turn.md)
- [skill-260712/ADR: Treat Skill Actions as Model-Producing Preparation](./skill-260712-skill-actions-as-producing-preparation.md)

## Migration provenance

- Historical source filename: `0132-separate-durable-events-model-lowering-and-turn-eligibility.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
