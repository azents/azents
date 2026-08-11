---
title: "Optional Managed Runtime for Agents Requirements"
created: 2026-08-03
updated: 2026-08-03
implemented: 2026-08-10
tags: [agent, runtime, workspace, frontend, security]
document_role: primary
document_type: requirements
snapshot_id: runtime-260803
---

# Optional Managed Runtime for Agents Requirements

- Snapshot: `runtime-260803`
- Document reference: `runtime-260803/REQ`

## Problem

Every Agent is currently treated as capable of owning a managed execution environment even when its work only needs model inference, remote tools, memory, or external channels. This makes the cost and authority of a managed Runtime difficult to distinguish from the Agent itself and does not give administrators a clear way to create a lower-cost, lower-authority Agent without a persistent Workspace or code execution capability.

Administrators also need to add or permanently remove that capability later without replacing the Agent or losing its conversations and non-Runtime configuration. The product must make the consequences understandable before an administrator grants execution authority or permanently deletes Workspace data.

## Primary Actor

An Agent administrator who configures an Agent for a Workspace.

## Primary Scenario

An administrator creates a new Agent without a managed Runtime. During creation, the administrator can clearly see which capabilities remain available, which capabilities require a Runtime, and which kinds of Agent normally need one. The Agent can immediately use model inference, supported remote tools, memory, attachments, subagents, and external channels without allocating managed compute or a persistent Agent Workspace.

## Supporting Scenarios

- During Agent creation or later in Agent settings, an administrator explicitly adds a managed Runtime and selects an available Runtime Profile.
- An administrator selects a Runtime-dependent capability on an Agent without a Runtime and is guided through an explicit Runtime addition flow.
- An administrator stops Runtime compute temporarily while preserving the Agent Workspace and Runtime capability.
- An administrator permanently removes an Agent's Runtime, Workspace, Projects, and Git worktrees while preserving the Agent's non-Runtime state.
- After permanent removal, an administrator adds a new Runtime to the same Agent and starts with an empty Workspace.

## Goals

- Let an Agent operate without managed compute, a persistent Agent Workspace, shell execution, or Runtime credential exposure.
- Make Runtime authority opt-in for newly created Agents while keeping Runtime setup easy to complete during Agent creation.
- Explain Runtime capability, cost, security, and data-lifecycle consequences in terms users can evaluate before making a choice.
- Let administrators explicitly add and permanently remove Runtime capability at Agent scope.
- Preserve conversations and other non-Runtime Agent state across Runtime addition and removal.
- Preserve existing Agent behavior when the feature is introduced.

## Non-Goals

- Session-specific or subagent-specific Runtime selection, provisioning, or removal.
- Automatic Runtime addition initiated by a model, tool call, Session, or subagent without administrator confirmation.
- A temporary detach or suspend mode that disables Runtime capability while retaining its Workspace for later reattachment.
- Recovery of a Workspace, Project, or Git worktree after permanent Runtime removal is confirmed and begins.
- Automatic restoration of previous Runtime-only capabilities or credential exposure after a Runtime is added again.
- Changing existing Agents to Runtime-free Agents without an administrator explicitly removing their Runtime.

## Requirements

### REQ-1. Runtime-free Agent creation by default

A newly created Agent must default to having no managed Runtime. The creation flow must keep the Runtime choice visible and make it easy to include a Runtime without making Runtime selection mandatory.

**Acceptance criteria**

- A user can create a functional Agent without selecting a Runtime Profile.
- The initial selection clearly indicates that no Runtime is included.
- The same creation flow provides a direct way to select an available Runtime Profile.
- Existing Workspace defaults do not silently grant Runtime capability to a new Agent that retains the default selection.

### REQ-2. Understandable capability guidance

Before creating or reconfiguring an Agent, an administrator must be able to understand what the Agent can and cannot do without a Runtime and when a Runtime is appropriate.

**Acceptance criteria**

- The creation and settings surfaces distinguish model and remote-tool capabilities from shell, filesystem, persistent Workspace, Project, Git worktree, build, test, and local file-production capabilities.
- The guidance includes representative Runtime-free and Runtime-dependent Agent use cases.
- The guidance explains that a Runtime grants code execution and persistent Workspace authority and may incur compute and storage cost.
- The current Runtime choice and its practical consequences remain visible before the administrator commits the change.

### REQ-3. Functional Runtime-free execution

An Agent without a Runtime must remain usable for every configured capability that does not require a managed execution environment.

**Acceptance criteria**

- The Agent can run model turns and maintain its conversation history without a Runtime.
- Supported memory, Goal, Todo, remote API or MCP tools, provider-hosted tools, external channels, managed Skills, attachments, and subagent collaboration remain available when independently enabled and compatible.
- Runtime-dependent tools and Workspace actions are not offered as usable capabilities.
- A stale or indirect attempt to perform a Runtime-dependent operation fails without provisioning a Runtime or expanding the Agent's authority.

### REQ-4. Explicit guided Runtime addition

Adding Runtime capability must require an explicit administrator choice. Selecting a Runtime-dependent feature on a Runtime-free Agent must guide the administrator through the required Runtime setup rather than silently enabling it.

**Acceptance criteria**

