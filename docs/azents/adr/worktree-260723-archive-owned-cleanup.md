---
title: "Archive-Owned Session Worktree Cleanup"
created: 2026-07-23
tags: [architecture, backend, session, worktree, retention]
document_role: primary
document_type: adr
snapshot_id: worktree-260723
---

# worktree-260723/ADR: Archive-Owned Session Worktree Cleanup

## Context

The confirmed
[worktree-260723/REQ](../requirements/worktree-260723-archive-owned-cleanup.md)
changes the Session worktree lifecycle boundary established by the implemented
[worktree-260722/ADR](./worktree-260722-archive-purge-integrity.md). The prior
decision made archive a Runtime-backed integrity gate and made retention purge
responsible for forced Git cleanup before database deletion. In production, this
coupled durable retention progress to the availability and deployed version of a
user Runtime Runner.

The new requirements make archive cleanup disposable and make purge authoritative
only for the database Session tree. The existing durable participant snapshots
still contain `session.git-worktrees@1`, so removing that participant would make
already-fenced jobs fail snapshot validation before they could progress.

## Decisions

### worktree-260723/ADR-D1 — Archive commits before one forced best-effort cleanup attempt

After the archive transaction commits, the service synchronously attempts forced
cleanup for every non-cleaned allocation in the root tree. Known per-allocation
Runner failures remain recorded by the worktree service. Any remaining exception
is logged at the archive best-effort boundary and does not change the successful
archive result.

This decision applies to worktree-260723/REQ-1 and REQ-4.

Pre-archive integrity validation is removed because cleanup eligibility no longer
controls archive eligibility. Running external cleanup inside the archive
transaction is rejected because Runtime latency or failure must not roll back the
database transition. Durable cleanup scheduling is rejected because archive
cleanup has no retry obligation.

### worktree-260723/ADR-D2 — Purge checkpoints a database-only compatibility tombstone

`session.git-worktrees@1` remains registered so existing immutable participant
snapshots remain resolvable. Its purge phases perform no Runtime, Git, filesystem,
or allocation-status operation and checkpoint normally. Its ownership manifest
contains only the allocation table as a pure database child with declared-cascade
purge policy; the physical worktree external resource declaration is removed.

This decision applies to worktree-260723/REQ-2, REQ-3, and REQ-4.

Removing the key is rejected because existing jobs would fail snapshot validation.
Bumping the policy version is rejected because the current registry resolves one
version per stable key and existing jobs must converge without a migration.
Retaining the old Runtime cleanup implementation is rejected because Runtime
availability must not influence purge.

Reusing policy version 1 deliberately changes its executable behavior under this
superseding decision. This exception preserves ordinary retry convergence and is
bounded to converting the former destructive participant into a no-op tombstone.

### worktree-260723/ADR-D3 — Database finalization ignores physical worktree state

The finalizer explicitly deletes worktree allocation rows before restrictive
Session context rows and the AgentSession tree. It does not read cleanup status or
require a terminal worktree outcome. The installed schema's restrictive
`session_agent_context_git_worktrees.session_agent_context_id` foreign key remains
unchanged; the existing explicit deletion order satisfies it.

This decision applies to worktree-260723/REQ-2.

Adding a database migration is rejected because the required deletion order
already exists and no persistence contract must change. Restoring cascade delete
on the restrictive context foreign key is rejected because the explicit
finalization boundary remains the reviewed deletion authority.

### worktree-260723/ADR-D4 — Existing failures converge through ordinary phase retry

A job previously failed at
`session.git-worktrees/CLEANUP_COMPLETED` re-enters that incomplete phase, executes
the tombstone no-op, checkpoints it, and unblocks `session.context`. Existing
successful participant checkpoints are not repeated.

This decision applies to worktree-260723/REQ-3.

Direct database repair, checkpoint reset, Runtime restart, and a separate legacy
worker are rejected because they bypass or duplicate the durable retry protocol.

## Consequences

- Archive may succeed while physical worktree data remains.
- A process cancellation or crash immediately after archive commit may skip the
  single cleanup attempt.
- Restore does not reconstruct a worktree removed at archive.
- Purge cannot be blocked by Runtime image drift, Runner readiness, Git
  registration, branch state, or worktree allocation status.
- Historical worktree-260722 decisions remain preserved as the rationale for the
  superseded behavior.
