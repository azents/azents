---
title: "Projects, working folders and worktrees"
created: 2026-11-04
tags: [wiki]
---

# Projects, working folders and worktrees

Owns which filesystem paths enter a Session’s working context, automatic Project policy and managed worktree cleanup. Runtime owns physical files; the Session context owns prompt eligibility. Durable operation execution is defined separately.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Runtime persistence](../flow/agent-runtime-persistence.md)
- [Durable Session actions](../execution/actions.md)
- [Instructions and Skills](../tools/instructions.md)
- [Workspaces and membership](../domain/workspace.md)
- [Agent](../domain/agent.md)
- [Conversations and events](../domain/conversation.md)
- [Toolkits](../domain/toolkit.md)

## Automatic root Session Project policy

Every Agent owns one `agent_automatic_project_settings` row, created with revision 1
and an empty item set when the Agent is created. Its
`agent_automatic_project_items` rows store a unique ordered list of normalized
absolute directory paths under the current Runner-reported Agent Workspace root.
Position and path are both unique within one Agent policy.

The policy is administrator-managed configuration for automatic root Session
creation. It is distinct from `agent_project_defaults`, presets, and catalog
projections used by the explicit new-Session draft UI. Replacing the policy does
not mutate existing root Sessions or their shared context Projects.
Permanent Runtime removal clears the ordered items and advances the policy revision once when a
non-empty policy is cleared. It preserves the settings row as the required empty-policy concurrency
authority so Runtime-free and later re-added Agents can continue creating automatic root Sessions.

## Automatic root Session Projects

```http
GET /agent/v1/workspaces/{handle}/agents/{agent_id}/automatic-session-projects
PUT /agent/v1/workspaces/{handle}/agents/{agent_id}/automatic-session-projects
```

Only an explicit AgentAdmin may read or replace this policy. Workspace ownership or
membership alone does not grant policy management.

- GET returns the complete ordered `project_paths`, current `revision`, updater, and
  timestamps without Runtime I/O.
- PUT is a complete replacement with `expected_revision` optimistic concurrency.
  Paths are normalized, duplicate normalized paths keep their first position, and
  an accepted replacement increments the revision exactly once.
- A non-empty replacement validates every path as an existing directory through the
  Agent Runtime before opening the final replacement transaction. Missing files,
  non-directories, Agent Workspace root, and out-of-root paths are rejected without
  changing the policy.
- An empty replacement clears the policy without requiring Runtime availability.
- A stale revision returns `409` with
  `automatic_session_projects_revision_conflict`; unavailable Runtime validation
  returns `409` with `automatic_session_projects_runtime_unavailable`.
- Successfully validated paths also refresh their Agent Project Catalog projection
  to available. Catalog status remains a UI projection and is not the policy source
  of truth.

Azents Web exposes this policy under the Agent Settings Projects page. The editor
maintains an ordered draft with add, remove, and move controls backed by the shared
Agent Workspace directory picker. Background query refresh does not replace an
initialized draft. Save sends the complete draft with its baseline revision;
success adopts the returned paths and revision, while validation, Runtime, generic,
and revision-conflict failures preserve the draft. Reload latest is an explicit
action that replaces the draft after a conflict.

## Session Worktree Database Ownership

Session Git worktree admission, allocation, Project linking, path claims,
action progress/result writes, cleanup settlement, and terminal handoff execute
as completed database-only repository operations. Their existing atomic groups
remain separate: a repository does not retain a transaction across Runner,
Runtime resolution, Git, filesystem, Skill invalidation, or projection callbacks.
Independent Session, allocation, and action observations use read-only scopes.

Critical dependent mutations fence the exact Session owner generation in the
same transaction as their writes. Binding validation composes with allocation,
Project linking, and catalog mutations within that operation; it is not an
independently committed service bridge. Runtime/path coordination and exact path
claim locks retain their order inside the mutation group. A stale execution
owner or binding cannot commit dependent state.

Terminal handoff atomically appends the durable action snapshot, creates the
idempotent bridge continuation and input wakeup when applicable, and deletes the
live action row. Failure or cancellation rolls the group back; replay returns
the existing durable event and requires retained continuation authority.
External callbacks run only after the operation finishes. Archive cleanup
likewise finishes its database claim/preparation or settlement before external
checkout removal and Skill effects.

## Agent Workspace Projects

