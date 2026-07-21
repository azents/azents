---
title: "Session Operation Turn Action Migration Design"
created: 2026-07-05
updated: 2026-07-05
implemented: 2026-07-05
tags: [backend, frontend, api, session, workspace, git]
document_role: supporting
document_type: supporting-consolidation
migration_source: "docs/azents/design/session-operation-turn-action-migration.md"
supporting_role: consolidation
---

# Session Operation Turn Action Migration Design

## Overview

This design migrates Azents session setup work from the current `SessionInitialization` lifecycle to
an action-as-operation TurnAction architecture. The prerequisite goal is to prepare the product for a
follow-up feature: adding an Azents-owned Git worktree to an already-existing session. That follow-up
feature is not implemented by this design; this design changes the session operation substrate so the
follow-up can be built without a second operation model.

The migration covers both:

- new-session Git worktree setup that currently uses `SessionInitialization`; and
- future existing-session Git worktree addition through the same `create_git_worktree` TurnAction.

The design follows [action-260705/ADR](../adr/action-260705-action-as-operation-turn-actions.md). The `action_message` event is the operation identity. Its action payload
is the source of truth for operation parameters. Execution progress is durable-event based and is
projected into live state. Project registry mutation is a context invalidation boundary so later model
turns rebuild system prompt and tool context from the updated Project set.

This is a clean migration. No compatibility layer is kept for legacy initialization request fields or
old initialization projections.

## Problem

`SessionInitialization` is one-to-one with an `AgentSession` and is named around startup setup. It
worked for new-session worktree creation because the setup work always happened before the first run.
It does not fit the next workflow: a user should be able to add a new Git worktree Project to a
session that already exists and may already have transcript, tools, Skills, and Project context.

If the existing initialization lifecycle is extended by appending more setup steps, several problems
appear:

- repeated session operations become hidden inside a single initialization object;
- retry and discard units are unclear when multiple operations exist;
- initialization failure can block an otherwise usable existing session without clear action-level
  recovery;
- new-session and existing-session worktree flows would diverge; and
- a Project registered during an operation can be missed by a later model turn if the prepared system
  prompt and tool context are not rebuilt.

The migration must preserve the user-facing ordering guarantees of TurnActions while making action
execution recoverable and resumable.

## Goals

- Replace `SessionInitialization` as the session setup operation model.
- Add `create_git_worktree` as a TurnAction whose action message is the operation identity.
- Represent multiple setup operations as multiple ordered action messages.
- Use the action payload as the operation parameter source of truth.
- Store action execution progress in durable event state that can rebuild live projections.
- Keep retry and discard scoped to the failed action.
- Treat Project registry mutation as a context invalidation boundary.
- Migrate new-session worktree setup to the same action execution path.
- Prepare the substrate for later existing-session worktree addition without implementing that
  follow-up feature in this design.
- Perform a clean migration with no long-term legacy compatibility layer.

## Non-Goals

- Do not implement the existing-session "add Git worktree" UI or end-to-end product flow yet.
- Do not add a `register_project` TurnAction in this design.
- Do not introduce a separate `SessionOperation` request entity that duplicates action payloads.
- Do not preserve `workspace_items`, `workspace_mode`, `project_paths`, or `/initialization` as
  long-term compatibility contracts.
- Do not make action progress Redis-only or non-recoverable.
- Do not allow a model turn to continue with stale Project context after a Project-mutating action.

## Current Behavior

New-session worktree setup currently works through `SessionInitialization`:

1. The session create request contains workspace setup fields.
2. Backend creates one `session_initializations` row for the session.
3. Backend creates ordered initialization steps for worktree creation, Project registration, catalog
   upsert, and status refresh.
4. `SessionRunner` checks the initialization gate before run dispatch.
5. Pending setup runs before input buffers are promoted to model input.
6. Live state exposes initialization projection and durable initialization event detail.

Existing-session Project registration currently registers already-existing directories only. It does
not create a Git worktree.

## Proposed Design

### Action model

Add `CreateGitWorktreeAction` to TurnAction payloads:

```ts
type CreateGitWorktreeAction = {
  type: "create_git_worktree";
  source_project_path: string;
  starting_ref: string;
};
```

The durable `action_message` event carrying this payload is the operation identity. The payload is the
canonical request. Execution state must reference this action event rather than store a second request
payload.

The action succeeds only when the created worktree path is usable as a session Project. At minimum the
successful boundary includes:

