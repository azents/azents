---
title: "Agent Default Projects for Automatic Sessions Requirements"
created: 2026-07-24
updated: 2026-07-24
tags: [agent, session, workspace, project]
document_role: primary
document_type: requirements
snapshot_id: agent-260724
---

# Agent Default Projects for Automatic Sessions Requirements

- Snapshot: `agent-260724`
- Document reference: `agent-260724/REQ`

## Problem

An Agent can have root Sessions created without a person going through an explicit new-Session workspace selection flow. These Sessions currently start without Projects even when the Agent consistently needs access to an established set of existing Projects. External-channel participants generally do not use Azents directly or understand its Project model, and other automatic Session creation paths likewise provide no opportunity to choose workspace items.

## Primary Actor

An Agent administrator who manages the Agent's default working context.

## Primary Scenario

An Agent administrator defines multiple existing Projects as the Agent's defaults. Later, the system creates a new root AgentSession without an explicit workspace selection, such as an External Channel Session or a newly ensured team-primary Session. The new Session starts with a snapshot of the Agent's configured default Projects, and subsequent activity in that Session continues to use the same Project set without requiring the invoking participant to understand or select Projects.

## Supporting Scenarios

- A user or API client explicitly creates a root Session with a workspace selection; that explicit selection is used without hidden defaults.
- An Agent has no configured default Projects; an automatically created root Session retains the current empty-Project behavior.
- An administrator changes the Agent defaults; existing Sessions retain their current Projects while later automatically created root Sessions use the new defaults.
- A subagent Session is created under an existing root Session; it continues to share the root SessionAgentContext instead of applying the Agent defaults again.

## Goals

- Let administrators define a stable Agent-level set of existing Projects for automatically created root Sessions.
- Give automatically created root Sessions the working context they need without requiring the invoking participant to visit Azents or understand Projects.
- Preserve exact caller intent for explicitly created Sessions.
- Make the behavior reusable across current and future automatic root Session creation sources rather than coupling it to one External Channel provider.

## Non-Goals

- Letting an Agent discover, choose, or register Projects dynamically from a request.
- Automatically creating Git worktrees, branches, or per-Session filesystem isolation.
- Providing channel-, connection-, participant-, or provider-specific Project mappings.
- Retrofactively changing the Projects of an existing Session when Agent defaults change.
- Preventing concurrent Sessions from modifying the same existing Project.
- Changing subagent Project ownership or giving subagents independent workspace defaults.

## Requirements

### REQ-1. Agent-level default Project configuration

An Agent administrator can configure zero or more existing Projects as the Agent's defaults for automatic root Session creation.

**Acceptance criteria**

- The administrator can save multiple existing Projects for one Agent.
- The saved configuration belongs to the Agent rather than to an External Channel connection, provider, channel, participant, or individual Session.
- Configuring no default Projects is valid.

### REQ-2. Application to automatic root Sessions

When the system creates a new root AgentSession without an explicit workspace selection, the Session receives the Agent's currently configured default Projects.

**Acceptance criteria**

- A newly created External Channel root Session receives the configured defaults.
- A newly created team-primary root Session receives the configured defaults.
- Future automatic root Session producers can use the same behavior without introducing provider-specific Project configuration.
- Each configured Project is available in the new root Session's shared SessionAgentContext.

### REQ-3. Explicit workspace selection takes precedence

A root Session created with an explicit workspace selection uses exactly that selection instead of the Agent defaults.

**Acceptance criteria**

- Explicitly supplied existing Projects are not combined with hidden Agent defaults.
- An explicitly supplied empty workspace selection produces a Session with no Projects.
- Existing Web and Public API new-Session behavior remains explicit and predictable.

### REQ-4. Creation-time snapshot behavior

A root Session's default Project set is determined when that Session is created and does not track later Agent configuration changes.

**Acceptance criteria**

- Changing Agent defaults affects only root Sessions created afterward.
- Existing External Channel bindings continue to use their existing AgentSession and Project set.
- Existing team-primary and other root Sessions are not modified when defaults change.

### REQ-5. Empty-default compatibility

An Agent without configured defaults preserves the current behavior of automatically created root Sessions.

**Acceptance criteria**

- Automatic root Session creation remains available when the Agent has no defaults.
- The created Session has no registered Projects unless another explicit creation input supplies them.
- Missing defaults do not block, delay, or require clarification from an External Channel participant.

### REQ-6. Subagent context inheritance

Creating a subagent Session does not independently apply the Agent defaults.

**Acceptance criteria**

- A subagent continues to share its root SessionAgentContext and registered Projects.
- No duplicate Project registration is produced by subagent creation.
- The behavior applies only at root Session context creation boundaries.

### REQ-7. Existing-Project-only scope

The defaults in this snapshot provide existing Projects without automatically provisioning isolated workspaces.

**Acceptance criteria**

- Applying Agent defaults does not create a Git worktree or branch.
- Sessions may perform the same reads and modifications allowed for an explicitly selected existing Project.
- Dynamic Project registration and automatic worktree creation remain available for a separate future requirements and design effort.

## Fixed Constraints

- External Channel participants are not required to be Azents Users or WorkspaceUsers and must not be asked to configure or select Projects.
- Workspace membership and Agent administration remain the authorization boundary for changing Agent configuration.
- Project authority follows the root SessionAgentContext; subagent Sessions share that context.
- Existing explicit new-Session contracts must not gain hidden Project inheritance.
- The feature must not infer applicability solely from whether a request originated in Web UI or from the current `start_reason` value; explicit workspace intent and root context creation are the product boundary.

## Open Assumptions

- The exact management surface and API shape for editing Agent defaults will be decided in the design.
- The current automatic root Session producers are External Channel creation and team-primary ensure; future producers will explicitly adopt the same creation contract.
- Project validation and unavailable-path behavior will reuse or strengthen existing Project selection semantics without changing the requirements above.

## Confirmation

Confirmed by the requester on 2026-07-24 before ADR and design decisions began.
