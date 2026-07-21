---
title: "Consume Failed Buffer Items Without Starting a Turn"
created: 2026-07-12
tags: [architecture, agent, backend, engine, reliability, session, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: consume-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0129-consume-failed-buffer-items-without-starting-a-turn.md"
---

# consume-260712/ADR: Consume Failed Buffer Items Without Starting a Turn

## Context

[drain-260712/ADR](./drain-260712-drain-input-buffers-before-turn-start.md) drains input buffers sequentially before deciding whether to start the next turn. Individual preparation items can fail for expected reasons, such as an invalid Goal transition or an inference-profile resolution failure. Leaving such an item pending would block all later FIFO work, while starting a model turn for a failed item would spend a model call even though no valid model-producing preparation was completed.

The same rule must apply consistently across buffer kinds so each type does not invent its own queue-blocking or turn-start behavior.

## Decision

Use a consumed, non-turn-producing failure as the baseline for expected input-buffer preparation failures.

When one buffer item reaches a handled preparation failure:

1. Append an immutable durable failure event linked to the failed buffer item and its user-visible intent.
2. Do not commit the failed item's intended domain side effects.
3. Do not update the AgentSession inference configuration from a failed model or effort resolution.
4. Delete the failed input-buffer row in the same atomic failure-result transaction.
5. Continue draining the next FIFO buffer item.

A handled failure resets immediate turn eligibility. A later successfully prepared model-producing item may establish turn eligibility again. If the final processed buffer item fails, the session returns to `idle` after the buffer becomes empty and no turn or AgentRun starts, even when an earlier item in the same drain cycle had prepared actionable input. That earlier durable input remains available to a future turn after later successful preparation wakes the session.

This rule applies to GoalAction validation/state failures and to `user_message` model or effort resolution failures. It is the default for other message kinds unless a later decision explicitly defines different semantics.

This failure-consumption rule applies only when the processor can classify and atomically persist an expected final failure. An unexpected database, process, or infrastructure exception rolls back the preparation transaction and leaves the buffer pending for retry or recovery; it must not be disguised as a successfully consumed domain failure.

## Rejected Alternatives

### Start a turn for the failed item

A model call is unnecessary when the only prepared result is a deterministic validation or resolution failure. The durable failure event already communicates the result.

### Leave the failed item pending

A deterministic failure would permanently block later FIFO work until manual deletion or implementation-specific retry handling intervened.

### Preserve turn eligibility from any earlier successful item

This would start a turn even though the final accepted instruction failed to prepare. The user-visible boundary would then look like the failed last message caused execution, which is the same undesirable behavior as starting a turn for a single failed message.

### Consume unexpected infrastructure failures as final failures

This converts transient or unknown faults into accepted data loss. Transactional rollback and recovery are required instead.

## Consequences

- Expected preparation failures are durable, visible, and non-blocking.
- Failed model resolution does not replace the last valid session inference configuration.
- Buffer drain maintains an explicit turn-eligibility outcome rather than using `any(success)` aggregation.
- The final processed item can suppress turn start after earlier successful preparation.
- SessionRunner must return the session to idle when drain finishes without turn eligibility.
- Failure events require stable buffer linkage and typed user-safe failure details.
- Unexpected technical failures retain the buffer and follow retry/recovery behavior.

## References

- [drain-260712/ADR: Drain Input Buffers Sequentially Before Turn Start](./drain-260712-drain-input-buffers-before-turn-start.md)
- [message-260712/ADR: Resolve User Message Profiles During Buffer Preparation](./message-260712-message-profile-during-buffer-preparation.md)
- [goal-260712/ADR: Treat Goal Actions as Model-Producing Preparation](./goal-260712-goal-actions-as-producing-preparation.md)

## Migration provenance

- Historical source filename: `0129-consume-failed-buffer-items-without-starting-a-turn.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
