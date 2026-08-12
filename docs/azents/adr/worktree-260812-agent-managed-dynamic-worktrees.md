---
title: "Agent-Managed Dynamic Worktrees"
created: 2026-08-12
tags: [architecture, agent, session, workspace, project, git, worktree]
document_role: primary
document_type: adr
snapshot_id: worktree-260812
---

# worktree-260812/ADR: Agent-Managed Dynamic Worktrees

## Context

The confirmed [worktree-260812/REQ](../requirements/worktree-260812-agent-managed-dynamic-worktrees.md) lets an Agent dynamically create and remove current-Session-owned Git worktrees after Session admission. Existing `create_git_worktree` operation TurnActions already provide durable allocation, Runner Git execution, Project registration, catalog and Skill projection refresh, terminal history, ownership-generation fencing, and prepared-context invalidation when the action executes before model dispatch. The new capability begins from a model function-tool call during an active AgentRun, so its execution identity, interruption behavior, and post-mutation context boundary require explicit decisions.

The existing action path does not refresh a running model turn in place. An operation action MailboxItem requires no inference and has a neutral turn effect. The executor processes it before model dispatch, synchronizes the filesystem Skill projection into `latest`, and returns context invalidation. When that action has no other inference-eligible input, the pending AgentRun performs no model call. A later inference input starts a fresh AgentRun; its ordinary `on_run_start` Skill hook adopts `latest` as `active` before the first model call. Session-scoped Toolkit instances may be reused across those Runs, but the new Run identity is the existing adoption boundary.

The same-Run context-invalidation path has a different contract. It rebuilds resolved inference settings while preserving the current Toolkit instances and `agent_prompt`. `SkillToolkit` adopts `latest` once per Run identity, so a second turn of the same Run does not currently reactivate a Project-change projection. Therefore the existing worktree lifecycle solves Project and Skill visibility through a fresh-Run boundary, not through same-Run continuation.

## Decision Map

- **D1 — Accepted:** Agent tools enqueue durable TurnActions instead of executing Git and Project mutations directly.
- **D2 — Accepted:** terminal TurnAction results enqueue a dedicated model-visible continuation input that starts a fresh AgentRun and reuses the existing Run-start context lifecycle.
- **D3 — Accepted:** expose separate path-based creation and removal tools while pinning resolved database identities inside their durable TurnActions.

## Decisions

### worktree-260812/ADR-D1 — Agent tools enqueue dedicated durable TurnActions

The Agent-facing dynamic worktree tools validate and durably enqueue dedicated operation TurnActions. They do not execute Runner Git operations, Project registration, cleanup, or context mutation inside the client-tool handler. The existing action-execution lifecycle remains responsible for durable allocation and ownership, Session-owner and Runtime-authority fencing, live progress, terminal history, Project and Skill projection mutation, and context invalidation.

The bridge from a model tool call to a TurnAction is limited to explicitly registered context-mutating operation tools. It is not a generic flag or convention available to arbitrary function tools, and ordinary tools continue to return their effects directly through normal client-tool results.

The enqueue is idempotently bound to the originating client tool call and current Session identity. A replay of the same admitted tool call converges on the same requested operation rather than appending another action. The immediate client-tool result reports only that the operation request was accepted for durable execution; the authoritative creation or removal outcome is delivered through the later action lifecycle.

This decision applies to worktree-260812/REQ-1, REQ-4, REQ-5, REQ-6, and REQ-7.

Direct mutation in the client-tool handler is rejected because it would duplicate the existing durable worktree lifecycle and weaken interruption recovery, ownership takeover fencing, live progress, terminal history, and Project-context invalidation. Treating every client tool as eligible to enqueue a TurnAction is rejected because TurnActions have special scheduling and context-rebuild semantics that should remain explicit operation infrastructure rather than a general-purpose deferred-tool mechanism.

### worktree-260812/ADR-D2 — Terminal results continue through a fresh AgentRun

An Agent-facing worktree tool returns only the durable acceptance of its associated TurnAction. The current AgentRun then yields at the operation boundary and does not perform another model call for that tool request. When the TurnAction reaches a terminal state, its bridge appends exactly one dedicated model-visible continuation input containing the bounded authoritative outcome and requests ordinary Session inference.

That continuation input starts a fresh AgentRun. The new Run uses the existing Run preparation and lifecycle path: Agent settings and prompt context are resolved again, Session Toolkit bindings are reconciled, `on_run_start` runs for the new Run identity, and `SkillToolkit` adopts the already synchronized `latest` projection as `active` before the first model call. Successful Project mutations therefore become visible through the same boundary already used by existing worktree TurnActions rather than through a new same-Run Skill or Toolkit refresh mechanism.

The continuation is an internal system-originated input, not a user-authored message and not merely a UI history event. It includes the operation identity, terminal status, bounded result or failure details, and the Project, path, ref, branch, preservation, or force-removal facts required by REQ-6 and REQ-7. The durable `ACTION_EXECUTION_RESULT` remains the authoritative operation-history projection; the continuation is its one-shot inference trigger and model-facing rendering.

