---
title: "Manual Orphan Worktree Cleanup"
created: 2026-07-26
tags: [architecture, backend, runtime, session, git, frontend]
document_role: primary
document_type: adr
snapshot_id: worktree-260726
---

# worktree-260726/ADR: Manual Orphan Worktree Cleanup

## Context

The confirmed
[worktree-260726/REQ](../requirements/worktree-260726-manual-orphan-cleanup.md)
requires an explicit Session Turn Action that finds Git worktrees left in the
requesting Session's current Agent Runtime, protects every worktree connected to
active root Session work, force-removes the remaining worktrees, preserves local
branches, and reports candidate-level progress and results.

The current operation-action lifecycle already provides durable provenance, FIFO
admission, Session owner-generation fencing, shutdown admission, live
projections, cancellation, and a durable terminal transcript event. It is
specialized around `create_git_worktree`, however, and its projection has no
typed action result.

The current worktree allocation model is authoritative for worktrees still owned
by a Session context. It is not a complete inventory of Runtime worktrees:
archive cleanup is best-effort, while later retention purge removes allocation
rows without requiring physical cleanup. A manual orphan cleanup must therefore
be able to establish current Git identity after the original allocation has been
deleted.

The historical
[azents-260703/ADR](./azents-260703-azents-git-worktree-ownership-and-cleanup.md)
allows destructive cleanup only with a matching allocation row. This snapshot
does not weaken that rule for ordinary Session lifecycle cleanup. It introduces
a separate, explicitly user-authorized recovery boundary for Git-registered
worktrees under the current Runtime's managed worktree root.

## Decision Backlog

The autonomous design resolves the following dependent decisions:

1. operation-action execution and dispatch;
2. authoritative Runtime scope and active protection state;
3. discovery identity and deletion authority;
4. connection-versus-deletion race coordination;
5. durable structured results;
6. candidate ordering, failure, cancellation, and recovery;
7. public action registration and web presentation.

The manual trigger, current-Runtime scope, force policy, branch preservation,
continue-on-candidate-failure behavior, and lack of a second confirmation are
already fixed by the Requirements and are not reopened here.

## Decisions

### worktree-260726/ADR-D1 — Generalize the existing operation Turn Action pipeline

Add `cleanup_orphan_git_worktrees` as a parameterless operation `TurnAction`.
Generalize the create-worktree-specific prepared input and executor dispatch into
a closed operation-action union dispatched by action discriminator. Each
operation keeps an action-specific service handler but reuses the existing
durable `ActionExecution` lifecycle, owner-generation fence, shutdown barrier,
live projection transport, stop behavior, and terminal transcript handover.

This decision applies to worktree-260726/REQ-1 and REQ-6.

A scheduler task, idle hook, or separate background job is rejected because it
would lose the explicit Session authorization and execution provenance required
by the feature. A second cleanup-specific execution framework is rejected
because it would duplicate already-established ownership, cancellation, and
durability behavior.

### worktree-260726/ADR-D2 — Derive protection from active root contexts on the exact Runtime

The requesting execution resolves its canonical root Session context and
`agent_runtime_id`. Cleanup is admitted only when that Runtime and Runner
generation are current and ready.

For that exact Runtime, the authoritative protected set is the union of:

- Project paths in every `SessionAgentContext` whose root `AgentSession` remains
  active and non-archived; and
- worktree allocation paths in those contexts whose status is not `cleaned`,
  including pending creation and failure states.

For a discovered worktree root, a protected path matches when the normalized
POSIX paths are equal or when either path is an ancestor of the other on path
component boundaries. This conservatively protects a worktree when an active
Project is its root, a directory inside it, or a directory that contains it.
Allocation paths use the same overlap predicate, although current allocations
normally record the exact worktree root.

All members of a root SessionAgent tree share the root context, so the context
Project and allocation sets protect root and subagent work without separately
inferring child ownership. Contexts on another Runtime and contexts whose root
Session is archived do not protect a path.

This decision applies to worktree-260726/REQ-2 and REQ-3.

Directory naming, allocation status alone, the requesting Session alone, and
Agent Project catalog rows are rejected as protection authority. They
respectively omit product state, omit manually registered worktrees, omit other
active roots, or represent a filesystem read model rather than active Session
scope.

