---
title: "Session Working Folder"
created: 2026-08-03
tags: [architecture, session, workspace, filesystem, project-browser, lifecycle]
document_role: primary
document_type: adr
snapshot_id: session-260803
---

# session-260803/ADR: Session Working Folder

## Context

The confirmed [session-260803/REQ](../requirements/session-260803-session-working-folder.md) introduces one disposable working folder for each root Session tree. The folder is shared through the existing `SessionAgentContext`, preferred for non-Project work, shown permanently in Projects mode, and cleaned once after archive commits. Cross-Session Agent Workspace files, registered Projects outside the folder, and legacy worktrees retain their existing locations and lifecycles.

Current root Session creation persists `AgentSession`, root `SessionAgent`, `SessionAgentContext`, and initial Project rows without Runtime I/O. Runtime shell commands currently default to the Agent Workspace root when no working directory is supplied. Project Browser manifests are database projections containing only registered or preview Project entries. Archive already commits the Session tree before making one best-effort worktree cleanup call, while retention purge is database-only.

The design must add explicit Session-folder ownership without making Runtime availability a Session-creation prerequisite, treating a Project registration as deletion authority, moving legacy worktrees, or reintroducing filesystem work into retention purge.

## Decision Map

- **D1 — Accepted:** store the exact Session working-folder path and cleanup state directly on `SessionAgentContext`.
- **D2 — Accepted:** expose a fixed Session-folder system entry while retaining registered worktrees as separate Project roots.
- **D3 — Accepted:** recursively delete the exact Session folder even when prior Git worktree cleanup fails.
- **D4 — Accepted:** use a separate non-blocking setup TurnAction for best-effort folder materialization.

## Decisions

### session-260803/ADR-D1 — SessionAgentContext is the working-folder ownership record

`SessionAgentContext` stores the exact absolute Session working-folder path together with its bounded cleanup status, cleanup summary, and cleanup timestamp. The path is assigned as part of root Session context creation without Runtime I/O and is never reconstructed during cleanup from the current naming convention. The root SessionAgent tree shares this one context-owned folder and lifecycle.

This decision applies to session-260803/REQ-1, REQ-2, REQ-5, REQ-6, and REQ-7.

A separate one-to-one allocation table is rejected because the working folder has the same owner and lifetime as `SessionAgentContext`, only one working folder exists per context, and no family of independently managed Session filesystem allocations is planned. Keeping the fields on the context avoids an additional persistence abstraction without weakening explicit ownership.

Deriving the cleanup path from a Session handle, context ID, or current path convention is rejected. Prefix containment remains a safety check, but destructive cleanup authority comes from the exact stored context path.

The main risk is that future independently managed Session filesystem resources could make the context model too broad. Such a future capability must introduce its own ownership model rather than silently reusing the working-folder fields.

### session-260803/ADR-D2 — Projects mode exposes both the Session folder and registered worktree roots

The existing-session Project Browser manifest adds a backend-owned `session_folder` source entry for the exact context-owned working-folder path. This fixed system entry is ordered before registered Project entries, is not backed by a Project registry row, and cannot be removed, renamed, moved, or directly deleted. Its descendants retain their ordinary authorized file operations.

Registered Projects keep their existing independent root entries and semantics. An Azents-created worktree inside the Session folder therefore appears both within the truthful Session-folder filesystem tree and as a separate top-level Git Project. The top-level Project entry remains the Project-scoped instruction, Skill, Git metadata, registry removal, and explicit worktree-cleanup boundary.

This decision applies to session-260803/REQ-3 and REQ-6.

Filtering registered Project subtrees out of the Session-folder tree is rejected because it would make Projects mode present a filesystem view that omits physically present children and behaves inconsistently with All-files mode. Treating the Session folder as a registered Project is rejected because general Session outputs must not inherit Project-scoped instructions, registry actions, or Project lifecycle semantics.

The intentional duplicate path is a representation of two distinct navigation scopes rather than duplicated storage. Compact source labeling may clarify the distinction without hiding either entry.

### session-260803/ADR-D3 — Physical Session-folder deletion proceeds after Git cleanup failures

