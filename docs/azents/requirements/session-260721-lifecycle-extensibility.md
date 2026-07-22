---
title: "Extensible Session Lifecycle Requirements"
created: 2026-07-21
updated: 2026-07-21
tags: [session, lifecycle, reliability, database]
document_role: primary
document_type: requirements
snapshot_id: session-260721
---

# Extensible Session Lifecycle Requirements

- Snapshot: `session-260721`
- Document reference: `session-260721/REQ`

## Problem

Session archive, restore, and permanent purge must coordinate an increasing number
of session-bound database rows and external resources. When each new domain is
handled through central lifecycle branches or implicit foreign-key cascades,
required work can be omitted and multiple referential actions can conflict during
deletion. These failures may leave archived sessions unpurged, external resources
orphaned, or lifecycle behavior dependent on database trigger ordering.

## Primary Actor

An Azents operator relying on session archive, restore, and retention purge to
remain correct as new session-bound domains are added.

## Primary Scenario

A workspace member archives a root session tree, may restore it before purge
fencing begins, or allows retention purge to permanently remove it. Every
session-bound domain applies its declared lifecycle behavior, required failures
prevent a partial lifecycle transition, and the final observable session state is
consistent with all required resource state.

## Supporting Scenarios

- A developer adds a session-bound database table or external resource and receives
  a CI failure until its archive, restore, and purge behavior is explicitly covered.
- An audit finds and removes any user-facing or request-path entry point that can
  permanently delete a session outside durable retention purge.
- An authorized Agent deletion request starts a durable decommission lifecycle
  that retires every owned session through retention purge before deleting the
  Agent.
- An interrupted purge retries required external cleanup without losing the
  metadata needed to complete cleanup safely.
- Downstream systems receive lifecycle notifications without becoming authoritative
  for whether archive, restore, or purge succeeded.

## Goals

- Keep session archive, restore, and purge reliable as session-bound domains grow.
- Make every session-bound domain's lifecycle behavior explicit and verifiable.
- Preserve atomic archive and restore behavior across the complete root session tree.
- Make irreversible purge cleanup retryable and prevent database finalization before
  required cleanup succeeds.
- Converge existing archive, restore, and retention-purge behavior on one lifecycle
  contract while keeping retention purge as the only permanent-deletion owner.
- Prevent Agent or Workspace deletion from cascading around the session lifecycle
  boundary.
- Detect unsafe or uncovered session deletion relationships before deployment.

## Non-Goals

- A generic lifecycle framework for every aggregate in the product in the initial
  delivery.
- Destructive external-resource cleanup during archive or restore.
- Making asynchronous notification consumers authoritative for canonical session
  lifecycle state.
- Providing Workspace decommission or Workspace deletion in the initial delivery.
- Changing the current product rule that archive preserves session-owned files and
  worktree allocations until permanent purge.

## Requirements

### REQ-1. Complete lifecycle coverage

Every session-bound domain must have an explicit archive, restore, and purge policy,
including an explicit preserve or no-action policy when no domain-specific
transition is required.

**Acceptance criteria**

- Adding or changing a session-bound relationship without declaring its lifecycle
  policy fails automated validation.
- Operators can determine which domain owns required lifecycle handling for each
  session-bound resource.

### REQ-2. Atomic and reversible archive

Archive must transition the complete root session tree and all required
archive-specific domain state atomically, without destructive external-resource
cleanup.

**Acceptance criteria**

- A required archive-domain failure leaves the root tree and required domain state
  unarchived.
- A successful archive preserves session-owned files, worktrees, and other
  purge-owned external resources.
- Archived sessions reject new execution and writes according to the existing
  session execution fence.

### REQ-3. Symmetric restore

Restore must reverse required archive-specific domain state atomically while purge
fencing has not started.

**Acceptance criteria**

- A required restore-domain failure leaves the complete root tree archived.
- A successful restore returns the complete root tree and required reversible
  domain state to their active lifecycle state.
- Restore remains unavailable after irreversible purge fencing begins.

### REQ-4. Durable and complete purge

Permanent purge must complete and verify all required external-resource cleanup
before deleting the root session tree and its required lifecycle metadata.

**Acceptance criteria**

- A required cleanup or verification failure retains the session tree and the
  metadata required for retry.
- Retrying an interrupted purge does not duplicate irreversible side effects or
  corrupt already completed cleanup.
- Final database deletion and purge-job completion are atomic.

### REQ-5. Domain-local lifecycle extension

Adding lifecycle behavior for a new session-bound domain must not require
duplicating lifecycle orchestration or adding domain-specific branches throughout
unrelated archive, restore, and purge flows.

**Acceptance criteria**

- The new domain's lifecycle behavior and verification are implemented in a
  domain-owned integration point.
