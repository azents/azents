---
title: "Manual Orphan Worktree Cleanup Requirements"
created: 2026-07-26
updated: 2026-07-26
tags: [worktree, session, runtime, cleanup]
document_role: primary
document_type: requirements
snapshot_id: worktree-260726
---

# Manual Orphan Worktree Cleanup Requirements

- Snapshot: `worktree-260726`
- Document reference: `worktree-260726/REQ`

## Problem

Worktrees can remain in an Agent Runtime after the Sessions that used them are no
longer active. These accumulated worktrees consume Runtime workspace capacity, but
the product has no user-invoked operation that determines which worktrees are no
longer connected to an active Session and removes them with a visible result.

## Primary Actor

A Workspace member using an active Agent Session.

## Primary Scenario

A Workspace member intentionally invokes an orphan-worktree cleanup action from
an active Session. The action examines the current Agent Runtime, determines which
worktrees under the Azents worktree area are not connected to any active root
Session, force-removes those worktrees even when they contain modified or
untracked files, preserves their local Git branches, and reports the complete
cleanup outcome to the requesting Session.

## Supporting Scenarios

- No orphan worktrees are found, and the action completes successfully with a
  zero-cleanup result.
- Several orphan worktrees are found and all are removed.
- One candidate cannot be removed, but the action continues processing the
  remaining candidates and reports both successful and failed outcomes.
- A worktree becomes connected to active Session work while cleanup is in
  progress and is protected from removal.
- The action is stopped or its worker loses ownership after some worktrees have
  already been removed, and the durable result identifies the partial outcome.

## Goals

- Give users one explicit Session action for finding and removing orphan
  worktrees.
- Restrict each invocation to the current Agent Runtime.
- Protect worktrees connected to active root Sessions.
- Reclaim orphan worktree storage even when orphan contents are modified or
  untracked.
- Make every removal, protection decision, and failure visible to the requester.
- Allow a later invocation to rescan current state and continue cleanup.

## Non-Goals

- Automatic, scheduled, idle-time, or turn-end worktree garbage collection.
- Cleaning worktrees in another Agent Runtime.
- Deleting local Git branches associated with removed worktrees.
- Archiving, restoring, or purging Sessions.
- General cleanup of arbitrary files outside the Azents worktree area.
- Requiring a second confirmation after the user submits the cleanup action.

## Requirements

### REQ-1. Explicit user-invoked cleanup

The product must provide a Turn Action through which a Workspace member
explicitly requests orphan-worktree discovery and deletion.

**Acceptance criteria**

- Submitting the action is the user's authorization to inspect and delete
  qualifying worktrees.
- The action does not run automatically because a Session, Run, or turn becomes
  idle or terminal.
- The action is durably associated with the requesting Session and user
  provenance.
- The user does not need to approve a second confirmation step after submitting
  the action.

### REQ-2. Current-Runtime scope

Each action invocation must operate only on the Agent Runtime associated with the
requesting Session.

**Acceptance criteria**

- The action examines only the Azents worktree area in the current Agent Runtime.
- It does not enumerate, start, restore, or mutate another Agent Runtime.
- Another Runtime's availability or failure cannot affect the action result.

### REQ-3. Active-Session orphan determination

The action must determine orphan status against the current set of non-archived
root Sessions and their connected worktrees.

**Acceptance criteria**

- Archived Sessions are not included in the active Session set.
- A worktree connected to any active root Session is protected from removal,
  including when that active Session is not the requesting Session.
- Worktree creation, registration, or another active connection established
  during the action cannot be removed based only on an earlier observation.
- A worktree under the Azents worktree area that is not connected to active
  Session work is eligible for cleanup.

### REQ-4. Forced worktree removal with branch preservation

The action must remove each orphan worktree even when it contains modified or
untracked contents, while preserving its local Git branch.

**Acceptance criteria**

- Modified and untracked worktree contents do not by themselves prevent removal.
- Removal clears the physical worktree and its Git worktree registration.
- The action does not delete the local branch that was checked out by the
  worktree.
- An existing target whose worktree identity cannot be established is not deleted
  as an arbitrary filesystem directory and is reported as a failure.

### REQ-5. Independent candidate progress and partial failure

Failure to remove one orphan candidate must not prevent attempts for the remaining
candidates.

**Acceptance criteria**

- Candidates are processed independently.
- Successful removals remain completed when a later candidate fails.
- If one or more candidates remain failed, the overall action terminates as
  failed after attempting the remaining candidates.
- Reinvoking the action performs a fresh discovery and can remove candidates that
  remain.

### REQ-6. Durable and visible outcome

The requesting Session must receive a durable, understandable result for the
complete action.

**Acceptance criteria**

- Live progress distinguishes discovery, protected active worktrees, removal
  attempts, successful removals, and failures.
- The terminal result reports the number of worktrees examined, protected,
  removed, already absent, and failed.
- Candidate-level outcomes identify the affected worktree path and a bounded
  reason without exposing worktree file contents or diffs.
- A zero-candidate run completes successfully.
- Cancellation or ownership loss records completed side effects and unresolved
  candidates without claiming that completed removals were rolled back.

## Fixed Constraints

- The active root Session set and its connected worktrees must be evaluated from
  authoritative current product state rather than inferred only from directory
  names.
- Destructive filesystem work remains confined to the Agent Runtime's Azents
  worktree area.
- Git worktree identity is revalidated before destructive removal.
- The action must not hold database row locks across Runtime or Git operations.
- Existing active Session work must not be invalidated by the cleanup action.
- Local branch preservation applies even when the worktree is force-removed.

## Open Assumptions

- The current Agent Runtime is available for the user-invoked cleanup operation.
- Active Session worktree connections are representable through the product's
  authoritative Session workspace state and in-progress worktree operations.
- Reinvocation is an acceptable recovery path for candidates left after
  cancellation or partial failure.

## Confirmation

Confirmed by the requester on 2026-07-26 before ADR and design decisions began.