The originating tool call, durable TurnAction, terminal result, and continuation input share a stable bridge identity. Admission replay, worker recovery, or terminalization replay converges on the same TurnAction and produces at most one continuation input. Only explicitly registered context-mutating operation bridges may request this handoff; ordinary client tools cannot end a Run or create continuation inference through a generic flag.

The continuation records the Run that actually terminalized the bridge action as its predecessor. It is not promoted while that predecessor remains nonterminal. Bridge action processing first completes that Run, then a later processing boundary consumes the continuation and creates the fresh AgentRun. This fence also applies when worker loss causes the action to execute in a later action-processing Run rather than the originating tool Run. A registered bridge admission must be observed at the tool boundary independently of provider `needs_follow_up`, and durable Session wake-up remains required for owner loss and idle recovery. Ordinary `context_invalidated` actions retain their existing same-Run rebuild behavior.

This decision applies to worktree-260812/REQ-1, REQ-4, REQ-5, REQ-6, and REQ-7.

Continuing the same AgentRun after context invalidation is rejected because the current invalidation path preserves Toolkit instances and `agent_prompt`, while `SkillToolkit` adopts filesystem projection changes once per Run identity. Supporting that option would require a new cross-Toolkit reactivation contract and would duplicate the existing fresh-Run context lifecycle. Exposing `ACTION_EXECUTION_RESULT` directly as recurring model history without a continuation input is rejected because it does not define a one-shot inference boundary and mixes durable UI history with model scheduling. Completing the original Run without automatically enqueueing inference is rejected because the Agent would not receive the terminal result in time to continue the initiating request.

### worktree-260812/ADR-D3 — Path-facing tools pin database identities

Eligible Agents receive two explicit tools: one creates a managed worktree from an exact current Session Project path, and one removes an exact current Session managed-worktree path. The creation input accepts `source_project_path` with optional `starting_ref` and optional `branch_name`. The removal input accepts `worktree_path` and an optional `force` flag that defaults to false.

At tool admission, the bridge normalizes the supplied path within the current Runtime Workspace and resolves it against the current shared Session context. Creation requires an exact registered `SessionWorkspaceProject` that is Git-backed. Removal requires an exact current-Session `SessionGitWorktree` allocation linked to that registered Project. The bridge stores the resolved Project or worktree allocation identity in the durable TurnAction alongside the user-facing path and optional parameters. Action execution revalidates that pinned identity, Session context, path, allocation ownership, and Runtime authority before applying side effects.

When `starting_ref` is absent, creation resolves the selected Project's current `HEAD`. When `branch_name` is absent, Azents generates a collision-free Session-related branch. A supplied branch must be new and valid. A linked-worktree source is resolved to its underlying repository while retaining the selected Project's current `HEAD` as the default starting point.

Removal defaults to non-force operation. A dirty or untracked target remains registered and returns bounded guidance permitting a later explicit `force=true` request. Successful removal unregisters only the managed worktree Project and preserves its branch. Neither tool accepts an arbitrary repository, directory, Project from another Session, ordinary Project removal target, primary worktree, unmanaged worktree, or another Session's allocation.

The terminal continuation renders paths, refs, branch names, and bounded outcomes rather than requiring the model to reason from opaque database IDs. Internal identities remain available for idempotency, concurrency, ownership, and time-of-check/time-of-use fencing but are not the primary Agent-facing selection contract.

This decision applies to worktree-260812/REQ-2, REQ-3, REQ-4, REQ-5, REQ-6, and REQ-7.

An opaque-ID Agent interface is rejected because the existing Runtime Workspace context presents Project paths, not Project or allocation UUIDs. Adding a second UUID inventory would duplicate Project context and make ordinary path-oriented Agent work less legible without improving server-side authority, since the bridge can resolve and pin identities at admission. Accepting paths without pinning database identities is rejected because normalization alone is not durable ownership authority and would leave execution vulnerable to context changes between tool admission and TurnAction execution.

## Fixed and Derived Outcomes

- Dynamic worktree tools are available in every eligible active Session.
- Creation sources are limited to Git Projects already registered in the current shared Session context.
- A linked-worktree source resolves to its underlying repository identity.
- The source Project remains registered; a successful generated worktree becomes an additional Project.
- Removal authority requires a matching current-Session Azents worktree ownership record.
- Non-force removal protects dirty or untracked content; explicit force may discard it without separate user confirmation.
- Agent-requested removal preserves the branch and cannot remove ordinary Projects, primary worktrees, unmanaged worktrees, or another Session's worktrees.
- Runtime Git operations remain fenced to the exact current Runner-reported Workspace and Runtime authority.
- A bridge continuation is consumed only after the Run that terminalized its action is terminal.
- Ordinary Project-context invalidation continues through the existing same-Run rebuild path; only the registered worktree bridges use the fresh-Run handoff.
- Durable Session wake-up is required independently of provider `needs_follow_up`.

## Agent-Owned Details

The implementation may choose local identifiers, helper and module boundaries, equivalent internal result types, bounded error codes and copy, logging fields, fixture composition, and collision retry details that preserve the accepted Requirements and ADR decisions without introducing another lifecycle, authority, compatibility mode, or user-visible capability.
