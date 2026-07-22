---
title: "Session Worktree Archive and Purge Integrity"
created: 2026-07-22
tags: [architecture, backend, runtime, session, git, retention]
document_role: primary
document_type: adr
snapshot_id: worktree-260722
---

# worktree-260722/ADR: Session Worktree Archive and Purge Integrity

## Context

The confirmed
[worktree-260722/REQ](../requirements/worktree-260722-archive-purge-integrity.md)
requires archive to preserve modified and untracked worktree contents while
rejecting lifecycle states that cannot be restored or safely purged. Retention
purge must later remove registered owned worktrees irreversibly, converge when the
expected target is already absent, and never delete an existing path whose Git
registration and Azents ownership do not agree.

The database allocation is the authority that Azents owns a worktree, but it
cannot prove current Git registration or physical target state. The existing
Runner removal operation delegates directly to `git worktree remove`, uses
`force=false`, and reports every nonzero Git exit as an undifferentiated failure.
Archive currently performs no worktree integrity check.

This ADR refines the established typed Git-operation and explicit allocation
ownership decisions in
[azents-260703/ADR](./azents-260703-azents-git-worktree-ownership-and-cleanup.md).

## Decisions

### worktree-260722/ADR-D1 — Inspect worktree integrity through a typed non-mutating Runner operation

Add a typed Runner operation that inspects one recorded worktree against its
source repository. The result reports exact Git registration, physical target
kind, registered branch identity, and a content-free dirty-state classification.
It does not return file names or diff content.

Archive uses this operation for every non-cleaned allocation in the locked root
tree before applying the archive mutation. A registered directory with the
recorded branch remains valid whether clean, modified, or untracked. Missing,
unregistered, mismatched, non-directory, invalid-source, and unavailable
inspection states reject archive.

This decision applies to worktree-260722/REQ-1, REQ-2, REQ-4, and REQ-6.

Generic shell execution is rejected because it bypasses the typed Git contract,
weakens semantic result handling, and conflicts with the existing runtime-control
boundary. Database-only validation is rejected because it cannot distinguish a
registered target, a stale allocation, and an unrelated existing path.

### worktree-260722/ADR-D2 — Classify physical absence separately from ambiguous existing paths

Purge combines the trusted allocation with Runner inspection:

| Git registration | Physical target | Purge outcome |
| --- | --- | --- |
| exact recorded registration | directory | remove with `force=true` |
| exact or stale registration | missing | idempotent absent cleanup |
| no exact registration | missing | idempotent absent cleanup |
| no exact registration or mismatched registration | existing | safety failure; retain metadata and retry |
| exact registration | non-directory target | safety failure; retain metadata and retry |

The source repository must remain inspectable so Azents-created branch cleanup can
be completed or proven already complete. Source-repository ambiguity is a
retryable safety failure, not an absent-target success.

The Runner removal operation repeats the same registration and physical-state
check immediately before mutation. This prevents the service's prior inspection
from becoming deletion authority after state changes. Reserved-root membership
alone remains insufficient.

This decision applies to worktree-260722/REQ-3, REQ-4, and REQ-6.

Deleting any existing unregistered path is rejected because a database allocation
can be stale while the path has been replaced by unrelated content. Treating every
Git failure as retryable is rejected because confirmed absence is already the
terminal cleanup state.

### worktree-260722/ADR-D3 — Force cleanup belongs only to retention purge

Retention purge invokes worktree removal with `force=true`, allowing modified and
untracked contents preserved through archive to cross the irreversible retention
boundary. Archive, restore, and manual cleanup do not gain purge authority and do
not perform forced removal as part of this snapshot.

The allocation must pass database ownership fencing, root-tree membership checks,
Agent Workspace path validation, exact Git registration checks for existing
targets, and Azents branch ownership checks before forced cleanup.

This decision applies to worktree-260722/REQ-1, REQ-3, and REQ-4.

Archive-time cleanup and clean-status admission checks are rejected because
archive is a reversible preservation transition. A general `force` default is
rejected because it would extend irreversible authority to non-purge callers.

### worktree-260722/ADR-D4 — Branch cleanup is idempotent only after authoritative absence

The typed branch deletion operation first checks the recorded branch in the valid
source repository. It deletes an existing Azents-created branch and returns a
terminal already-absent outcome when the branch is not present. Invalid
repositories, transport failures, and other Git failures remain errors.

Per-allocation durable cleanup summaries distinguish force removal and confirmed
absence. The allocation reaches `cleaned` only after the worktree and owned branch
are terminal and the catalog/project cleanup transaction commits.

This decision applies to worktree-260722/REQ-3, REQ-4, and REQ-6.

Swallowing every branch deletion failure is rejected because it could hide an
invalid repository or incomplete cleanup. Repeating `git branch -D` without an
absence check is rejected because an already-deleted branch would strand an
otherwise complete retry.

### worktree-260722/ADR-D5 — Existing purge jobs retain their participant snapshot and checkpoints

The worktree participant remains policy version 1 because this snapshot corrects
the implementation of its existing ownership and cleanup contract rather than
changing the durable participant schema or ordering. Existing retry jobs rerun
only incomplete participant phases through the ordinary lease and retry workflow.
Successful participant checkpoints are preserved.

Each retry resets non-cleaned allocation status to cleanup pending, applies the
new terminal classification, and records the resulting allocation summary. No
production database mutation, checkpoint reset, parallel compatibility path, or
legacy worker branch is introduced.

This decision applies to worktree-260722/REQ-3, REQ-5, and REQ-6.

Bumping the participant policy version is rejected because already-materialized
jobs would fail version validation before reaching the corrected cleanup logic.
Resetting participant rows is rejected because it would repeat unrelated external
cleanup.

### worktree-260722/ADR-D6 — Archive exposes a typed bounded integrity conflict

Archive returns a typed worktree-integrity failure containing the opaque allocation
ID, stable reason code, lifecycle stage, and bounded operator-safe summary. The
public route maps it to `409 Conflict`. It never returns the recorded path, branch,
Git output, repository content, or Runner stderr.

The complete archive tree remains active because validation completes before the
archive mutation and the transaction commits only on success.

This decision applies to worktree-260722/REQ-2, REQ-4, and REQ-6.

Returning an internal server error is rejected because the user can act on a
stable integrity conflict. Returning raw Git diagnostics is rejected because they
may disclose filesystem or repository details.

## Consequences

- Runtime Control gains one typed, read-only Git worktree inspection operation and
  richer terminal outcomes for removal and branch deletion.
- Archive availability now depends on a ready current-generation Runner whenever a
  non-cleaned owned allocation exists.
- Dirty state is observed only to prove it is intentionally accepted; it does not
  gate archive.
- Purge can irreversibly remove dirty owned worktrees while preserving the
  allocation and participant retry state on ambiguous paths.
- Confirmed absence becomes a durable successful allocation outcome, allowing
  legacy retry jobs to converge.
- No database migration or participant policy-version change is required.

## Risks

- Holding root-tree database locks during Runner inspection can increase archive
  latency. Inspection uses a short bounded deadline and performs no mutation.
- Filesystem state can change between archive inspection and transaction commit.
  Root/allocation ownership remains locked, and purge independently revalidates
  external state before deletion.
- A source repository that is itself unavailable prevents branch verification and
  therefore keeps purge retryable. This is safer than claiming terminal cleanup
  without branch evidence.
