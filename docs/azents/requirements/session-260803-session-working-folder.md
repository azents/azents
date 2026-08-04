---
title: "Session Working Folder Requirements"
created: 2026-08-03
updated: 2026-08-03
implemented: 2026-08-04
tags: [session, workspace, filesystem, project-browser, lifecycle]
document_role: primary
document_type: requirements
snapshot_id: session-260803
---

# Session Working Folder Requirements

- Snapshot: `session-260803`
- Document reference: `session-260803/REQ`

## Problem

The Agent Workspace is shared across Sessions, while Azents-created Git worktrees are currently organized under a worktree-specific Session path. Agents have no general Session-owned location for ordinary outputs, downloads, transformations, and other working files, so files can become scattered in shared Agent Workspace storage and their intended lifetime is unclear.

Users need a clear distinction between disposable Session work and files intentionally retained across Sessions. They also need to see and browse the current Session's working files alongside registered Projects and to archive a Session without leaving Session-owned content as an ongoing lifecycle obligation.

## Primary Actor

A workspace member who works with an Agent in a root Session, reviews its files and Projects, preserves selected outputs when needed, and later archives the Session.

## Primary Scenario

A workspace member starts or opens a root Session. The root Session and all of its subagents share a dedicated working folder. Commands and Agent guidance prefer that folder for work that does not belong to a registered Project, and the folder is always visible in the Projects browser. The member may move or create files in the shared Agent Workspace when they should survive the Session. After the Session tree is successfully archived, Azents makes one best-effort attempt to remove the Session folder and all of its contents without making archive success depend on cleanup success.

## Supporting Scenarios

- The Agent edits source files inside a registered Project instead of placing those changes in the Session folder.
- The Agent creates downloads, generated reports, converted files, and temporary working data in the Session folder without registering each item.
- The user deliberately stores an output outside the Session folder so it remains available to later Sessions using the same Agent Runtime.
- The Session folder contains one or more Azents-created Git worktrees.
- Archive cleanup encounters an unavailable Runtime, Git failure, filesystem failure, or symlink.
- Initial Session-folder setup fails before the Agent begins ordinary Session work.
- An active Session predates this capability and has a worktree at the legacy managed-worktree path.

## Goals

- Give every root Session tree one obvious, shared, disposable working location.
- Make the Session folder the default location for non-Project Agent work.
- Make Session-owned files continuously discoverable from the Projects browser.
- Distinguish Session-lifetime storage from cross-Session Agent Workspace storage and short-lived Runtime scratch storage.
- Remove Session-owned filesystem content on archive without coupling archive or retention purge success to filesystem availability.
- Preserve existing registered Projects and legacy worktree paths without migration.

## Non-Goals

- Treating the Session folder as durable backup or archival storage.
- Guaranteeing that every archived Session folder is physically removed.
- Retrying failed Session-folder cleanup during retention purge.
- Moving existing worktrees from their recorded legacy paths.
- Deleting user-managed registered Projects or other files outside the owned Session folder.
- Changing the lifecycle of the Agent Workspace itself, including explicit Runtime reset or terminal Agent/Runtime deletion.

## Requirements

### REQ-1. Dedicated root-Session working folder

Every root Session tree must have one dedicated working folder inside its Agent Workspace. The root Session and all descendant subagents must use the same folder.

**Acceptance criteria**

- An active root Session has one stable working-folder path for its lifetime.
- Root and descendant SessionAgents receive the same working-folder path.
- Different root Session trees do not share a working folder.
- The stable path may be visible before its physical directory has been created.
- The folder may contain arbitrary unregistered files and directories created by the Agent or user.
- Everything inside the folder is treated as disposable Session-owned data.

### REQ-2. Preferred and default Agent working location

Agent instructions and command execution defaults must direct non-Project work to the current Session working folder.

**Acceptance criteria**

- Runtime instructions include the current Session folder's exact absolute path and its Session-lifetime semantics.
- A command executed without an explicit working directory starts in the current Session folder.
- Runtime instructions tell the Agent to create the exact Session folder before use when it is absent.
- Failure of the automatic folder-setup attempt does not block later setup actions, user input, or model dispatch.
- Instructions direct Project-specific work to the applicable registered Project path.
- Instructions direct files that should survive Session archive to cross-Session Agent Workspace storage.
- Instructions retain short-lived Runtime scratch as a separate storage category.