Archive cleanup makes one existing typed Git cleanup attempt for every Azents-owned worktree associated with the root Session tree. Regardless of an individual Git cleanup outcome, cleanup then makes one recursive deletion attempt for the exact Session working-folder path stored on `SessionAgentContext`. A Git cleanup failure therefore does not preserve the enclosing Session folder or its remaining contents.

The cleanup does not add a post-deletion Git prune, branch-repair retry loop, selective subtree deletion pass, or later purge retry. Git cleanup and Session-folder deletion remain bounded parts of the one archive-owned best-effort attempt.

This decision applies to session-260803/REQ-5, REQ-6, and REQ-7.

Stopping recursive deletion after any worktree failure is rejected because the existing stop-after-failure behavior bounded further deletion attempts; it was not an ownership or containment safety boundary. The new exact context-owned folder path authorizes one bounded recursive deletion attempt without expanding cleanup to unrelated paths. Selectively preserving only failed worktree subtrees is rejected because exclusion-based recursive deletion creates an additional deletion pass and a more complex partial filesystem state.

This choice keeps deletion attempts bounded while prioritizing removal of Session-owned physical data. A source repository may retain stale worktree registration or an Azents-created branch when its one Git cleanup attempt fails. That residue is observable cleanup degradation but does not make the archived Session folder recoverable and does not block archive or purge.

### session-260803/ADR-D4 — A separate non-blocking setup TurnAction materializes the folder

Introduce a system-authored `create_session_working_folder` TurnAction. Root Session creation records the exact context-owned path and enqueues this action before requested worktree setup actions and the first user message. For an otherwise empty Session the action uses queue-only scheduling and does not wake the Session or start its Runtime solely to create a directory. A later wake caused by user input, worktree setup, or an explicit Project-browser retry processes the FIFO action first.

The action resolves the current Session's shared `SessionAgentContext`, reads the stored path, and idempotently creates the directory through the Runtime Runner. It never accepts a client-selected target path. Existing-directory success and first creation both terminalize successfully.

Action failure records the ordinary terminal action result and does not block later setup actions, user input, model dispatch, or Runtime tools. Runtime instructions provide the exact path and direct the Agent to create it explicitly from the Agent Workspace root when it is absent. Runtime operations do not add an automatic Session-folder preflight after the setup action; the folder may therefore remain absent until a later setup retry or Agent-created repair.

Project Browser always projects the context path even when the physical directory is absent. An explicit prepare/retry interaction may enqueue the same idempotent TurnAction and wake the Session. Runtime reset and archived-Session restore may queue a fresh non-waking setup action for affected active contexts.

This decision applies to session-260803/REQ-1, REQ-2, REQ-3, and REQ-7.

Implicit materialization before every Runtime operation is rejected because it adds a hidden preflight to unrelated shell and file operations. A mandatory worker prerequisite is rejected because it would start or require Runtime availability for Sessions that do not use filesystem capabilities and would make setup failure an execution-admission gate contrary to the confirmed requirements. Folding materialization into `create_git_worktree` is rejected because Sessions without worktrees still need the working-folder contract.

The accepted trade-off is that the first default-workdir command can fail when setup did not create the directory. Prompt-guided repair uses an explicit Agent Workspace workdir to create the exact stored path, after which ordinary tools use it normally.

## Fixed and Derived Outcomes

- One root `SessionAgentContext` owns one Session working-folder lifetime shared by its complete SessionAgent tree.
- Root Session creation remains database-only; physical directory materialization cannot be a creation prerequisite.
- The exact Session path is available to runtime instructions, command defaults, Project Browser projection, and archive cleanup.
- Archive commits before one best-effort cleanup attempt, and cleanup failure cannot change archive success.
- Retention purge performs no Runtime, Git, or filesystem operation.
- Legacy worktrees remain at their recorded paths.
- Symlink cleanup never follows a target outside the owned Session folder.
- The Session-folder root is protected from ordinary remove, rename, move, and delete actions.

## Agent-Owned Details

The implementation may choose local identifiers, helper and module boundaries, internal subdirectory names, API field names, status enum names, log field names, UI iconography and compact utility copy, and fixture composition as long as those choices introduce no additional lifecycle, ownership, persistence, compatibility, or user-visible mode.