### worktree-260726/ADR-D3 — Discover and remove managed worktrees through new typed Runner operations

Add a typed Runner discovery operation scoped internally to the canonical
`/workspace/agent/.azents/worktrees` root. It returns a bounded, path-sorted
inventory containing:

- the canonical target path;
- whether exact Git worktree registration was established;
- a safe repository anchor under the Agent Workspace;
- registered branch identity when present;
- a stable registration fingerprint used for revalidation; and
- a bounded classification for ambiguous managed-root entries.

Add a separate guarded removal operation for a discovered managed worktree. The
request carries the discovered identity and `force=true`. Immediately before
mutation the Runner verifies the canonical target remains under the managed root,
the repository anchor remains valid, and the exact registration fingerprint and
branch identity still match. It then removes only the Git worktree registration
and physical target. It never invokes branch deletion.

An entry under the managed root whose Git identity cannot be established is
returned as an examined failure and is never passed to generic filesystem
deletion. A target that becomes absent after discovery returns the terminal
`already_absent` outcome when the Runner can safely reconcile its registration.

This decision applies to worktree-260726/REQ-2, REQ-4, REQ-5, and REQ-6.

Reusing recursive file deletion is rejected because managed-root membership is
not Git identity. Requiring a surviving allocation row is rejected because
retention purge may legitimately delete that row before a failed archive cleanup
is recovered. Weakening the allocation-backed lifecycle removal operation is
rejected; manual orphan cleanup has its own stricter discovery-and-revalidation
contract.

### worktree-260726/ADR-D4 — Coordinate managed-root topology and exact targets with durable claims

Add a durable worktree-path claim keyed by Agent Runtime and canonical worktree
path. Use two short PostgreSQL transaction advisory locks in a fixed order:

1. a Runtime-scoped managed-worktree coordination lock serializes cleanup claim
   insertion with Project creation, attachment, and removal whenever the Project
   path equals, contains, or is below the managed root, as well as worktree
   target reservation; and
2. an exact Runtime/path lock serializes candidate claims and destructive writers
   for one canonical worktree target.

Transactions that need both locks always acquire the Runtime lock before the
exact path lock. While holding them, cleanup refreshes the active protection
query using the normalized path-overlap predicate and inserts the exact target
claim only if the path remains unconnected. The transaction commits before
Runner I/O.

Project attachment checks for every blocking claim whose candidate path overlaps
the Project path, rather than checking only exact equality. It rejects the
attachment with a typed conflict while such a claim exists. Worktree target
reservation treats an exact blocking claim like a path collision and selects the
next bounded suffix.

Claims record the owner kind, nullable action execution, owner generation,
discovery fingerprint, lease deadline, candidate state, and latest bounded
outcome. They remain blocking only while leased and the candidate is claimed or
removal is in progress. Manual-action terminalization releases all remaining
claims. The existing stale-operation cancellation boundary also releases claims
when a new Session owner encounters an abandoned execution. An expired lease can
be reclaimed under the path transaction lock after its owner state is
revalidated.

Archive cleanup acquires a short-lived path claim before its existing external
cleanup attempt. If manual cleanup already owns the path, archive preserves its
best-effort contract and skips that allocation. If archive owns the path first,
manual cleanup records bounded `cleanup_in_progress` failure and continues. This
prevents the two destructive paths from concurrently mutating the same Git
registration while leaving archive semantics otherwise unchanged.

This decision applies to worktree-260726/REQ-3, REQ-5, and REQ-6.

A protection query followed directly by Runner removal is rejected because a new
Session connection can commit in the gap. Coordinating only manual cleanup and
Project attachment is rejected because archive cleanup is another destructive
writer for the same paths. An exact submitted-Project-path lock is rejected
because Project paths may be ancestors or descendants of a discovered worktree
root. Requiring exact worktree-root Project registration is rejected because it
would change the existing arbitrary Project registration contract. Holding row
locks or an open database transaction across Runner I/O is rejected by the fixed
constraints. A process-local mutex is rejected because API and worker processes
may be distributed.

