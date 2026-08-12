---
title: "Agent-Managed Dynamic Worktrees Requirements"
created: 2026-08-12
updated: 2026-08-12
implemented: 2026-08-12
tags: [agent, session, workspace, project, git, worktree, external-channel]
document_role: primary
document_type: requirements
snapshot_id: worktree-260812
---

# Agent-Managed Dynamic Worktrees Requirements

- Snapshot: `worktree-260812`
- Document reference: `worktree-260812/REQ`

## Problem

External Channel Sessions start with the Agent's configured automatic Projects so Slack and Discord requests can begin without asking the user to select Projects or waiting for a Git worktree to be created. This keeps the first response path natural, but concurrent coding requests may then modify the same shared Project checkout from multiple Sessions and conflict with each other.

An Agent can create a worktree with shell commands, but an unmanaged worktree is not registered in the Session's Project context. Project-scoped instructions, Skills, browsing, ownership, and cleanup behavior therefore do not follow the new working directory. Users need Agents to create isolated worktrees only when a task requires them, use those worktrees as normal Session Projects, and remove temporary worktrees without losing access to the original Project for later tasks.

## Primary Actor

A workspace member who invokes an Agent through Slack or Discord and expects a coding task to run in an isolated checkout without delaying every External Channel Session at creation time.

## Primary Scenario

An External Channel request creates a Session immediately with the Agent's configured automatic Project snapshot. After determining that the request requires isolated Git changes, the Agent selects one Git Project already registered in that Session and dynamically creates a worktree for the task. The generated worktree becomes an additional Session Project, so subsequent work in that path uses Project-scoped instructions and Skills. The original Project remains registered. When the isolated workspace is no longer needed, the Agent removes only that managed worktree Project while preserving its branch and leaving the original Project available for the next task.

## Supporting Scenarios

- An Agent in a Web-created or otherwise active Session uses the same capability; it is not limited to External Channel Sessions.
- A Session contains multiple registered Git Projects and creates multiple managed worktrees over its lifetime.
- The selected source Project is itself a linked Git worktree, and the new worktree is created from the same underlying repository.
- The Agent starts from the selected Project's current `HEAD` or explicitly chooses another branch, tag, or commit.
- The Agent chooses a descriptive new branch name or lets Azents generate a collision-free name.
- Removal encounters dirty or untracked content, and the Agent decides whether to preserve it or explicitly discard it.
- Root and descendant Agents use the same generated Project through their shared Session Project context.

## Goals

- Preserve fast External Channel Session creation without mandatory worktree setup.
- Let Agents isolate coding work after understanding the request.
- Keep dynamically created worktrees inside Azents Project, instruction, Skill, ownership, and cleanup lifecycles.
- Support repeated creation and removal without removing the stable source Projects needed for later work.
- Give Agents bounded removal authority over only the managed worktrees owned by the current Session.

## Non-Goals

- Discovering or using unregistered Git repositories as worktree sources.
- Registering arbitrary directories or repositories as Projects through the Agent capability.
- Automatically cloning repositories or promoting newly cloned repositories into Project context.
- Automatically creating a worktree for every External Channel or other Session.
- Replacing or unregistering the source Project when a worktree is created.
- Removing ordinary registered Projects, repository primary worktrees, unmanaged linked worktrees, or worktrees owned by another Session.
- Deleting the generated Git branch when the Agent removes a worktree.
- Adding a trusted or untrusted Project state for repository instructions in this capability.

## Requirements

### REQ-1. On-demand isolation without Session-creation delay

An Agent must be able to create an isolated Git worktree after an active Session has begun, without requiring worktree creation during automatic Session admission.

**Acceptance criteria**

- External Channel Session creation continues to snapshot configured automatic Projects without waiting for Runtime Git worktree creation.
- The capability is available in every eligible active Session regardless of whether the Session originated from Web, Slack, Discord, or another producer.
- A Session that never needs isolated Git work performs no dynamic worktree operation.
- Worktree preparation progress or failure is visible in the invoking Session and does not appear as an unexplained delay.

### REQ-2. Source limited to current Session Git Projects

A dynamically created worktree must derive from a Git Project already registered in the current Session's shared Project context.

**Acceptance criteria**

- The Agent selects the source by a current Session Project identity rather than by an arbitrary unregistered filesystem path.
- A registered non-Git Project is rejected without creating or registering a worktree.
- An unregistered repository, Agent Project Catalog candidate, newly cloned repository, or Project from another Session cannot be selected directly.
- A selected linked worktree is resolved to its underlying Git repository before another worktree is created.
- Repository and target resolution remains within the current Agent Runtime's authorized Workspace boundary.

