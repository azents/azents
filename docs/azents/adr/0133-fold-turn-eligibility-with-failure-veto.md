---
title: "ADR-0133: Fold Turn Eligibility with Failure Veto"
created: 2026-07-12
tags: [architecture, agent, backend, engine, reliability, session]
---

# ADR-0133: Fold Turn Eligibility with Failure Veto

## Context

Turn continuation depends both on the context in which buffer draining begins and on the ordered outcomes of individual buffer items. A preparation-only success such as a worktree setup must not start a new turn by itself, but it also must not stop an already active run between turns. A handled failure has different semantics: when it is the final effective outcome, no next turn should start.

A single `turn_eligible: bool` cannot distinguish a neutral preparation success from a failure veto because both would otherwise be `false`.

## Decision

Each buffer processor returns an explicit turn effect as part of its structured preparation outcome:

- `eligible` — successful model-producing preparation; sets accumulated turn eligibility to `true`.
- `neutral` — successful preparation-only work; preserves the current accumulated value.
- `failed` — handled final preparation failure; sets accumulated turn eligibility to `false`.

Initialize the accumulator from the actual execution context:

- `true` when an existing `AgentRun` is running and the processor is at a boundary between turns;
- `false` when buffers are being drained after the previous run fully ended and no active AgentRun exists.

Fold each item in durable FIFO order:

```text
eligible -> true
neutral  -> unchanged
failed   -> false
```

After the buffer is empty:

- accumulated `true` starts a new turn or continues the existing active run;
- accumulated `false` starts no turn and returns the session to idle.

A later `eligible` item may recover from an earlier failure. A final failure veto remains effective when no later eligible item replaces it. Neutral preparation after a failure does not re-enable turn execution.

The active-run input is based on an actual running AgentRun at a between-turn boundary, not merely `AgentSession.run_state = running`. Session run state is also used to represent committed pending work before any AgentRun exists and therefore cannot establish continuation eligibility by itself.

This decision retains ADR-0129's final-failure behavior while qualifying the statement that any eligible buffer item is sufficient: an eligible result starts a turn only when no later handled failure veto remains in the FIFO fold.

The terminal status used when a failure veto stops an already active AgentRun is a follow-up lifecycle decision. The buffer-preparation failure event remains distinct from actual model execution provenance.

## Examples

| Initial active run | FIFO effects | Final eligibility | Result |
| --- | --- | --- | --- |
| no | `neutral` | false | preparation only; session idle |
| no | `neutral, eligible` | true | start a new turn |
| yes | `neutral` | true | continue the active run |
| no | `eligible, failed` | false | no turn; session idle |
| no | `failed, eligible` | true | start a new turn |
| yes | `failed` | false | do not continue to another turn |

## Rejected Alternatives

### OR all item booleans

A successful early input would continue to trigger a turn after a later handled failure, violating the final-failure rule.

### Treat every false result as a veto

Preparation-only work would stop an active run even though it completed successfully and has no reason to alter continuation.

### Use Session run state as the initial value

The session is marked running while queued work awaits preparation, including cases where no AgentRun exists. It does not identify a between-turn execution context.

## Consequences

- Preparation outcomes need a three-state turn effect instead of one ambiguous boolean.
- FIFO order affects the final eligibility fold without coupling it to durable event visibility or model lowering.
- Handled failure can suppress both new-turn start and active-run continuation.
- Preparation-only actions remain transparent to an already eligible execution context.
- Tests must cover every initial-context and effect-order combination.

## References

- [ADR-0129: Consume Failed Buffer Items Without Starting a Turn](./0129-consume-failed-buffer-items-without-starting-a-turn.md)
- [ADR-0132: Separate Durable Events, Model Lowering, and Turn Eligibility](./0132-separate-durable-events-model-lowering-and-turn-eligibility.md)