1. validating access and source path policy;
2. creating the Git worktree through typed Runner operations;
3. registering the created path in `session_workspace_projects`;
4. updating the Agent Project catalog; and
5. refreshing Skill projection so later composer actions and model context can see new Project Skills.

Catalog status refresh can be recorded as a non-blocking warning when the session Project itself has
already been registered successfully.

### New-session setup as ordered action input

New-session worktree setup becomes ordered setup action input before the first user message input.
When a draft new session contains a worktree item, the create request produces a
`create_git_worktree` action input followed by the first user message input. If multiple worktree
operations are needed, each is a separate action in order.

Existing Project paths selected for new-session setup remain direct Project bindings at session
creation time for this migration. They are not modeled as `register_project` TurnActions.

### Action execution state and durable progress

Action execution progress is durable-event based. The implementation may use purpose-built tables or
structured durable event kinds, but it must preserve these logical records:

- action execution started;
- step started;
- command/progress/stdout/stderr output;
- step completed;
- warning;
- failure;
- retry requested;
- failed finalized by discard; and
- completed.

The mutable `action_message` event payload is not patched with execution state. Live state derives the
latest action execution projection from durable state so reconnect and worker restart can recover the
current operation card.

### Ordered execution and recovery

TurnAction ordering remains the ordering authority. The runner processes input buffers in FIFO order.
When it reaches a `create_git_worktree` action:

1. it appends the durable `action_message` event;
2. it starts action execution associated with that event;
3. it runs the worktree setup steps;
4. it records durable progress events; and
5. it either completes the action, fails it, or records a user-driven final failure.

On failure, later pending input and actions remain pending. The user chooses:

- **Retry** — re-run only the failed action; or
- **Discard** — record `failed_final` for the failed action and allow the ordered queue to continue.

`failed_final` means the action failed and the user accepted that failure as final. It does not mark
the action successful and does not remove it from history.

### Context invalidation boundary

`create_git_worktree` registers a new Project on success. This changes prompt and tool context. The
runner must not continue into a later model turn using a context prepared before the Project registry
changed.

After a Project-mutating action completes successfully:

1. finish the action execution;
2. refresh catalog and Skill projection as required;
3. record action completion;
4. enqueue a follow-up wake-up if pending input remains; and
5. stop the current processing boundary.

The follow-up wake-up rebuilds the session context from current database state, including the updated
Project list and Skill projection, before processing later pending input or starting a model run.

### Cleanup and partial side effects

`session_git_worktrees` remains the ownership and cleanup authority for Azents-created worktrees. The
migration replaces initialization linkage with action-event linkage. Cleanup must still require an
explicit ownership row and must never infer deletion authority from Project rows or path prefixes
alone.

If a worktree is created but later action steps fail, retry should resume from safe step state where
possible. If the user discards the failed action, any Azents-owned unregistered worktree side effect
must remain cleanup-addressable through the ownership row. Cleanup failure must not rewrite the action
as successful.

## API and Data Model Changes

### Public API

- Add `create_git_worktree` to the generated public `ChatAction` / `TurnAction` schema.
- Replace new-session worktree setup request fields with action-based setup input.
- Replace initialization retry/detail endpoints with action-execution retry/detail projections keyed
  by the action identity selected by the API design.
- Remove legacy workspace setup request fields as part of the clean migration.

### Database and repository model

- Remove or replace `session_initializations`, `session_initialization_steps`, and
  `session_initialization_events` as the authoritative setup model.
- Introduce durable action execution state/events or equivalent durable event records associated with
  `action_message` event IDs.
- Replace `session_git_worktrees.initialization_id` / `step_id` linkage with action-execution linkage
  while preserving source path, starting ref, worktree path, branch name, status, ownership, failure,
  and cleanup metadata.
- Keep `session_workspace_projects` as the session Project registry and prompt scope source of truth.

### Frontend model

- New-session draft UI may continue to show a workspace item selector, but worktree items are sent as
  ordered `create_git_worktree` setup actions.
- Existing-session worktree addition in the follow-up feature should submit the same TurnAction rather
  than call a separate worktree operation API.
- Timeline/live UI renders action execution cards from durable action execution projection.
- Retry and Discard controls target the failed action execution.

## Runtime and Lifecycle Behavior

- Runner Git operations remain typed Runner operations.
- Backend owns action execution lifecycle, retry/discard policy, Project registration, catalog update,
  Skill projection refresh, live projection, and cleanup coordination.
- Runner owns filesystem/Git execution and streams output into durable action execution events.
- A successful Project-mutating action always creates a fresh-context boundary before later model
  turns.
