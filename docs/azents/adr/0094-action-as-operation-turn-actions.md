---
title: "ADR-0094: Model Session Operations as Turn Actions"
created: 2026-07-05
tags: [architecture, backend, frontend, session, workspace, git]
---

# ADR-0094: Model Session Operations as Turn Actions

## Context

ADR-0091 introduced `SessionInitialization` as a one-to-one setup lifecycle for an
`AgentSession`. It solved the first Git worktree use case by gating the first run while setup work
created an Azents-owned Git worktree and registered the created path as a session Project.

That model is too narrow for the next product direction: users must be able to add a Git worktree to
an already-existing session. That flow is not session initialization. It is a user-requested turn that
changes the session Project set before later model turns use the updated workspace context.

The same prerequisite also affects new-session worktree setup. New-session setup should not remain a
separate initialization-only path while existing-session worktree setup uses a different operation
model. The migration target is a clean action-as-operation architecture that covers both:

- new-session setup actions that must run before the first user message reaches the model; and
- existing-session workspace mutation actions that must run in ordered turn context before later
  pending input is processed.

Compatibility with the current `workspace_items`, `workspace_mode`, `project_paths`, and
`SessionInitialization` request model is intentionally out of scope. This is a clean migration.

## Decision

### ADR-0094-D1 — Action messages are operation identity

A user-selected `TurnAction` that performs session setup or workspace mutation is the operation. The
canonical operation request is the durable `action_message` event and its `payload.action` object.

Azents will not introduce a separate `session_operations` request entity whose payload duplicates the
action. Execution state, progress, and logs may be projected from durable action execution events, but
the operation identity and parameters remain the action event.

### ADR-0094-D2 — Add `create_git_worktree` as a TurnAction

Azents will add a `create_git_worktree` TurnAction with the source Project path and starting Git ref
in the action payload.

```json
{
  "type": "create_git_worktree",
  "source_project_path": "/workspace/agent/repo",
  "starting_ref": "main"
}
```

The action means "create an Azents-owned Git worktree and add the created worktree path as a usable
Project for this session." It does not merely mean "run `git worktree add`." Project registration is
part of the action success boundary.

### ADR-0094-D3 — Multiple operations are multiple ordered actions

If setup requires multiple operations, it must be represented as multiple ordered action messages.
Azents will not use an aggregate `configure_workspace` action containing nested operations.

This keeps retry and discard semantics action-local:

- retry retries the failed action only;
- discard finalizes the failed action as failed and allows the queue to continue; and
- partial-failure semantics for an aggregate workspace action are not needed.

Existing Project registration is not modeled as a new TurnAction in this ADR. This migration is scoped
to replacing `SessionInitialization` worktree setup with `create_git_worktree` TurnActions. Existing
Project registration behavior can remain an immediate session Project binding at the relevant write
boundary unless a future design changes it.

### ADR-0094-D4 — New-session setup uses the same action model

New-session worktree setup is represented by ordered action input before the first user message input.
The session runner processes setup actions before the first model run. The first user message remains
pending until preceding setup actions are complete or finalized.

`SessionInitialization` is replaced by this action execution model. The migration does not preserve a
legacy initialization compatibility path.

### ADR-0094-D5 — Action execution progress is durable-event based

Live progress must be recoverable from durable event state, not Redis-only projection. Action
execution emits durable progress events associated with the `action_message` event identity. The live
snapshot is derived from durable action execution state/events.

The exact storage shape is an implementation detail, but it must satisfy these constraints:

- the action event remains append-only and is not patched with mutable status;
- stdout/stderr/progress logs are recoverable after reconnect and worker restart;
- `/live` can project the current action execution state; and
- retry and discard decisions are recorded durably.

### ADR-0094-D6 — Failure stops ordered action execution until user decision

When an operation TurnAction fails, the runner stops at that action. Later pending inputs and actions
remain pending.

The user may choose:

- **Retry** — retry only the failed action; or
- **Discard** — record the failed action as `failed_final` and continue to the next pending input or
  action.

`failed_final` means the operation attempted execution, failed, and the user chose not to retry it.
It remains a failed action in history; it is not rewritten as successful and is not removed.

### ADR-0094-D7 — Project registry mutation is a context invalidation boundary

A successful `create_git_worktree` action changes `session_workspace_projects`. That changes the
system prompt, Project-scoped instructions, RuntimeToolkit Project list, Skill projection, and tool
resolution context for later model turns.

Therefore the runner must not continue into a model turn using a context prepared before Project
registration. After a Project-mutating action completes, the current processing boundary ends. If
pending input remains, the runner enqueues a follow-up wake-up. The next wake-up rebuilds session
context from the updated Project registry and Skill projection before processing later input.

### ADR-0094-D8 — Clean migration, no compatibility layer

This migration replaces the previous initialization-specific API and lifecycle model. New public and
frontend contracts should be expressed in terms of action inputs and durable action execution
projection. Legacy fields and compatibility adapters for `workspace_items`, `workspace_mode`,
`project_paths`, and `SessionInitialization` are not retained as long-term behavior.

## Consequences

- Existing-session Git worktree addition can reuse the same ordered turn-action machinery as
  new-session setup.
- Worktree setup no longer needs a special one-to-one `SessionInitialization` lifecycle.
- The event transcript contains the immutable user action request; execution progress is durable and
  separately projectable.
- Retry/discard semantics are simpler because the operation unit is the action message.
- Project registry mutations create a hard context boundary, requiring a follow-up wake-up before
  later model turns use the changed workspace.
- Public API, generated clients, frontend state, worker logic, specs, and E2E fixtures require a clean
  migration.

## Alternatives

### Keep SessionInitialization and append new worktree steps

Rejected. A one-to-one initialization lifecycle does not model repeated existing-session workspace
operations and makes failure/discard semantics awkward.

### Introduce a separate SessionOperation request entity

Rejected. The action payload is already the user-authored operation request. Duplicating the request
in a separate entity introduces source-of-truth drift.

### Aggregate workspace setup into one configure_workspace action

Rejected. Aggregate actions obscure retry/discard units and force partial-failure semantics. If there
are multiple operations, there should be multiple action messages.

### Continue into model execution after Project mutation in the same prepared context

Rejected. Project registration changes the system prompt and tool context. Continuing with a stale
prepared context could run a later user message without the newly added Project.

### Add compatibility adapters for legacy initialization request fields

Rejected. The migration is intentionally clean to avoid preserving old semantic boundaries that the
new action-as-operation model removes.