Agent Workspace Project is a boundary registry explicitly registered by user for an existing directory under AgentRuntime's current Runner-reported Agent Workspace. Agent Workspace root itself is not a Project. Current public API registers any non-root descendant directory under that Runtime-specific root, including nested folders.

- Project Source, archive upload, empty folder bootstrap, Runtime pending load/ACK do not exist in public API or current DB/service/runtime provisioning layers. Provisioning such as file creation, archive extract, and git clone is separated into future Project Import/Provisioning phase.
- New session creation accepts `existing_project_paths` plus ordered `setup_actions`. Existing Project paths register explicit Project paths and do not copy Projects from the team-primary session. `create_git_worktree` setup actions create Azents-owned Git worktrees from source Project paths and starting refs, then register the created worktree paths as session Projects. Legacy `workspace_items`, `workspace_mode`, and `project_paths` requests are not part of the current contract.
- `agent_automatic_project_settings` and ordered
  `agent_automatic_project_items` store the Project policy used only when a root
  Session producer selects Agent-default workspace intent. Every Agent begins with
  an empty revision-1 policy. Policy reads are coherent snapshots, and complete
  replacements use an expected revision so a stale draft cannot overwrite a newer
  policy.
- AgentAdmin policy management normalizes and de-duplicates paths while preserving
  first-seen order. A non-empty replacement validates every directory through the
  current Agent Runtime before the final locked revision check and atomic replace.
  An empty clear requires no Runtime. Validation or revision failure leaves the
  previous ordered policy unchanged.
- Automatic Project policy management uses a completed, native read-only
  repository admission/policy snapshot before Runtime directory validation.
  Non-empty path validation and Runtime target discovery run with that read scope
  closed. The final repository write rechecks the exact Agent Workspace and
  explicit AgentAdmin relationship, locks that authority and the current policy,
  then atomically replaces the ordered policy and catalog availability projection.
  Revoked management authority, stale revisions, SQL failures and cancellation do
  not leave a partial policy/catalog change. Empty clears still require no Runtime.
- Automatic root creation reads the policy inside its caller-owned database
  transaction and writes those paths directly to the new
  `SessionAgentContext`. It performs no Runtime I/O at Session creation time.
  Existing Sessions keep their context-owned snapshot when policy configuration
  changes.
- Permanent Runtime removal clears automatic policy items, defaults, presets, catalog rows, context
  Projects, and managed worktree metadata. It preserves the automatic policy settings row as an
  empty revisioned policy required by later root Session creation.
- `agent_project_defaults` stores the last non-empty new-session workspace selection used when creating a non-primary session for the Agent. New-session defaults come from this table, not from the current live Project rows of the most recent session. Creating a new session with non-empty existing Project paths or setup actions replaces the stored defaults in selection order; creating a session with an empty selection leaves the stored defaults unchanged.
- `GET /chat/v1/agents/{agent_id}/session-project-defaults` returns both legacy `project_paths` and ordered `items` for the new-session UI, including source metadata (`empty` or `last_created_session`).
- `agent_project_presets` stores agent-scoped recent Project path presets. Creating a new session with selected Projects or registering an existing Project refreshes matching presets. `GET /chat/v1/agents/{agent_id}/project-presets` returns these presets ordered by recent use.
- `agent_project_catalog` stores Agent-scoped reusable Project path candidates and filesystem status projection (`unchecked`, `available`, `missing`, `unavailable`, or `error`) with optional detail and `last_checked_at`. Catalog status is a UI projection; it does not decide prompt Project eligibility. Worktree action execution upserts the created worktree path into the catalog and may refresh status, but it does not update last-created-session defaults after execution.
- `GET /chat/v1/agents/{agent_id}/git-refs?source_project_path=...` previews branches, tags, default branch, and HEAD commit for a Git source Project through typed Runtime Runner Git operations. Runtime unavailable or Git semantic failures are surfaced as user-safe preview errors.
- `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/projects/register` registers an existing directory as Project for the selected AgentSession's shared `SessionAgentContext`. Server validates user access, agent/session match, active Runtime directory existence, and Project path policy, then creates the context-owned registry row. This API does not modify filesystem.
- Existing-session registration first completes its database authorization and
  binding snapshot, performs Runtime path resolution and directory validation
  without an active database transaction, and then uses one database-only
  operation repository to revalidate access, binding identity, target path, and
  conflicts while atomically creating the Project, preset, and catalog effects.
  Final Project operations acquire locks in the retained order `Agent ->
  AgentSession -> membership -> binding/context -> Project/path`.
