---
title: "ADR-0119: Precreate the Inherited First Subagent Run"
created: 2026-07-10
tags: [architecture, backend, engine, subagent]
---

# ADR-0119: Precreate the Inherited First Subagent Run

## Context

ADR-0108 requires a newly spawned subagent's first run to inherit the parent AgentRun's exact requested target, resolved model snapshot, and effective reasoning effort without re-routing. The inheritance must be durable before child wake-up. Storing a physical snapshot on InputBuffer would violate its requested-intent boundary, while using temporary AgentSession fields would duplicate AgentRun provenance and require separate consume/clear recovery logic.

ADR-0117 establishes AgentRun as the durable owner of requested and resolved execution provenance. The child first run is already known when `spawn_agent` executes inside the parent run.

## Decision

Create the child subagent's first AgentRun in the same database transaction that creates the child AgentSession, SessionAgent node, and spawn-task InputBuffer. Introduce a durable `pending` AgentRun state meaning created but not yet worker-activated. Pending does not necessarily mean unresolved: ordinary pending runs initially have requested-only provenance, while this inherited pending run already carries the parent resolved snapshot.

The pending child run stores:

- `parent_agent_run_id` referencing the spawning parent run;
- requested target label and effort copied from the parent run;
- `inference_profile_source = parent_run`;
- the parent's immutable resolved model-selection snapshot;
- effective resolved reasoning effort;
- effective context-window and compaction-threshold values.

Initialize the child AgentSession last-used target and effort from the same inherited requested profile in that transaction. Enqueue the child task, commit all state, and only then publish the broker wake-up.

On wake-up, the worker atomically claims the session's pending AgentRun, transitions it to running, and builds the RunRequest from its stored resolved provenance. It does not allocate a different run ID and does not invoke target routing for this first inherited run.

Only one claimable pending run may exist for a session. Duplicate wake-ups cannot claim the same run twice. After the inherited first run becomes terminal, later child runs follow normal session profile and run-time resolution policy.

## Rejected options

### Store the inherited snapshot temporarily on AgentSession

This duplicates AgentRun provenance, pollutes session state with one-time physical model data, and requires crash-safe clear/create coordination.

### Store the inherited snapshot on the spawn InputBuffer

InputBuffer is defined as requested intent rather than resolved physical execution data and is deleted after promotion.

### Create the child AgentRun only after wake-up

A crash between child creation and worker resolution could lose inheritance or replace it with Agent defaults.

### Re-resolve the parent target for the child

Routing can choose another physical model and violate parent-run context inheritance.

## Consequences

- AgentRun status gains a pending state and lifecycle timestamps distinguish creation from worker start.
- AgentRun gains nullable parent-run lineage.
- Spawn creation and initial task enqueue must be one transaction; broker wake-up remains post-commit.
- Worker scheduling claims precreated runs before allocating ordinary new runs.
- Pending runs require recovery/re-wake support when commit succeeds but initial publication fails.
- Resolved subagent inheritance has one durable source of truth and no intermediate snapshot payload.