### REQ-3. Explicit or default starting point and branch

The Agent must be able to create a worktree from a useful default starting point while retaining control over the ref and new branch when the task requires it.

**Acceptance criteria**

- When no starting ref is supplied, creation starts from the selected Project's current `HEAD`.
- For a selected linked worktree, the default is that worktree's current `HEAD`.
- The Agent may explicitly select another valid branch, tag, or commit as the starting point.
- The Agent may supply a valid new branch name.
- When the Agent omits a branch name, Azents generates a collision-free Session-related branch name.
- An Agent-supplied branch name must be new and cannot overwrite or reuse an existing branch.

### REQ-4. Managed worktree Project registration

A successfully created worktree must become an additional managed Project in the current Session without changing the source Project registration.

**Acceptance criteria**

- The worktree is created beneath the current Session working-folder boundary.
- The generated path is registered only after Git worktree creation succeeds.
- The registered worktree participates in Project-scoped instruction, Skill, browsing, and context behavior like other Git Projects.
- Subsequent Agent work can address the exact generated Project path returned by creation.
- The source Project remains registered and unchanged.
- Multiple source Projects and multiple generated worktree Projects may coexist in the same Session context.
- Root and descendant Agents sharing that context observe the generated Project according to the existing shared Project model.
- Creating and registering the derived worktree requires no additional user approval.

### REQ-5. Removal restricted to current-Session managed worktrees

The Agent must be able to remove a generated worktree only when Azents records it as a managed worktree owned by the current Session context.

**Acceptance criteria**

- The Agent selects a current Session managed worktree identity rather than an arbitrary filesystem path.
- Ordinary registered Projects cannot be removed through this capability.
- A repository's primary worktree cannot be removed through this capability.
- Unmanaged linked worktrees and worktrees owned by another Session cannot be removed through this capability.
- Successful removal removes that worktree's filesystem checkout and Session Project registration and refreshes the Project and Skill context.
- Successful removal does not unregister, restore, replace, or otherwise change the source Project.
- The generated branch is preserved after removal.

### REQ-6. Explicit force removal with model-facing recovery guidance

Removal must protect dirty work by default while allowing the Agent to explicitly discard it when appropriate to the task.

**Acceptance criteria**

- Removal defaults to non-force behavior.
- A dirty worktree or one with untracked content is not removed by a non-force request.
- A dirty non-force failure clearly tells the Agent that it may retry with explicit force when discarding those changes is intended.
- An explicit force request may irreversibly remove dirty and untracked worktree content without separate user confirmation.
- Force authority remains limited to a current-Session-owned managed worktree and does not expand to other Projects, worktrees, or branches.
- A successful removal tells the Agent that the branch was preserved, identifies that branch, and suggests separate branch cleanup when it is no longer needed.
- The removal capability itself never deletes the branch.

### REQ-7. Observable, bounded lifecycle outcomes

Creation and removal must provide enough outcome information for the Agent and user to understand which isolated workspace changed and what remains afterward.

**Acceptance criteria**

- Successful creation identifies the source Project, generated worktree Project, exact working path, starting point, and branch.
- Failed creation registers no generated Project and reports a bounded actionable reason.
- Successful removal identifies the removed worktree Project and preserved branch.
- Failed removal leaves Project registration and ownership state consistent with the confirmed filesystem outcome.
- Repeated or concurrent requests do not silently create duplicate ownership for the same operation or remove an ineligible target.
- Session archive and existing lifecycle cleanup continue to recognize dynamically created worktrees as Azents-owned allocations.

## Fixed Constraints

- Root and descendant Agents share one `SessionAgentContext` and its Project set.
- New worktrees use the current Session working-folder boundary; recorded legacy worktree paths retain their existing behavior.
- Project registry membership alone is not destructive cleanup authority; removal requires matching Azents worktree ownership.
- The source Project is retained when a worktree is created or removed.
- Agent removal preserves the branch even when worktree removal is forced.
- The Agent may autonomously choose explicit force removal without a separate user-approval interaction.
- Existing archive, retention purge, Runtime reset, and terminal Agent/Runtime lifecycle authority remain unchanged unless a later accepted design identifies a required compatibility change.

## Open Assumptions

- The Agent can reliably use the generated worktree path returned by creation for the isolated task even though the source Project remains registered.
- Users accept that an Agent's explicit force removal may irreversibly discard uncommitted content inside a managed worktree.
- Preserved branches provide sufficient recovery for committed work after Agent-requested worktree removal.
- Experience with registered-Project-only sources will determine whether a future snapshot should consider unregistered repositories or broader Project registration authority.

## Confirmation

Confirmed by the requester on 2026-08-12 before ADR and design decisions began.