- `GET /chat/v1/agents/{agent_id}/sessions/{session_id}/projects` returns registered Project list for the selected AgentSession. Public response exposes only `id`, `path`, `created_at`, `updated_at`.
- `GET /chat/v1/agents/{agent_id}/sessions/{session_id}/workspace/project-browser-manifest` returns a backend-owned Project browser manifest for the selected session. It derives Project root entries from `session_agent_context_projects`, joins catalog status projection by Agent/path, and returns backend-provided capabilities. Project root entries allow registry removal when tied to a session Project and disallow filesystem delete, move, and rename. Entries linked to `session_agent_context_git_worktrees` expose `repository_type: "git"` so clients can render Git-specific Project root metadata without probing the filesystem. A non-cleaned Azents-owned worktree Project also exposes `delete_worktree: true`; ordinary Project registry rows and preview entries do not.
- `POST /chat/v1/agents/{agent_id}/workspace/project-browser-manifest/preview` accepts explicit `project_paths` before a session exists and returns the same Project browser entry model. Preview entries do not expose session registry removal because no session Project row exists yet, and they do not expose repository metadata.
- Project browser manifest reads do not call runtime runner file stat/list operations before responding. Missing or unchecked catalog projection is represented as stored/unchecked status and may be refreshed by separate boundary-triggered sync work.
- Manifest access checks and Project/worktree/catalog preparation are completed
  read-only repository operations. Session working-folder binding and Runtime
  workspace evidence resolution run between closed reads. The final Session or
  preview read repeats its existing membership/Agent authority after Runtime
  preparation and returns detached ordered rows. Stored unchecked status,
  Git/worktree metadata, capability policy and non-blocking refresh hints are
  presented by the service; no filesystem/Runtime callbacks or live database
  handles cross the repository boundary.
- `DELETE /chat/v1/agents/{agent_id}/sessions/{session_id}/projects/{project_id}` removes only the selected Session's shared context registry row. Filesystem folder deletion is destructive and not included. Azents-owned worktree cleanup is a separate explicit cleanup or archive-time best-effort lifecycle based on `session_agent_context_git_worktrees` ownership metadata, not on the Project registry row alone. Retention purge deletes only the allocation row and never accesses Runtime or Git state.
- `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/git-worktree/cleanup` requests destructive cleanup for Azents-owned worktree allocations. When `project_id` is supplied, cleanup is scoped to the allocation linked to that session Project; otherwise cleanup covers all non-cleaned allocations for the session. Cleanup validates session ownership, containment under `<current-agent-workspace>/.azents/worktrees`, branch name presence, and Azents-created branch ownership before calling Runner Git cleanup. Successful cleanup removes the Git worktree without force, deletes the Azents-created branch, removes the catalog entry, deletes the linked session Project row, and best-effort removes the empty session-scoped worktree parent directory. Failure or cancellation of that final empty-parent removal does not revert otherwise confirmed Git cleanup.
- `cleanup_orphan_git_worktrees` is a parameterless, explicit chat TurnAction rather than a direct
  destructive REST route. It is scoped to the invoking Session's current Runtime and may force-remove
  dirty or untracked Azents-managed worktrees that are not connected to any active root Session while
  preserving their local branches. A Runtime-scoped coordination lock and path-overlap cleanup claims
  serialize Project attachment, worktree target allocation, and cleanup admission; an exact,
  ancestor, or descendant active Project connection wins protection. Database transactions and
  advisory locks do not span Runner I/O; expired claims are reclaimable only after owner validation,
  and archive cleanup remains a
  best-effort non-blocking competitor. The action's live and durable result is bounded and
  content-free, with per-candidate `removed`, `already_absent`, `protected`, `failed`, or
  `unresolved` outcome.
- Workspace operation TurnActions share the closed public policy and preparation
  registry with other actions, then execute through a Worker-owned closed
  operation registry. Public worktree creation and cleanup retain required
  inference-profile admission without requiring inference during operation
  preparation. Session-folder and Agent-managed worktree variants remain internal.