- Existing unrelated domain lifecycle implementations do not require modification.
- Archive, restore, and purge retain one consistent ordering and failure contract.

### REQ-6. Existing lifecycle migration

Existing session archive, restore, cleanup, and permanent-deletion behavior must
move behind the same lifecycle coverage boundary rather than leaving parallel
legacy execution paths.

**Acceptance criteria**

- Existing session-bound domain handling is subject to the same ownership,
  ordering, failure, retry, and verification contract as newly added domains.
- Permanent session deletion occurs only through durable retention purge after
  required domain cleanup and verification.
- Any user-facing route, generated client operation, frontend action, or internal
  request-path service that directly performs permanent session deletion is removed.
- No lifecycle entry point directly performs the final root-tree deletion before
  all required domain handling has succeeded.
- The central lifecycle flow retains only cross-domain coordination and does not
  retain domain-specific cleanup branches.

### REQ-7. Unsafe relationship detection

Automated validation must detect session deletion relationships that can perform
conflicting mutations or bypass required lifecycle handling.

**Acceptance criteria**

- Validation reports multiple mutation paths from a session lifecycle root to the
  same table, including mixed `CASCADE` and `SET NULL` paths.
- An intentionally accepted relationship requires explicit ownership and an
  executable PostgreSQL lifecycle test.
- The production-equivalent deletion path is exercised with representative
  populated relationships rather than validated only from ORM metadata.

### REQ-8. Authoritative lifecycle completion

Archive, restore, and purge may notify downstream systems, but canonical lifecycle
success must not depend on an untracked or best-effort event consumer.

**Acceptance criteria**

- The lifecycle operation reports success only after all required canonical state
  changes are durably committed.
- A delayed or unavailable notification consumer does not create partial canonical
  lifecycle state.
- Downstream lifecycle notifications are emitted only for committed transitions.

### REQ-9. Actionable failure and retry visibility

Lifecycle failures must identify the affected domain and lifecycle stage while
preserving a safe retry path.

**Acceptance criteria**

- Operators can identify whether failure occurred during archive, restore, purge
  cleanup, purge verification, or final database deletion.
- Purge retry state identifies the domain whose required work remains incomplete.
- Repeated failure in one session does not prevent other eligible session purge
  jobs from advancing.

### REQ-10. Safe parent aggregate deletion

An authorized Agent deletion request must durably decommission the Agent and route
every owned session through the session lifecycle instead of deleting sessions
through an Agent foreign-key cascade. Workspace deletion is unavailable in the
initial delivery.

**Acceptance criteria**

- Once Agent decommission begins, the Agent cannot start new sessions, accept new
  execution, or restore an archived session.
- Every Agent-owned root tree, including the team-primary tree, reaches an archived
  and execution-fenced state through authoritative lifecycle handling.
- Each owned session is permanently deleted only by retention purge after its
  required cleanup and verification complete.
- The Agent row is deleted only after no owned AgentSession or required
  Agent-lifecycle resource remains.
- Agent decommission failure is durable, retryable, and observable without
  reactivating the Agent.
- Agent deletion is rejected while the current archived-session retention policy
  is Unlimited.
- The Admin Workspace deletion route and generated client operation are removed.
- Agent or Workspace database deletion cannot cascade around the required session
  lifecycle.

## Fixed Constraints

- Archive and restore remain reversible database lifecycle transitions.
- Destructive external-resource cleanup occurs only during permanent purge.
- Purge retains the existing root-tree fencing and cleanup-before-delete safety
  boundary.
- Durable retention purge is the only permanent session-deletion owner.
- The existing user-facing Delete action remains an archive-backed reversible
  removal action and does not become permanent deletion.
- Agent Delete starts decommission rather than directly deleting the Agent or its
  sessions.
- Workspace Delete is not supported in the initial delivery.
- Parent aggregate deletion does not override archived-session retention or create
  a user-requested immediate session-purge path.
- Agent decommission requires a finite archived-session retention policy.
- PostgreSQL behavior from the installed schema is authoritative for referential
  action validation.
- Required lifecycle work must be deterministic, idempotent where retried, and
  testable without relying on notification timing.
- No legacy lifecycle fallback is required.

## Open Assumptions

- The initial implementation applies the lifecycle coverage model to AgentSession
  root trees; other aggregate roots may adopt it later.
- Domains with no archive-specific state may explicitly declare preservation while
  still participating in purge coverage.
- Post-commit lifecycle notifications may reuse an existing durable delivery
  mechanism if repository feasibility analysis finds one suitable.

## Confirmation

Confirmed by the requester on 2026-07-21, including the correction that durable
retention purge remains the only permanent-deletion owner, Agent Delete becomes a
durable decommission lifecycle, Workspace Delete is removed, and Agent Delete is
rejected while archived-session retention is Unlimited.