- A failed action blocks later pending input until user retry/discard decision.

## Error Handling

- Validation errors before action execution should be recorded as failed action execution state where
  the action message has already become the operation identity.
- Runtime unavailable, Git command failure, branch/ref errors, Project registration failure, and Skill
  refresh failure are recorded with user-safe failure or warning details.
- Retry reuses the same action payload from the durable action message.
- Discard records `failed_final` and allows later pending input to proceed.
- Cleanup-required side effects remain tied to `session_git_worktrees` ownership metadata.

## Security and Permissions

- Access checks remain session-scoped and workspace-membership based.
- Source paths must still be normalized under `/workspace/agent` and must not allow path traversal.
- Worktree cleanup authority remains explicit ownership metadata, not path prefix or Project row
  membership.
- The action payload may contain workspace paths and branch names; it is durable transcript-adjacent
  data and should be exposed only through session-authorized APIs.

## Migration and Rollout

This is a clean migration:

- remove old initialization request/projection contracts instead of retaining compatibility adapters;
- regenerate OpenAPI clients after schema changes;
- migrate or replace existing initialization tests with action execution tests;
- update specs after implementation to reflect current behavior; and
- supersede [initialization-260703/ADR](../adr/initialization-260703-initialization-lifecycle.md) initialization lifecycle behavior with [action-260705/ADR](../adr/action-260705-action-as-operation-turn-actions.md) where they conflict.

Because the follow-up existing-session worktree addition depends on this substrate, this migration
should ship first as its own feature stack.

## Alternatives Considered

### Keep SessionInitialization and append operations

Rejected because one session-level initialization object cannot represent repeated user-requested
operations cleanly.

### Introduce `session_operations` as a request table

Rejected because the action payload is already the immutable operation request.

### Aggregate workspace setup into one action

Rejected because retry/discard units become unclear and partial-failure semantics become product
complexity.

### Continue after Project mutation in the same prepared context

Rejected because system prompt/tool context could omit the newly registered Project.

## Test Strategy

### E2E primary verification matrix

Primary product verification should use deterministic E2E coverage once implementation starts.
Required scenarios:

| Scenario | Expected evidence |
| --- | --- |
| New session with one worktree setup action | Setup action card completes before first assistant/model run starts; generated worktree Project appears in Workspace Projects. |
| New session with worktree action followed by first user message | First model turn runs only after fresh context includes the created Project. |
| Worktree action failure | Later pending input remains pending; UI shows failed action with Retry and Discard. |
| Retry failed worktree action | Only the failed action retries; later pending input remains ordered behind it. |
| Discard failed worktree action | Failed action becomes final failed; later pending input can proceed. |
| Browser reconnect during action execution | Live state restores action progress from durable events. |
| Worker restart during action execution | Runner resumes or reports durable failure without losing action identity. |

### E2E plan

- Use testenv fixtures to create an Agent with a ready runtime and a Git repository under
  `/workspace/agent`.
- Drive azents-web through the new-session flow that creates worktree setup actions.
- Assert visible ordering: action progress appears before first assistant output.
- Assert Project browser state after completion includes the generated worktree Project.
- Inject a deterministic Git failure fixture for retry/discard behavior.

### Fixture and prerequisite support

Fixture support is needed because the feature depends on a real Git repository, typed Runner Git
operations, and runtime filesystem state. Fixtures should provide:

- a local Git repository with at least one local branch;
- a branch/ref that can be used for successful worktree creation;
- a controlled invalid ref or collision scenario for failure testing;
- stable runtime readiness and cleanup between tests.

### Evidence format

Validation PRs should record:

- E2E command and environment;
- screenshots or trace artifacts for action progress/retry/discard UI;
- database assertions or API snapshots showing action event identity and Project registration;
- cleanup evidence for created worktrees; and
- any skipped live tests with explicit skip criteria.

### CI execution policy

Deterministic scenarios belong in CI. Optional/live environment tests may be skipped only when the
runtime provider or Git operation substrate is unavailable, and skipped tests must not hide regressions
in pure API/service behavior.

### Static and unit checks

Backend implementation phases should include targeted tests for:

- action payload validation;
- action execution ordering;
- durable event projection;
- retry/discard transitions;
- context invalidation/follow-up wake-up; and
- `session_git_worktrees` cleanup authority after action linkage migration.

Frontend phases should include Storybook stories for loading/running/failed/retry/discard/completed
action execution cards and TypeScript quality checks.