### REQ-3. Always-visible Projects browser entry

The current Session working folder must always be visible and browsable in the Projects browser, independently of registered Projects.

**Acceptance criteria**

- Projects mode includes the Session folder even when the Session has no registered Projects.
- The entry is visibly distinguishable from user-registered Projects and Git worktrees.
- The entry remains visible when the physical directory is not yet present or automatic setup failed.
- Users can expand the entry and perform ordinary supported file operations on its contents.
- The Session-folder root cannot be removed from the Session, renamed, moved, or directly deleted through ordinary Project or file actions.
- The entry communicates that its contents are removed when the Session is archived.
- All-files mode continues to expose the Agent Workspace filesystem independently of the Projects-mode entry.

### REQ-4. Clear storage lifetime guidance

The product must distinguish Session-lifetime storage, cross-Session Agent Workspace storage, registered Project storage, and Runtime scratch storage.

**Acceptance criteria**

- The Session folder is described as the preferred location for ordinary Session work and as disposable on archive.
- `/workspace/agent/` is described as storage for files intentionally retained across Sessions in the same Agent Runtime.
- `/workspace/agent/` is not represented as surviving explicit Runtime reset or terminal Agent/Runtime deletion.
- Registered Project paths are described as the location for work belonging to those Projects.
- `/tmp/` is described as short-lived Runtime scratch that may be lost independently of Session archive.

### REQ-5. Archive-owned best-effort folder cleanup

A successful root-Session archive must trigger one best-effort cleanup attempt for the Session working folder after the archive state is committed.

**Acceptance criteria**

- Archive commits the complete Session tree as archived before filesystem cleanup begins.
- One successful archive request makes at most one automatic Session-folder cleanup attempt.
- Cleanup failure does not roll back archive or change its successful result.
- Restore does not recreate files or worktrees removed by archive cleanup.
- Retention purge does not access Runtime, Git, or filesystem state and does not retry failed folder cleanup.
- Cleanup failures are recorded or logged with bounded Session context for operational diagnosis.

### REQ-6. Whole-folder ownership with safe external boundaries

Archive cleanup must remove all content owned inside the Session folder without deleting filesystem targets or Projects outside that boundary.

**Acceptance criteria**

- Unregistered files and directories inside the Session folder require no individual ownership records to be deleted.
- Symlink entries inside the Session folder are removed without following them to external targets.
- Registered Projects and other Agent Workspace files outside the Session folder remain untouched.
- Azents-created Git worktrees receive the required Git cleanup before the remaining Session folder is recursively removed.
- A Git or filesystem cleanup failure remains best-effort and does not expand deletion outside the recorded Session-folder boundary.

### REQ-7. Forward-only adoption without legacy worktree migration

Existing worktrees must remain at their recorded paths, while newly created Session-owned work uses the new Session working-folder model.

**Acceptance criteria**

- Deployment does not move or rewrite an existing worktree path.
- Existing worktree allocations continue to use their recorded paths for access and cleanup.
- Existing worktrees remain visible as their currently registered Projects.
- New worktrees created after adoption use the current root Session's working-folder boundary.
- Archive cleanup can handle both the new Session folder and any recorded legacy worktree allocations owned by the archived Session tree.

## Fixed Constraints

- Project registration remains a scope and browser boundary; it does not by itself authorize filesystem deletion.
- Root and descendant SessionAgents share one `SessionAgentContext` and one Session working-folder lifetime.
- Session-folder materialization is best-effort setup and is not an execution-admission prerequisite.
- Archive eligibility continues to reject active Session trees and active AgentRuns.
- Retention purge remains database-only for Session-owned filesystem resources.
- Explicit Runtime reset and terminal Agent/Runtime deletion retain their existing authority over Agent Workspace data.
- Existing implemented Requirements and ADR documents remain immutable.

## Open Assumptions

- Users accept that content left in the Session folder is disposable and may be irrecoverable immediately after archive.
- Users who need longer retention can copy or move selected outputs to cross-Session Agent Workspace storage before archive.
- A failed best-effort archive cleanup may leave physical Session data behind with no later automatic Session-lifecycle retry.

## Confirmation

Confirmed by the requester on 2026-08-03 before ADR and design decisions began.
