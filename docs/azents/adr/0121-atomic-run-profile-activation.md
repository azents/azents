---
title: "ADR-0121: Atomically Activate the Resolved Run and Session Profile"
created: 2026-07-10
tags: [architecture, backend, database, engine, session]
---

# ADR-0121: Atomically Activate the Resolved Run and Session Profile

## Context

AgentSession last-used target and effort drive later implicit execution and Composer initialization. Updating them when input is enqueued would let unresolved or invalid intent replace the last successful profile. Waiting until run completion would leave session state stale after the model has already begun executing and make long runs inconsistent with later implicit work.

AgentRun resolved provenance, effective context limits, and running state must describe the same activation point. Starting the provider call before those writes commit could produce model output without durable execution provenance.

## Decision

`Pending` means that a run has not yet committed its worker activation checkpoint, not necessarily that it lacks resolved provenance. Ordinary pending runs resolve first; a `parent_run` inherited pending run already has a stored resolved snapshot and skips routing.

After ordinary target resolution succeeds, or after an inherited run's stored profile is verified, activate the run and session profile in one database transaction before any model call:

- persist the AgentRun resolved model-selection snapshot;
- persist effective reasoning effort and context/compaction limits;
- set the resolution timestamp;
- transition the AgentRun from pending to running;
- update AgentSession `last_model_target_label` and `last_reasoning_effort` from the run's requested target intent.

Commit this checkpoint before invoking the model provider. If the transaction fails, do not start the model call; run preparation remains retryable.

A null last reasoning effort with a non-null last target represents the visible `Default` no-override effort. The session stores the requested Agent-owned label, not the physical resolved model.

If target resolution fails, atomically mark the pending AgentRun failed with its typed failure data and end timestamp while leaving AgentSession last-used fields unchanged.

Apply the same checkpoint semantics to explicit input, edited input, manual retry, implicit session execution, and Agent-default initialization. Automatic retry stays within the already activated AgentRun and does not update session profile again.

The first subagent run is precreated with inherited resolved provenance under ADR-0119, and its child session is initialized from the parent profile in the spawn transaction. Worker claim verifies and preserves those values while transitioning the pending child run to running; it does not route again.

## Rejected options

### Update session profile on enqueue

A target that later fails resolution would displace the last known usable profile.

### Update session profile after run completion

The session would report an older profile throughout model and tool execution, and interrupted or failed provider calls would erase the fact that the resolved profile was actually activated.

### Persist provenance after starting the provider call

A crash could leave externally executed model work without durable resolved provenance.

### Split run activation and session update across transactions

Observers and implicit execution could see a running resolved run paired with stale session profile state.

## Consequences

- Ordinary model-producing AgentRuns use pending as the pre-resolution state and running only after durable resolved activation.
- Session last-used semantics mean the latest successfully resolved and activated profile, not the latest completed response.
- Provider invocation is ordered after the run-start database commit.
- Resolution failure never mutates the prior session profile.
- Repository/service operations need an atomic run-activation method that locks the relevant pending AgentRun and AgentSession rows.