- Path policy follows: the current Agent Workspace root is forbidden, paths outside that root are forbidden, and exact duplicate Project paths per session are forbidden. Nested Project paths are allowed.
New-session azents-web UI shows a compact additive workspace item list above the draft first-message composer. It loads stored last-created-session defaults, shows recent agent-level presets, lets users add repository folders to the list, and lets each selected folder switch between repository and new worktree modes from the row-level type selector. The runtime-backed folder picker can select the current folder so a Git repository directory itself can be added without relying on an existing preset. Worktree branch selection in this draft UI uses the Git ref preview endpoint but exposes only local branches by default; remote branches and tags are not shown in the base branch selector. Concrete session azents-web UI exposes Project management inside the Workspace surface instead of a separate Projects tab. The Workspace browser opens in `Projects` mode by default, lists registered Project roots, and keeps `All files` as an explicit secondary mode rooted at the Agent Workspace root. Empty Project sets show an explicit empty Projects state and do not fall back to Agent Workspace root entries. Project browser root rows display the folder basename as the primary label and render the full absolute path as dimmed, truncated secondary text after the name. The secondary path truncates before the primary label; the primary label truncates only when it exceeds the available row width. Git-backed Project root rows use a Git folder icon; non-Git Project roots keep the normal folder icon. Expanding an unloaded directory keeps that row expanded. A requested load shows a directory-local loading indicator, a failed load shows an inline error, and returned children render in place without requiring a collapse/re-expand cycle.

In an existing concrete session, Register Project opens a runtime-backed Agent Workspace folder picker rooted at the Agent Workspace root. The picker reads Agent Workspace filesystem entries, not Project browser manifest entries or the already-registered Project set. Generic directory listing does not probe every child for Git metadata. Its description and current-directory controls remain outside one bounded vertical content viewport; directory entries and non-ready status content scroll inside that viewport on desktop and narrow mobile layouts, including touch scrolling in Safari, without creating nested modal scrolling. Selecting one folder performs one explicit repository-type inspection for that path: a non-Git folder is validated and registered as an existing Agent Workspace directory through the session Project register API, while a Git repository folder opens a registration mode dialog with `Existing directory` and `New worktree` choices. `New worktree` requires a starting ref from Git ref preview and submits a durable `create_git_worktree` operation TurnAction with the current message/input boundary rather than appending session-initialization setup work. The operation creates a session-scoped Azents-owned worktree, registers the generated worktree path as a session Project, upserts the Agent Project Catalog, refreshes the Project/Skill projection, and lets the active run rebuild context after the Project registry changes. Worktree execution is keyed by the source `input_buffer_id` and fenced by the admitting Session owner generation. Active state and logs remain live until completion, failure, or cancellation atomically appends one durable result snapshot and removes the live execution. Ownership takeover cancels leftover work without re-executing the Git side effect; terminal results have no retry or discard mutation APIs.

Git-backed Project root rows separate registry removal from destructive cleanup. `Remove from session` removes only the session Project row. `Delete worktree` is shown only when the backend manifest exposes `delete_worktree` for an Azents-owned non-cleaned allocation and routes to the Git worktree cleanup API. Source upload/list/delete, bootstrap source type selection, and agent-initiated Project approval workflow are not currently implemented.

## Session working-folder lifecycle

Each root `SessionAgentContext` stores a nullable historical path, optional logical Runtime ID, and
one binding state:

- `none` is assigned to roots created while Runtime-free. It has no path and is never eligible for
  later automatic binding.
- `pending` is assigned to managed roots before current Runner Workspace evidence is available. An
  explicitly authorized Session-folder preparation may bind it exactly once.
- `bound` owns one exact unique path under the current Runner-reported Agent Workspace. Only this
  state authorizes Session files, Project/worktree operations, Runtime prompt/default workdir, and
  archive folder cleanup.
- `invalidated` retains its historical path and removal evidence for audit after permanent Runtime
  removal but authorizes no Runner, browser, setup, retry, Project, worktree, or archive operation.

Direct human input and External Channel message admission share missing-folder setup admission.
Before allocating the incoming message's queue order, they enqueue one internal
`create_session_working_folder` action for eligible `pending` or `bound` contexts that have no
pending or recorded setup action. Setup admission and input admission use the same database
transaction; the Worker materializes the folder through the Runner before processing the new
message group. This also repairs previously created channel Sessions on their next channel
message without requiring a Web message. Runtime-free and invalidated contexts remain ineligible.
Concurrent admission uses the context-owned idempotency key to avoid duplicate setup rows.