### worktree-260726/ADR-D5 — Add one generic structured result field to action executions

Add a nullable JSON result to the generic `ActionExecution` model and projection.
Each operation handler owns validation of its versioned result schema. The
cleanup result contains aggregate counts and bounded candidate outcomes with:

- canonical path;
- outcome: `protected`, `removed`, `already_absent`, `failed`, or `unresolved`;
- stable reason code; and
- bounded user-safe summary.

The cleanup service updates the result after discovery and after every candidate
transition. Existing ordered action events remain the live timeline mechanism,
using cleanup-specific step keys for discovery, protection, removal, success,
and failure. Terminal handover copies the current structured result and ordered
events into the existing `action_execution_result` transcript payload.

This decision applies to worktree-260726/REQ-5 and REQ-6.

Encoding the terminal result only in free-form event text is rejected because the
web client would have to parse presentation strings. A cleanup-only result table
is rejected because other operation actions will need the same projection
extension. Returning file names, status output, diffs, or raw Git diagnostics is
rejected.

### worktree-260726/ADR-D6 — Process a stable inventory sequentially and reconcile interruption

After one fresh discovery, candidates are processed in canonical path order.
Ambiguous discovery entries are recorded as failures, while valid candidates
continue. Before each valid removal the service acquires the path claim and
refreshes protection as defined by ADR-D4. One candidate failure never prevents
later candidates from being attempted.

The action completes successfully when no candidate remains failed. It completes
as failed only after all candidates have been considered when one or more
failures remain. Zero candidates is successful.

On user stop, shutdown cancellation, or ownership loss, completed outcomes remain
durable. The service performs a shielded, bounded reconciliation for an
in-flight candidate when possible, marks candidates whose side effect cannot be
determined as `unresolved`, marks undispatched inventory as unresolved, releases
blocking claims, and terminalizes through the existing cancellation path. A later
invocation always performs new discovery rather than resuming the old inventory.

This decision applies to worktree-260726/REQ-5 and REQ-6.

Parallel removal is rejected because sequential processing gives deterministic
progress, bounded Runner pressure, and a simpler cancellation boundary. Rollback
is rejected because successful external deletions are intentionally irreversible.
Resuming a stale inventory is rejected because active connections and Git state
may have changed.

### worktree-260726/ADR-D7 — Expose one no-parameter action and render cleanup-specific results

The public input-action listing advertises the cleanup action for an accessible,
active Session. Selecting it submits the ordinary action message immediately;
the UI presents destructive helper text before selection but does not add a
second confirmation.

Refactor the current create-worktree-specific execution card into
action-discriminated renderers. The cleanup renderer shows live phase messages,
aggregate counts, candidate paths, bounded reasons, and the terminal
completed/failed/cancelled state. Unknown operation types retain a generic
fallback renderer.

This decision applies to worktree-260726/REQ-1 and REQ-6.

Adding a standalone maintenance page is rejected because the confirmed primary
scenario is a Session Turn Action. Rendering raw command lines or Git output is
rejected because the user contract is semantic cleanup progress, not shell
transcript access.

## Consequences

- Manual cleanup gains explicit deletion authority for allocation-less worktrees
  only when current Git registration and managed-root identity are established.
- Project attachment and worktree target selection gain a shared path
  coordination invariant.
- The database requires cleanup-claim persistence and a generic action-result
  field.
- Runtime Control gains typed discovery and guarded manual-removal operations.
- Local branches survive cleanup by construction.
- Active Session path overlap is evaluated immediately before each deletion
  claim, and managed-root Project connections are coordinated against the claim,
  without holding a database transaction during Runtime work.
- Cancellation can report an unresolved side effect rather than claiming a
  rollback or a false success.

## Risks

- Every Project attachment path must use the shared coordination helper; bypassing
  it would reopen the connection race.
- A malformed or damaged managed-root entry remains on disk and is reported as a
  failure until an operator repairs or removes it outside this action.
- A very large Runtime inventory can exceed the bounded Runner response. The
  action must fail discovery before deletion with an explicit capacity reason
  rather than return a partial inventory.
- Runner unavailability after some removals produces a partial failed or
  cancelled result, which is recovered by a later fresh invocation.
