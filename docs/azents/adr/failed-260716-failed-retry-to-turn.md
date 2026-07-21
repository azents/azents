---
title: "Scope Failed-run Retry to One Model Turn"
created: 2026-07-16
tags: [architecture, backend, engine, worker, retry, recovery, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: failed-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0145-scope-failed-run-retry-to-model-turn.md"
---
# failed-260716/ADR: Scope Failed-run Retry to One Model Turn

## Context

[failed-260627/ADR](./failed-260627-failed-error-retry.md) established durable failed-run retry state on `agent_runs` and required worker handover to preserve retry count and backoff. Its recovery language treated a running `AgentRun` as the effective retry scope.

One `AgentRun` can contain multiple model turns. The implementation consequently retained failed-attempt count, history, and backoff after a model turn recovered. A failure in a later turn continued the older turn's budget. Durable retry state also survived successful output, so REST live-state resync could restore an obsolete error card under a later inference profile.

The intended product policy is that automatic retry protects one model turn. A later model turn receives a fresh budget, while worker handover during the current turn must still preserve retry progress.

## Decision

### Retry budget is scoped to one model turn

Failed-attempt count, attempt history, and exponential backoff belong to the model turn that encountered the failure. Repeated attempts before that turn produces committed model output share one retry cycle. The next model turn starts with failed attempt 1 and an empty attempt history if it fails.

### Successful output admission ends the retry cycle atomically

`agent_runs.retry_state` remains durable during retry backoff and during an in-flight retry attempt so shutdown and ownership takeover cannot reset the budget or bypass backoff.

The transaction that admits successful normalized model output also clears `agent_runs.retry_state`. This creates one durable recovery boundary:

- before commit, retry state identifies an active retry for the unfinished model turn;
- after commit, output in the transcript and null retry state identify a completed retry cycle.

The clear does not depend on provider usage or a `turn_marker`, because successful output can exist without reported usage.

### Live retry state follows the durable current-turn lifecycle

REST and WebSocket `run.retry` projections represent the current model turn's active retry cycle. The retry card may remain visible during backoff and the in-flight retry model call. It is removed after successful output admission or terminal finalization, not merely because `next_retry_at` elapsed.

An expired `next_retry_at` is valid while the retry attempt is in flight and therefore is not, by itself, a stale-state filter.

### [failed-260627/ADR](./failed-260627-failed-error-retry.md) recovery scope is superseded narrowly

[failed-260627/ADR](./failed-260627-failed-error-retry.md) remains authoritative for shared failed-run finalization, structured attempts, durable retry storage, bounded retry policy, stop behavior, terminal metadata, and successful-run-only Goal continuation.

This ADR supersedes [failed-260627/ADR](./failed-260627-failed-error-retry.md) only where its language implies that retry budget spans an entire running `AgentRun`. Recovery preserves the active current-turn retry cycle, not retry history from earlier completed turns in the same run.

## Consequences

### Positive

- Later model turns receive a fresh retry budget.
- Worker takeover remains safe during both backoff and in-flight retry.
- Successful output and retry-state removal cannot be separated by a crash window.
- REST resync cannot resurrect a retry card from an earlier successfully completed turn.
- Retry UI cannot visually attach an old provider failure to a later Session inference profile.

### Negative / trade-offs

- The event execution core participates in retry lifecycle by clearing the durable state in the model-output transaction, while the worker remains the owner of failure classification, waiting, and terminal finalization.
- Unexpected failures after a successful model-output commit begin a fresh failed-run retry cycle even if they happen during tool execution for that output. This is intentional because the model call's retry cycle has completed.

## Alternatives

### Clear retry state when backoff expires

Rejected. A crash during the following model request would lose the durable count and let takeover restart the budget.

### Add an explicit persistent turn identifier to retry state

Rejected for the current correction. It expands the persistent contract and migration surface without improving the atomic output-commit boundary.

### Hide expired retry state only in live APIs

Rejected. It addresses presentation only and leaves retry counting and takeover incorrect. Expired timestamps are also expected during an active retry request.

## Related documents

- [failed-260627/ADR: Failed-run Error Retry and Finalization](./failed-260627-failed-error-retry.md)
- [Turn-scoped Failed-run Retry](../design/turn-scoped-failed-run-retry.md)
- [Agent Execution Loop](../spec/flow/agent-execution-loop.md)
- [Run Resume](../spec/flow/run-resume.md)
- [Chat Session Resync](../spec/flow/chat-session-resync.md)

## Migration provenance

- Historical source filename: `0145-scope-failed-run-retry-to-model-turn.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