The existing-session Project browser includes the Session-folder entry only for an active managed
binding. Runtime-free and invalidated contexts return a capability-aware unavailable state rather
than exposing a historical path. A later Runtime add never binds an old `none` or `invalidated`
context; only a newly created post-add root may enter `pending` and then `bound`.

New worktrees allocate below a currently bound Session folder and remain independently registered
as top-level Git Projects. Archive performs best-effort Git and folder cleanup only for an
authorized `bound` context. Permanent Runtime removal invalidates all retained `pending` and
`bound` contexts in bounded batches and relies on terminal Runtime deletion for physical Workspace
removal instead of dispatching per-Session folder deletion. Retention purge remains database-only.

## Git worktree-created Projects

A Git worktree-created Project is an Agent Workspace Project whose directory is created under the Azents reserved worktree root for one non-primary AgentSession. The source Project path must be an existing Git repository reachable inside the Agent Runtime workspace. The selected starting ref is resolved by Runner Git operations, and creation uses a generated branch/worktree path based on the session handle and source repository leaf. The unsuffixed repository leaf is used whenever that directory name is available. Directory collisions select the lowest available numeric suffix starting at `-2`, while branch collisions advance their suffix independently. A cleaned allocation releases its directory name, while recorded branch names remain reserved independently. The persisted allocation records the final names.

A non-primary session can own a Git worktree allocation created by a `create_git_worktree` setup action. The action is stored as an ordered `action_message` input before the first user message and is consumed without appending an `action_message` transcript event. Preparation durably claims execution by `input_buffer_id` before deleting the buffer. Successful action execution invalidates the prepared context until the worktree path is created, registered as the session Project, and the next processing boundary rebuilds context; failed action execution is terminal, appends durable result history, and FIFO input processing continues.

Each created worktree is prompt-eligible only through its context-owned `SessionWorkspaceProject` projection, just like manually selected Projects. The `SessionGitWorktree` row is retained for lifecycle and cleanup, and links to the registered Project row after registration succeeds. Explicit user-requested cleanup remains session-scoped. After a Session archive transaction commits, archive makes one forced best-effort pass over every non-cleaned root-tree allocation. Successful cleanup removes the owned worktree and Azents-created branch, removes the session-scoped reserved worktree parent directory when it becomes empty, deletes catalog and linked Project rows, and marks the allocation cleaned. Failure is recorded and logged but does not fail archive or schedule retry. Durable purge does not inspect or remove physical worktrees and deletes allocation rows through database finalization regardless of cleanup status.

The dynamic worktree Toolkit exposes both `create_git_worktree` and
`remove_git_worktree` independently of current Project or allocation eligibility.
Admission still revalidates the exact Session context, Runtime and Project or
allocation authority; visibility alone does not authorize an operation.

An eligible root or subagent may also create a worktree on demand from an exact Git Project already
registered in its shared current Session context. The Agent-facing action pins the source Project
identity at admission, revalidates it before Runner mutation, defaults an omitted starting ref to that
Project worktree's current `HEAD`, and may generate a collision-free branch. Confirmed creation leaves
the source Project unchanged, registers the generated checkout as an additional shared Session
Project, updates the Agent Project Catalog, and refreshes filesystem Skill projection for the fresh
continuation Run.

Agent-requested removal is authorized only for an exact non-cleaned `SessionGitWorktree` allocation
linked to an exact current-context Project. It shares the managed-path claim boundary with manual and
archive cleanup, but its semantics are branch-preserving. Non-force removal refuses dirty or
untracked content without changing the Project or allocation. Explicit force may discard that
checkout content. After Runner confirms removal or absence, the service removes the linked Project
and catalog entry, refreshes Skill projection, and marks the allocation cleaned while retaining its
source and preserved branch metadata. It never calls branch deletion. Archive skips that cleaned
allocation, so it cannot later delete the branch preserved by the Agent-facing removal.

## Agent Project Catalog operation boundaries

Agent Project Catalog candidate upserts, entry lists, exact-path status snapshots,
and status application finish inside repository-owned operations. Independent
lists and snapshots use PostgreSQL read-only scopes and return detached domain
entries; candidate batches and status batches retain one atomic write group and
the exact Agent/path identity. Runtime target resolution, Agent Workspace path
normalization, and Runner filesystem probes occur outside every open catalog
transaction, before their resulting status evidence is applied.

