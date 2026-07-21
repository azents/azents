---
title: "Subagents Inherit the Parent Run Profile"
created: 2026-07-10
tags: [architecture, agent, backend, engine, subagent, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: subagent-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0108-subagent-parent-run-profile-inheritance.md"
---

# subagent-260710/ADR: Subagents Inherit the Parent Run Profile

## Context

Subagents execute through internal subagent AgentSessions and the same worker/AgentRun path as the root session. A newly spawned subagent has no prior session inference profile. Applying the Agent default or re-resolving only the parent's target could make the child start with a different physical model than the parent run that delegated the task.

Subagents are children of a concrete running parent `AgentRun`, so their initial execution profile should be part of the forked execution context. Future explicit subagent model overrides are planned but are outside the scope of the per-prompt model-selection feature.

## Decision

A newly spawned subagent inherits the complete effective inference profile of the parent `AgentRun` that executes `spawn_agent`:

- requested model target label;
- already resolved `AgentModelSelection` snapshot;
- effective reasoning effort.

The child subagent's first `AgentRun` uses the inherited resolved model snapshot and effort directly. It does not re-run target routing for that initial inherited profile. This is a parent-run context inheritance boundary, not an implicit no-profile run under [time-260710/ADR](./time-260710-time-target-resolution.md).

The inherited profile must be durable before the child wake-up is published so worker handoff or restart cannot replace it with Agent defaults. The child AgentSession's last-used target and effort are initialized from the inherited profile for later implicit child runs under [used-260710/ADR](./used-260710-used-inference-profile.md).

Adding an explicit target or effort override to `spawn_agent` is a separate future feature and is not part of this design.

## Rejected options

### Resolve the parent's target again for the child

Dynamic routing could select a different physical model, violating the expectation that a spawned child follows the concrete parent run's model settings.

### Use the Agent default profile

This breaks parent context inheritance whenever the user selected a different profile for the parent prompt.

### Add subagent override controls now

The target abstraction supports a future override, but expanding the collaboration tool contract is outside this feature's scope.

## Consequences

- `spawn_agent` needs access to the parent AgentRun's requested and resolved inference provenance.
- Child creation must persist a one-time resolved-profile inheritance payload before wake-up.
- The first child run bypasses target re-resolution only for this inherited parent profile; normal later run boundaries continue to follow session/profile policy.
- Subagent audit data can identify both the inherited target intent and the exact parent-resolved model.
- Parent and first child runs use the same physical model and reasoning effort even if routing policy changes between their start times.

## Migration provenance

- Historical source filename: `0108-subagent-parent-run-profile-inheritance.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