- An administrator can add a Runtime during Agent creation or later from Agent settings.
- Runtime addition requires the administrator to select an available Runtime Profile and confirm the authority change.
- Selecting a Runtime-dependent feature explains why a Runtime is required and offers the Runtime setup flow in context.
- No model, Session, subagent, tool invocation, Workspace default, or compatibility fallback can add a Runtime without that confirmation.

### REQ-5. Lazy Runtime provisioning

Adding Runtime capability must not allocate active compute immediately. The Agent must become Runtime-capable while physical execution resources are created only when a Runtime-dependent operation is first requested.

**Acceptance criteria**

- Immediately after Runtime addition, the Agent is shown as configured but not started.
- No active Runtime compute is required merely to save the Agent setting.
- The first authorized Runtime-dependent operation can initiate normal Runtime startup.
- Runtime startup failure does not remove or replace the administrator's selected Runtime configuration.

### REQ-6. Agent-wide Runtime boundary

Runtime capability must belong to the Agent and apply consistently to all of its Sessions and subagents.

**Acceptance criteria**

- Sessions and subagents cannot independently add, remove, select, or replace a Runtime.
- Runtime addition makes the capability available under the same Agent-wide policy to all compatible Sessions and subagents.
- Runtime removal revokes Runtime-dependent capability from every Session and subagent of that Agent.
- Spawning a subagent cannot expand the parent Agent's Runtime authority.

### REQ-7. Temporary stop remains distinct from permanent removal

Administrators must be able to distinguish temporarily stopping Runtime compute from permanently removing Runtime capability and data.

**Acceptance criteria**

- Stopping a Runtime preserves its Workspace and keeps the Agent Runtime-capable.
- A stopped Runtime may start again through the normal authorized Runtime-use flow.
- Removing a Runtime is presented as a separate destructive action.
- The initial feature does not offer a temporary detach or suspend action that preserves Workspace data while removing Runtime capability.

### REQ-8. Safe permanent Runtime removal

An administrator must be able to permanently remove an Agent's Runtime through an explicit destructive flow that stops active work, prevents new Runtime use, deletes Runtime-owned resources, and does not report completion until deletion is authoritatively verified.

**Acceptance criteria**

- The confirmation identifies that the Agent Workspace, registered Projects, Git worktrees, running processes, and other Runtime-owned state will be permanently deleted.
- The confirmation identifies that conversations, Memory, general Agent settings, compatible Toolkit connections, external channels, Exchange attachments, model files, and artifacts are retained.
- The flow reports the active Sessions and subagents whose work will be interrupted.
- Confirming removal immediately prevents new Agent work and Runtime operations, then stops active Sessions, subagents, Runs, and processes before destructive deletion proceeds.
- Removal remains visibly pending while authoritative deletion confirmation is unavailable, including during an infrastructure-provider outage.
- Repeated deletion attempts are safe, and already-absent Runtime resources can be confirmed as successfully removed.
- A pending or ambiguous deletion cannot be treated as success, cannot expose the old Workspace, and cannot allow a replacement Runtime to be added concurrently.

### REQ-9. Fresh and explicit Runtime re-addition

After permanent removal completes, an administrator must be able to add a Runtime to the same Agent without restoring deleted Workspace data or silently restoring previous Runtime-only authority.

**Acceptance criteria**

- The Agent retains its identity, conversations, Memory, compatible Toolkit connections, and non-Runtime settings after removal.
- A later Runtime addition starts with an empty Workspace.
- Deleted Project and Git worktree registrations are not restored.
- Shell access and Runtime credential injection that were disabled by removal do not reactivate automatically.
- The administrator must explicitly enable sensitive Runtime-only capabilities and credential exposure again.

### REQ-10. Existing Agent compatibility

Introducing optional Runtime capability must preserve the behavior and authority of existing Agents until an administrator explicitly changes them.

**Acceptance criteria**

- Every Agent created before rollout remains Runtime-capable after migration, including an Agent whose Runtime Profile is not currently configured.
- Existing Agent Runtime selections, Workspace data, and Runtime-dependent configuration are not removed or downgraded by rollout.
- New Agents created after rollout use the Runtime-free default.
- An existing Agent becomes Runtime-free only through the same explicit permanent removal flow.

## Fixed Constraints

- Runtime addition and removal use the existing Agent settings authorization boundary; a Session participant or model cannot grant or revoke Runtime authority.
- Runtime absence is not a read-only guarantee for remote systems. Independently authorized remote tools may still perform mutations.
- Permanent removal must not depend on Redis availability or retention for correctness.
- Runtime removal must not delete Agent conversation history, Memory, retained product files, compatible Toolkit connections, or external-channel configuration.
- Runtime-owned Workspace data cannot be promised recoverable after destructive deletion begins.
- Existing implemented Agent, Session, subagent, and Runtime ownership boundaries remain authoritative unless a later confirmed requirement explicitly changes them.

## Open Assumptions

- Runtime-free Agents use the existing model execution, durable transcript, run recovery, and server-executed Toolkit paths rather than a second Agent execution product.
- A Toolkit that has both remote and Runtime-specific capabilities can retain its compatible remote capability while its Runtime-specific projection remains unavailable.
- Product copy will use user-facing terms that distinguish the Agent execution loop from the optional managed Runtime and Agent Workspace.

## Confirmation

Confirmed by the requester on 2026-08-03 before ADR and design decisions began.
