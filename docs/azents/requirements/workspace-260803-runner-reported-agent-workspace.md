---
title: "Runner-Reported Agent Workspace Requirements"
created: 2026-08-03
implemented: 2026-08-03
tags: [runtime, workspace, runner, provider, backend]
document_role: primary
document_type: requirements
snapshot_id: workspace-260803
---

# Runner-Reported Agent Workspace Requirements

- Snapshot: `workspace-260803`
- Document reference: `workspace-260803/REQ`

## Problem

Azents currently behaves as though every Agent Workspace is located at one
platform-known absolute path. This prevents Runtime implementations from choosing
another home directory and causes server validation, discovery, prompts, and file
boundaries to disagree with the actual Runtime filesystem.

## Primary Actor

A Runtime integrator operating an Agent Runtime whose durable home directory is
not the platform's historical default path.

## Primary Scenario

A Runtime Runner starts with a configured home directory, reports that absolute
path to Runtime Control, and every Agent Workspace feature uses the reported path
without requiring a platform-wide path constant.

## Supporting Scenarios

- A Runner receives an explicit workspace path instead of relying on its process
  environment.
- Static tool guidance explains Agent Workspace usage without embedding one
  deployment-specific absolute path.
- A Runtime reports a different valid Agent Workspace path after recreation and
  the server treats the latest current-generation Runner report as authoritative.

## Goals

- Make Agent Workspace location Runtime-specific.
- Make the connected Runner the authority for its Agent Workspace absolute path.
- Remove product behavior that assumes one concrete home directory.

## Non-Goals

- Changing Agent Workspace persistence, reset, or terminal-deletion semantics.
- Supporting multiple Agent Workspace roots for one connected Runner.
- Translating or retaining Project paths that fall outside a newly reported root.
- Changing organization-level Workspace naming or API route names.

## Requirements

### REQ-1. Runtime-specific Agent Workspace path

Agent Workspace location must not be a platform-wide fixed path.

**Acceptance criteria**

- A Runtime using a non-default absolute home directory can reach `READY`.
- Workspace browsing, Project validation, generated worktrees, instruction and
  Skill discovery, and durable file publication operate under that directory.

### REQ-2. Runner-reported authority

The connected current-generation Runner report is the authoritative source for the
Agent Workspace absolute path stored and consumed by Azents.

**Acceptance criteria**

- Provider lifecycle metadata is not required to supply or approve the path.
- A current Runner report updates `agent_runtimes.workspace_path`.
- Missing or invalid Runner path evidence prevents Runner readiness.

### REQ-3. Runner path resolution

The Runner must resolve its Agent Workspace from an explicit startup value when
provided and otherwise from `HOME`.

**Acceptance criteria**

- Explicit startup input takes precedence over `HOME`.
- An absent, empty, or non-absolute resolved path stops Runner startup with a
  clear error.
- The resolved normalized absolute path is used for relative operations and
  reported through Runtime Control.

### REQ-4. No fixed path in product consumers

Product behavior must use the Runner-reported path or avoid naming a concrete home
directory.

**Acceptance criteria**

- Server path normalization receives the current Agent Workspace root explicitly.
- Static tool schemas and static prompts contain no deployment-specific Agent
  Workspace absolute path.
- Runtime-generated guidance may display the exact current Runner-reported path.

### REQ-5. No compatibility fallback

Azents must not silently fall back to a historical Agent Workspace path when
Runner evidence is unavailable or when stored paths fall outside the current root.

**Acceptance criteria**

- Missing Runner workspace evidence is surfaced as unavailable or failed.
- Existing Project and worktree paths outside the current reported root are
  rejected or reported unavailable rather than rewritten.

### REQ-6. Regression coverage

Automated tests must prove that Agent Workspace behavior is independent of the
historical default path.

**Acceptance criteria**

- Runner, Control, Provider, workspace, Project, worktree, Skill, instruction, and
  file-publication tests use at least one alternate root.
- Repository checks prevent production code from reintroducing the historical path
  as an Agent Workspace constant.

## Fixed Constraints

- Existing implemented Requirements and ADRs remain immutable.
- The existing `agent_runtimes.workspace_path` column and Runner Control
  `workspace_path` field remain the storage and transport surfaces.
- Provider infrastructure continues to own durable volume lifecycle and mount
  configuration, but not the reported Agent Workspace metadata authority.
- Generated public API clients are not committed as part of this change.

## Open Assumptions

- A Provider that configures a Runner mount also configures the Runner process
  environment or explicit startup input consistently with that mount.

## Confirmation

Confirmed by the requester on 2026-08-03 before ADR and design decisions began.