Catalog filesystem status is descriptive Agent-scoped evidence and does not
inherit a Session owner-generation gate. Canonical Session and action ownership
remain fenced at their actual registry/action mutation boundaries; descriptive
status refresh does not grant Project registration or action admission authority.

## Session Project eligibility and ownership

`rdb/models/session_workspace_project.py` stores the project registry used as session working
context. `SessionWorkspaceProject` rows are owned by `AgentSession` through `session_id`.
Runtime owns only the physical workspace where project paths exist.

Project and context inspector routes are session-scoped under
`/chat/v1/agents/{agent_id}/sessions/{session_id}/...`. They validate that the selected session
belongs to the requested agent and that the requester is a workspace member before reading or writing
that session's rows. Runtime lookup is allowed only after that session context is selected, and only
for physical workspace validation or runner filesystem operations. Runtime current project, selected
project, active project, team-primary fallback, and runtime-owned project catalog state are not part of
the conversation prompt contract. The Agent Project catalog is only a reusable path/status projection
for browser and new-session preview UI; session Project rows remain the prompt-eligibility source.

RuntimeToolkit loads registered project prompt content from the current logical `AgentSession` ID.
Runtime context sharing affects shell/file operations; it must not make project registry ownership or
project prompt selection fall back to a parent, team-primary, or runtime session.
Project finalization preserves the shared `Agent -> AgentSession` lock prefix,
then locks membership, binding/context, and Project/path authority in that order.
This matches input and promotion paths and prevents opposing Session-then-Agent
waits.

## Managed worktree allocation ownership

`session_agent_context_git_worktrees` is the cleanup authority for Azents-owned worktrees. It stores the source
Project path, starting ref, generated worktree path, generated branch name, base commit, status,
failure summary, cleanup summary, and the owning action execution when the worktree came from a
TurnAction. Worktree creation uses typed Runner Git operations, registers exactly the created path in
`session_agent_context_projects`, and upserts the Agent Project catalog entry without updating
last-created-session defaults. Existing Project selections still refresh presets/defaults directly;
worktree actions refresh source-path presets and register only the created worktree path as prompt
context. Generated paths are allocated under
`<current-agent-workspace>/.azents/worktrees/<session-handle>/`. The ownership row,
not reserved-root membership or `session_agent_context_projects`, is required
before destructive cleanup can remove a path or branch.

## Agent worktree tools

The auto-bound, unprefixed Dynamic Worktree Toolkit is resolved for root and subagent turns only
when the Session is active, the Agent has managed Runtime capability, the shared Session context has
current bindable or bound Workspace authority, and no removal fence denies Runtime work. It is not
restricted to External Channel Sessions and carries no requester identity.

It exposes:

- `create_git_worktree(source_project_path, starting_ref?, branch_name?)`, which accepts only an
  exact Git Project already registered in the current shared Session context; and
- `remove_git_worktree(worktree_path, force=false)`, which accepts only an exact current-context
  Project linked to a non-cleaned Azents-managed worktree allocation.

Both handlers normalize paths against current Runner Workspace evidence, pin Project/allocation,
context, Session, Run, and client call identities, and enqueue a dedicated internal TurnAction. The
tool result reports durable acceptance only. Git inspection and mutation occur later in the action
executor under current authority. The bridge idempotency key is derived from Session ID, Run ID, tool
name, and client call ID, so duplicate execution of one admitted call returns the same request.

Each Run owns an internal `TurnActionBridgeBoundary` shared only by this Toolkit and Engine
execution. After admission the boundary forces one action-input poll after the foreground tool batch,
even when provider output requests no follow-up. It is not model-settable through arguments, result
metadata, hooks, or generic Toolkit context. A registered bridge action terminates the current Run
after atomic terminal handoff; its hidden continuation starts a fresh Run, allowing normal Toolkit
reconciliation and filesystem Skill `latest` to `active` adoption before the next model call.

## API route entrypoints

- `/chat/v1/agents/{agent_id}/workspace/repository-type`

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/repos/session_working_folder_setup.py`](../../../../python/apps/azents/src/azents/repos/session_working_folder_setup.py)
- [`python/apps/azents/src/azents/repos/agent_workspace_access.py`](../../../../python/apps/azents/src/azents/repos/agent_workspace_access.py)
- [`python/apps/azents/src/azents/core/session_workspace_paths.py`](../../../../python/apps/azents/src/azents/core/session_workspace_paths.py)
