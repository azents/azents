---
title: "Archive-Owned Session Worktree Cleanup Requirements"
created: 2026-07-23
updated: 2026-07-23
implemented: 2026-07-23
tags: [session, worktree, archive, retention, reliability]
document_role: primary
document_type: requirements
snapshot_id: worktree-260723
---

# Archive-Owned Session Worktree Cleanup Requirements

- Snapshot: `worktree-260723`
- Document reference: `worktree-260723/REQ`

## Problem

Archived Session trees can remain permanently blocked when retention purge depends
on a user Runtime to inspect or remove Git worktrees. Worktree cleanup is useful
when a Session leaves active use, but its success must not determine whether the
Session can be archived or later removed from the database.

## Primary Actor

A workspace member who archives a Session and expects the archive request to
complete even when its Runtime or Git worktree cannot be cleaned.

## Primary Scenario

A workspace member archives an inactive root Session tree. The Session tree is
committed as archived, the system makes one best-effort attempt to remove its
owned Git worktrees, and the archive remains successful if that attempt fails.
When retention later expires, purge permanently removes the database Session tree
without consulting any Runtime, Git repository, branch, path, or worktree state.

## Supporting Scenarios

- A Runtime is unavailable when archive attempts worktree cleanup.
- A worktree cleanup operation fails after the archive transaction commits.
- A retention purge job created before this change is already retrying at the
  worktree participant.
- A worktree or branch remains physically present after the Session database tree
  is purged.

## Goals

- Make archive the only Session lifecycle point that attempts Git worktree cleanup.
- Keep archive cleanup explicitly best-effort and disposable.
- Make retention purge independent of Runtime and Git worktree availability.
- Allow existing worktree-blocked purge jobs to converge through ordinary retries.

## Non-Goals

- Guaranteeing that every archived worktree or branch is physically removed.
- Retrying failed archive worktree cleanup as retention work.
- Preserving worktree contents for Session restore.
- Repairing existing purge jobs through direct production database mutation.
- Restarting or replacing a user Runtime to unblock Session deletion.

## Requirements

### REQ-1. Archive-owned best-effort cleanup

Archive must be the only Session lifecycle transition that attempts to remove
Session-owned Git worktrees.

**Acceptance criteria**

- The complete Session tree is committed as archived before Git cleanup begins.
- Archive makes at most one automatic root-tree cleanup attempt per successful
  archive request.
- Modified or untracked contents may be force-removed during that attempt.
- Runtime unavailability, Git failure, ownership ambiguity, or any other cleanup
  failure does not roll back the archive or change its successful response.
- Failed cleanup creates no retention retry obligation.

### REQ-2. Database-only retention purge

Retention purge must permanently delete the database Session tree without
consulting or mutating Runtime or Git worktree state.

**Acceptance criteria**

- Purge does not call a Runtime Runner or Runtime provider for worktree inspection,
  removal, branch deletion, or filesystem access.
- Purge does not require worktree allocations to be cleaned or verified.
- Purge removes Session-owned worktree allocation rows through its database
  finalization boundary regardless of their recorded cleanup status.
- Physical worktree or branch state cannot block permanent Session deletion.

### REQ-3. Existing retry-job convergence

Already-materialized purge jobs that contain the existing worktree participant
must converge through the ordinary retry workflow.

**Acceptance criteria**

- Existing participant rows and successful checkpoints are preserved.
- A retry at the worktree cleanup phase advances without Runtime or Git access.
- Downstream participants become unblocked through normal checkpoint progression.
- No direct production database update or one-off repair worker is required.

### REQ-4. Verification and operational visibility

The changed ownership boundary must be deterministic and observable without
turning cleanup failure into user-visible archive failure.

**Acceptance criteria**

- Archive cleanup failures are logged with bounded Session and worktree context.
- Automated tests prove archive success on cleanup failure.
- Automated tests prove purge has no Runtime/worktree collaborator.
- Automated tests prove a previously blocked worktree participant completes on
  its next ordinary retry.
- The lifecycle ownership manifest no longer classifies physical Git worktrees as
  purge-owned external resources.

## Fixed Constraints

- Archive eligibility still rejects active Session trees and active AgentRuns.
- Durable retention purge remains the only permanent Session database deletion
  owner.
- Purge remains lease-fenced, retryable, and isolated per root tree for its other
  required participants.
- Existing worktree participant snapshot keys and policy version values remain
  readable until incomplete jobs have converged.
- Historical implemented Requirements and ADR documents remain unchanged.

## Open Assumptions

- Leaving physical Git data behind after a failed archive cleanup is acceptable
  because no later Session lifecycle stage owns that cleanup.
- The existing finalizer's explicit database deletion order remains authoritative
  for restrictive Session-context foreign keys.

## Confirmation

Confirmed by the requester on 2026-07-23 before ADR and design decisions began.
