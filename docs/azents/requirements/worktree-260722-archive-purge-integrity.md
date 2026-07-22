---
title: "Session Worktree Archive and Purge Integrity Requirements"
created: 2026-07-22
updated: 2026-07-22
implemented: 2026-07-22
tags: [session, worktree, archive, retention, reliability]
document_role: primary
document_type: requirements
snapshot_id: worktree-260722
---

# Session Worktree Archive and Purge Integrity Requirements

- Snapshot: `worktree-260722`
- Document reference: `worktree-260722/REQ`

## Problem

Session archive preserves owned Git worktrees so the session can be restored, while
retention purge must later remove those worktrees before permanently deleting the
session tree. If archive accepts a worktree allocation whose ownership or future
cleanup target cannot be established, or purge treats an already-absent worktree as
an unrecoverable failure, expired sessions can remain indefinitely in retry state.
Conversely, archive must not reject an otherwise valid session merely because its
preserved worktree contains modified or untracked files.

## Primary Actor

A workspace member who archives a session and expects it to remain restorable until
its retention deadline, then be permanently removed without manual operator repair.

## Primary Scenario

A workspace member archives a root session tree that owns one or more Git worktrees,
including a worktree with modified or untracked files. Archive validates that every
allocation remains safely owned and addressable for later lifecycle handling,
preserves the worktrees without destructive cleanup, and completes atomically. If
the session is not restored before its retention deadline, purge safely resolves
each owned worktree to a terminal cleanup outcome and permanently deletes the
session tree without requiring user or operator intervention.

## Supporting Scenarios

- An allocation refers to a worktree that is no longer registered or physically
  present, and purge converges without treating confirmed absence as a permanent
  failure.
- An allocation points to an existing path whose ownership cannot be proven, and
  the system refuses to delete the ambiguous path while retaining actionable retry
  state.
- Purge jobs already retrying because of prior worktree cleanup classification
  automatically resume and converge after the corrected behavior is deployed.
- One root's worktree failure does not prevent unrelated eligible roots from being
  purged.

## Goals

- Preserve archive and restore as reversible lifecycle operations.
- Prevent archive from creating a root-tree state that cannot be safely handled by
  later retention purge.
- Make worktree cleanup deterministic and idempotent across retries.
- Permanently remove expired session-owned worktrees, including preserved local
  changes, before final session deletion.
- Automatically recover existing retrying purge jobs without direct production
  database mutation.
- Keep ambiguous or unowned filesystem paths protected from deletion.

## Non-Goals

- Deleting or force-cleaning worktrees during archive or restore.
- Rejecting archive solely because a worktree contains modified or untracked files.
- Preserving expired worktree contents beyond the owning session's retention
  deadline.
- Adding a user-facing immediate permanent-delete operation.
- Allowing session deletion to bypass required worktree cleanup and verification.
- Deleting an arbitrary filesystem path whose session ownership cannot be proven.

## Requirements

### REQ-1. Reversible archive with preserved worktree contents

Archive must preserve every session-owned worktree and its current contents,
including modified or untracked files.

**Acceptance criteria**

- Archive does not perform destructive worktree or branch cleanup.
- Modified or untracked worktree contents alone do not cause archive to fail.
- A successfully archived session remains restorable with its preserved worktree
  ownership and contents until purge fencing begins.

### REQ-2. Archive-time worktree lifecycle integrity

Archive must atomically reject a root tree when the system cannot establish that an
owned worktree allocation is safely associated with the root and remains
addressable for later lifecycle handling.

**Acceptance criteria**

- Ownership, root-tree membership, and cleanup-target integrity failures prevent the
  complete archive transition.
- A rejected archive leaves the complete root tree active and does not partially
  mutate worktree lifecycle state.
- The failure identifies the affected worktree allocation and an actionable reason
  without exposing unrelated filesystem content.
- Archive does not reject a worktree whose only exceptional state is preserved
  local modification.

### REQ-3. Deterministic retention-purge cleanup

Retention purge must resolve every owned worktree to a verified terminal cleanup
outcome before permanently deleting the session tree.

**Acceptance criteria**

- A registered owned worktree is removed during permanent purge, including when
  preserved local changes require irreversible cleanup.
- A worktree proven already absent does not remain in retry state and is recorded as
  successfully cleaned.
- Azents-owned branch cleanup remains part of the required terminal outcome.
- Repeating cleanup after interruption converges without duplicating destructive
  side effects.
- Final session deletion occurs only after every owned allocation is terminal and
  verified.

### REQ-4. Ambiguous-path safety

The system must not delete an existing filesystem path when session ownership of
that path cannot be proven.

**Acceptance criteria**

- An unregistered or inconsistent existing path is not treated as already absent.
- Ambiguous ownership retains the allocation and session metadata required for
  diagnosis and retry.
- Failure state distinguishes confirmed absence, preserved local modifications, and
  ambiguous ownership.
- Operators receive a bounded, actionable reason without session-content leakage.

### REQ-5. Existing retry-job convergence

Existing retention purge jobs blocked only by prior worktree cleanup classification
must automatically resume through the ordinary durable retry workflow.

**Acceptance criteria**

- Deployment does not require direct production database updates to reactivate
  eligible retry jobs.
- Existing participant progress and successful cleanup checkpoints are preserved.
- Jobs with confirmed absent worktrees advance without manual repair.
- Jobs with owned modified worktrees complete the required permanent cleanup at
  retention expiry.
- Jobs with genuinely ambiguous paths remain safely retryable and observable.

### REQ-6. Verification and operational visibility

Worktree archive validation and purge cleanup outcomes must be covered by
deterministic automated tests and observable in durable lifecycle state.

**Acceptance criteria**

- Tests cover registered clean, registered modified, registered-but-physically
  absent, unregistered-and-absent, and unregistered-but-existing targets.
- Tests verify archive atomicity and the absence of destructive archive behavior.
- Tests verify retry convergence and cleanup-before-delete ordering.
- Durable failure and progress state identifies the worktree lifecycle stage and
  terminal classification.

## Fixed Constraints

- Archive and restore remain reversible database lifecycle transitions.
- Destructive external-resource cleanup occurs only during permanent retention
  purge.
- Durable retention purge remains the only permanent Session deletion owner.
- Worktree cleanup and verification complete before SessionAgentContext and
  AgentSession finalization.
- Filesystem deletion requires authoritative Azents ownership evidence and remains
  restricted to the Agent Workspace boundary.
- Purge remains retryable, idempotent, lease-fenced, and isolated per root job.
- Existing successful participant checkpoints are not reset to repair one failed
  worktree participant.
- No backward-compatibility fallback or parallel legacy cleanup path is required.

## Open Assumptions

- Runtime inspection can distinguish worktree registration, physical path
  existence, and preserved local modifications without mutating the target.
- Existing retrying jobs retain enough allocation and root-tree ownership metadata
  to be evaluated by the corrected cleanup behavior.
- An expired session-owned worktree has no independent retention claim after the
  owning root crosses permanent purge fencing.

## Confirmation

The requester explicitly confirmed this Requirements snapshot on 2026-07-22 and
authorized autonomous design, implementation, and pull-request delivery.
