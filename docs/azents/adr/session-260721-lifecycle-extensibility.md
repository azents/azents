---
title: "Extensible Session Lifecycle"
created: 2026-07-21
tags: [session, lifecycle, reliability, database, architecture]
document_role: primary
document_type: adr
snapshot_id: session-260721
---

# Extensible Session Lifecycle

- Snapshot: [session-260721/REQ](../requirements/session-260721-lifecycle-extensibility.md)
- Document reference: `session-260721/ADR`

## Context

Session archive, restore, and retention purge currently coordinate session-bound
domains directly from central services and rely on database cascades for final
deletion. This makes lifecycle correctness harder to extend as new database
relationships and external resources are added.

The production archived-session purge failure demonstrated that individually valid
foreign keys can create an invalid combined referential-action sequence. A
worktree allocation was reachable from the deleted root through two creator
`SET NULL` paths and one context-owned `CASCADE` path. PostgreSQL attempted an
update-side foreign-key check after the parent context had been removed but before
the worktree row's cascade deletion, aborting the complete session deletion.

[session-260721/REQ](../requirements/session-260721-lifecycle-extensibility.md)
requires existing and future session-bound domains to receive explicit archive,
restore, and purge coverage; archive and restore to remain atomic and reversible;
purge cleanup to remain durable and retryable; durable retention purge to remain
the sole permanent-deletion owner; leaked direct user-deletion paths to be removed;
Agent deletion to decommission rather than cascade sessions; Workspace deletion to
be removed; and CI to reject uncovered or unsafe lifecycle relationships.

## Decision Topics

The following architecture topics are resolved by the decisions below:

1. **Authoritative execution model**: whether required lifecycle work uses direct
   participants, asynchronous event consumers, or a hybrid boundary.
2. **Lifecycle phase contract**: how archive, restore, purge preparation, external
   cleanup, verification, and final database deletion are divided, and which phases
   share a transaction.
3. **Participant registration and ownership**: how each session-bound domain
   declares archive, restore, and purge responsibility, including explicit preserve
   or no-action policies.
4. **Purge progress and retry state**: whether progress is tracked only for the
   complete purge job or durably per participant and phase.
5. **Permanent-deletion ownership**: whether durable retention purge remains the
   sole permanent-deletion owner and how leaked user-facing or request-path delete
   entry points are removed.
6. **Database deletion and foreign-key policy**: which rows participants delete
   explicitly, where ownership cascades remain allowed, and how conflicting
   referential-action paths are prevented.
7. **Participant ordering and dependencies**: whether lifecycle execution uses only
   fixed phases or also permits declared dependencies between domain participants.
8. **Coverage validation and exceptions**: how schema-graph validation, real
   PostgreSQL lifecycle tests, and reviewed exceptions prove that new
   session-bound relationships are covered.
9. **Post-commit event delivery**: which lifecycle notifications require durable
   delivery and how they remain non-authoritative for canonical lifecycle success.
10. **Migration and cutover**: how existing archive, restore, worktree, file,
    broker, direct-delete, and retention-purge logic moves to the lifecycle
    boundary without retaining parallel legacy paths.
11. **Parent aggregate deletion**: how Agent deletion retires owned sessions
    without bypassing retention purge and how Workspace cascade deletion is
    removed.

## Decisions

### ADR-D1. Authoritative participants determine canonical lifecycle success

Affected requirements:
[session-260721/REQ-2](../requirements/session-260721-lifecycle-extensibility.md#req-2-atomic-and-reversible-archive),
[session-260721/REQ-3](../requirements/session-260721-lifecycle-extensibility.md#req-3-symmetric-restore),
[session-260721/REQ-4](../requirements/session-260721-lifecycle-extensibility.md#req-4-durable-and-complete-purge),
[session-260721/REQ-5](../requirements/session-260721-lifecycle-extensibility.md#req-5-domain-local-lifecycle-extension),
and
[session-260721/REQ-8](../requirements/session-260721-lifecycle-extensibility.md#req-8-authoritative-lifecycle-completion).

Canonical session lifecycle work is executed by a lifecycle orchestrator through
registered authoritative participants. Participant completion directly determines
archive, restore, and purge success.

Asynchronous lifecycle events are emitted only after a committed transition and
are not authoritative for canonical lifecycle success. Event consumers may retry
or reconcile their own derived state, but their failure does not roll back or
invalidate a committed session lifecycle transition.

Work that must succeed for the canonical session and its owned resources to remain
consistent, including execution fencing, external-resource cleanup, required
database finalization, and final session-tree deletion, must not be delegated
solely to lifecycle event consumers.

The delivery guarantees for non-authoritative post-commit events remain a separate
decision.

### ADR-D2. Use fixed transition-specific lifecycle phases

Affected requirements:
[session-260721/REQ-2](../requirements/session-260721-lifecycle-extensibility.md#req-2-atomic-and-reversible-archive),
[session-260721/REQ-3](../requirements/session-260721-lifecycle-extensibility.md#req-3-symmetric-restore),
[session-260721/REQ-4](../requirements/session-260721-lifecycle-extensibility.md#req-4-durable-and-complete-purge),
and
[session-260721/REQ-9](../requirements/session-260721-lifecycle-extensibility.md#req-9-actionable-failure-and-retry-visibility).

Session lifecycle uses fixed transition-specific phases rather than allowing each
participant to define an arbitrary workflow.

Archive and restore execute their participant validation and database state changes
in the same transaction as the core root-tree transition. These phases prohibit
destructive external I/O and participant-owned commits. Any required participant
failure rolls back the complete transition.

Purge uses the following fixed phase boundary:

1. Claim and fence the durable root-tree purge job.
2. Prepare and validate participant cleanup targets while retaining the metadata
   required for retry.
3. Execute idempotent external cleanup outside the final database transaction.
4. Verify that required external cleanup is complete.
5. In one final database transaction, revalidate the root-tree boundary, run
   participant-owned database finalization, delete the root session tree, and
   complete the purge job.
6. Emit non-authoritative lifecycle events only after commit.

Purge does not enter final database deletion when preparation, external cleanup, or
verification fails. The persistence granularity for participant progress remains a
separate decision.

### ADR-D3. Use an explicit registry with domain-owned lifecycle policies

Affected requirements:
[session-260721/REQ-1](../requirements/session-260721-lifecycle-extensibility.md#req-1-complete-lifecycle-coverage),
[session-260721/REQ-5](../requirements/session-260721-lifecycle-extensibility.md#req-5-domain-local-lifecycle-extension),
[session-260721/REQ-6](../requirements/session-260721-lifecycle-extensibility.md#req-6-existing-lifecycle-migration),
and
[session-260721/REQ-7](../requirements/session-260721-lifecycle-extensibility.md#req-7-unsafe-relationship-detection).

Each session-bound domain defines its lifecycle participant and an explicit
lifecycle ownership policy. The policy declares the domain's archive, restore, and
purge behavior, including explicit preservation or no-action behavior when a phase
requires no domain-specific state change.

Participants are assembled into one deterministic immutable registry at the
application composition root. Adding a domain requires an explicit registry entry,
but does not add domain-specific branches to the lifecycle orchestrator.
Import-time registration and mutable global participant discovery are prohibited.

Every session-bound database table and external resource must have exactly one
declared lifecycle owner or an explicit independent-lifecycle classification. One
participant may own multiple related resources, but multiple participants may not
claim the same resource.

Startup and CI validation reject duplicate participant keys, conflicting resource
ownership, incomplete archive/restore symmetry, incomplete purge responsibilities,
and disagreement between declared policies and the assembled registry. Complete
foreign-key graph coverage remains a separate validation decision.

### ADR-D4. Persist purge progress per participant and phase

Affected requirements:
[session-260721/REQ-4](../requirements/session-260721-lifecycle-extensibility.md#req-4-durable-and-complete-purge)
and
[session-260721/REQ-9](../requirements/session-260721-lifecycle-extensibility.md#req-9-actionable-failure-and-retry-visibility).

Each durable purge job has one execution record for every required lifecycle
participant. Participant execution records identify the participant and policy
version and persist the current purge phase, attempt count, last error, lifecycle
timestamps, and bounded operational summary.

The required participant set is materialized when irreversible purge fencing
begins. An in-progress fenced purge therefore retains a stable required participant
set across retries and deployments. Missing or incomplete required participant
records prevent final database deletion.

Retries resume participants that have not completed external cleanup and
verification. Externally completed participant work is not repeated merely because
another participant failed, although cleanup remains idempotent because a process
may terminate after an external side effect and before its durable checkpoint.

Domain resource rows remain the source of truth for cleanup targets. Participant
execution records track orchestration progress rather than duplicating arbitrary
domain resource lists.

Participant database finalization is not committed as independent participant
progress. All participant finalization, root-tree deletion, and purge-job
completion occur in the atomic final transaction established by ADR-D2.

### ADR-D5. Keep durable retention purge as the sole permanent-deletion owner

Affected requirements:
[session-260721/REQ-4](../requirements/session-260721-lifecycle-extensibility.md#req-4-durable-and-complete-purge),
[session-260721/REQ-6](../requirements/session-260721-lifecycle-extensibility.md#req-6-existing-lifecycle-migration),
and
[session-260721/REQ-8](../requirements/session-260721-lifecycle-extensibility.md#req-8-authoritative-lifecycle-completion).

Durable retention purge remains the only owner of permanent session deletion.
User-facing session removal continues to archive the root tree and remains
reversible until retention purge fencing starts. No user-facing permanent-delete
API or action is introduced.

Any user-facing route, generated client operation, frontend action, or internal
request-path service that can directly perform permanent session deletion is
removed. The existing UI action labeled Delete is not removed when it continues to
invoke the archive transition and does not claim permanent deletion.

Final root-tree deletion may be invoked only by the retention-purge lifecycle
finalizer after all required participants have completed cleanup, verification,
and database finalization.

### ADR-D6. Explicitly finalize lifecycle roots and limit cascades to pure database children

Affected requirements:
[session-260721/REQ-4](../requirements/session-260721-lifecycle-extensibility.md#req-4-durable-and-complete-purge),
[session-260721/REQ-6](../requirements/session-260721-lifecycle-extensibility.md#req-6-existing-lifecycle-migration),
and
[session-260721/REQ-7](../requirements/session-260721-lifecycle-extensibility.md#req-7-unsafe-relationship-detection).

A session-bound resource is a lifecycle root when its deletion requires external
cleanup, retry, domain validation, lifecycle metadata, or an observable
finalization result. Lifecycle-root ownership foreign keys use restrictive
deletion semantics. The owning participant explicitly deletes lifecycle-root
database rows during the atomic purge finalization transaction after external
cleanup and verification have succeeded.

Database cascades are permitted only for pure database children that have no
independent lifecycle work, have no meaning without their parent, and are reachable
through one unambiguous ownership path. The final root-session deletion is
therefore a final integrity check and removal of safe database children, not the
mechanism that discovers or initiates required lifecycle cleanup.

Reference and provenance foreign keys default to restrictive deletion semantics.
`SET NULL` requires an explicit contract that the child remains meaningful and
fully operable after the referenced row is removed. Nullable columns alone do not
justify mutating referential actions.

Multiple mutating paths from one session lifecycle root to the same table are
prohibited by default, including multiple `CASCADE` paths and any mixture of
`CASCADE`, `SET NULL`, or `SET DEFAULT`. Reviewed exceptions and their executable
validation remain a separate decision.

Session Git worktree allocation rows become explicitly finalized lifecycle roots.
Their participant deletes the allocation rows before context and session
finalization. Restrictive ownership and creator references prevent direct session
or context deletion from bypassing required cleanup.

### ADR-D7. Use fixed phases with a limited explicit dependency graph

Affected requirements:
[session-260721/REQ-4](../requirements/session-260721-lifecycle-extensibility.md#req-4-durable-and-complete-purge)
and
[session-260721/REQ-5](../requirements/session-260721-lifecycle-extensibility.md#req-5-domain-local-lifecycle-extension).

Lifecycle participants execute only within the fixed phases established by ADR-D2.
Registry list order and numeric priorities do not define lifecycle execution order.

A participant may declare a stable-key dependency only when required by resource
ownership or cleanup correctness. The registry validates the dependency graph and
rejects missing participant references and cycles. Dependency cycles are resolved
by correcting ownership, changing schema relationships, or combining responsibilities
under one participant rather than by introducing an ordering exception.

Archive and restore validation run for every required participant, and database
application follows the validated dependency order in one transaction. Purge
cleanup and verification do not run a dependent participant until its prerequisite
participants have completed. A participant waiting on a failed prerequisite is
reported as blocked rather than independently failed.

Participant database finalization follows the validated dependency order. The
orchestrator always runs core root-session deletion after every participant has
completed finalization, so participants do not declare repetitive dependencies on
the core finalizer.

### ADR-D8. Validate installed schema graphs and executable lifecycle contracts

Affected requirements:
[session-260721/REQ-1](../requirements/session-260721-lifecycle-extensibility.md#req-1-complete-lifecycle-coverage),
[session-260721/REQ-6](../requirements/session-260721-lifecycle-extensibility.md#req-6-existing-lifecycle-migration),
and
[session-260721/REQ-7](../requirements/session-260721-lifecycle-extensibility.md#req-7-unsafe-relationship-detection).

CI creates a fresh supported PostgreSQL database, applies the Alembic migration
chain to head, and validates session lifecycle coverage against the installed
`pg_constraint` and `pg_trigger` graph. ORM metadata alone is not accepted as
evidence of production referential-action behavior.

Static validation rejects uncovered session-bound resources, lifecycle-root
cascades, multiple mutating paths, incompatible referential actions, ambiguous
ownership, incomplete participant policies, and disagreement between registry
declarations and installed constraints. Diagnostics include the complete path from
the lifecycle boundary to the affected table.

Production-equivalent PostgreSQL lifecycle contract tests populate dense root-tree
fixtures, including valid nullable provenance and ownership references, and execute
archive, restore, retention purge, participant failure, retry, final-transaction
rollback, and direct-deletion bypass scenarios.

An intentionally accepted graph exception is scoped to exact constraint names and
paths, identifies the owning participant and rationale, and references an
executable PostgreSQL contract test. Table-wide ignores, wildcard exceptions, and
untested allowlist entries are prohibited. A changed constraint path invalidates
the existing exception.

### ADR-D9. Emit best-effort lifecycle notifications after commit

Affected requirement:
[session-260721/REQ-8](../requirements/session-260721-lifecycle-extensibility.md#req-8-authoritative-lifecycle-completion).

Session lifecycle emits non-authoritative notifications only after the canonical
lifecycle transaction commits. Event publication and consumer failure do not roll
back, invalidate, or change the result of the committed archive, restore, or purge
transition.

Lifecycle event consumers treat events as invalidation or acceleration signals and
retain a canonical read or reconciliation path. Lifecycle events therefore may be
lost without making canonical session state incorrect. Event payloads carry stable
operation and lifecycle identities sufficient for consumers to perform idempotent
refetch or cleanup when delivery succeeds.

The initial lifecycle framework does not introduce a transactional outbox or
per-event delivery guarantees. If a future consumer requires guaranteed delivery,
that requirement is designed separately. Work required for session and resource
correctness remains an authoritative participant rather than being reclassified as
a durable event consumer.

### ADR-D10. Prepare additively and perform one authoritative cutover

Affected requirements:
[session-260721/REQ-5](../requirements/session-260721-lifecycle-extensibility.md#req-5-domain-local-lifecycle-extension),
[session-260721/REQ-6](../requirements/session-260721-lifecycle-extensibility.md#req-6-existing-lifecycle-migration),
[session-260721/REQ-7](../requirements/session-260721-lifecycle-extensibility.md#req-7-unsafe-relationship-detection),
and
[session-260721/REQ-10](../requirements/session-260721-lifecycle-extensibility.md#req-10-safe-parent-aggregate-deletion).

The lifecycle architecture is delivered through additive foundation, participant,
and validation phases followed by one authoritative production cutover.
Preparatory phases add contracts, registry assembly, participant execution storage,
domain participants, schema validation, and lifecycle contract tests without
creating a second authoritative production lifecycle path.

The authoritative cutover moves archive, restore, retention purge, retry, and final
root-session deletion to the lifecycle orchestrator. The same cutover removes
direct legacy orchestration and any leaked user-facing or request-path permanent
delete entry point. It does not retain a feature flag, dual write, fallback delete
path, or participant-failure bypass.

Existing pending and retryable purge jobs materialize the participant set required
by the current registry when they first enter irreversible fencing under the new
workflow. Existing completed jobs are unchanged. A job already owned by an old
worker is allowed to finish or have its lease expire before the new workflow claims
it; old and new workers do not process the same lease concurrently.

Foreign-key hardening follows the authoritative code cutover or is coupled to the
same controlled deployment boundary. Once restrictive lifecycle-root constraints
are installed, rollback restores service through a forward fix rather than
reactivating the old direct-deletion path.

Implementation may use stacked preparatory pull requests, but production behavior
is not activated until the complete participant set, lifecycle contract tests, and
cutover path are ready.

### ADR-D11. Decommission Agents and remove Workspace deletion

Affected requirements:
[session-260721/REQ-6](../requirements/session-260721-lifecycle-extensibility.md#req-6-existing-lifecycle-migration),
[session-260721/REQ-7](../requirements/session-260721-lifecycle-extensibility.md#req-7-unsafe-relationship-detection),
and
[session-260721/REQ-10](../requirements/session-260721-lifecycle-extensibility.md#req-10-safe-parent-aggregate-deletion).

An authorized Agent deletion request starts a durable Agent decommission operation
instead of deleting the Agent row. Decommission immediately prevents new Agent
work, durably retires every owned root session tree, and waits for retention purge
to permanently delete those sessions before final Agent deletion.

Agent Delete is rejected with a conflict while the current archived-session
retention policy is Unlimited. A finite policy must be active before the
decommission transaction starts. This avoids accepting a Delete operation that
cannot converge while still prohibiting a request-specific retention override or
immediate purge.

The decommission worker uses authoritative session lifecycle operations. It may
retire the team-primary root under the aggregate-shutdown boundary even though the
ordinary member archive action continues to reject team-primary sessions. Existing
archived retention snapshots remain unchanged, and newly retired active roots
snapshot the current retention policy. Agent decommission does not create an
immediate-purge override.

Restore and new session creation remain unavailable after decommission starts.
Decommission has no cancellation path after session retirement begins because
some owned roots may already have crossed irreversible purge fencing.

The Admin Workspace deletion route and its generated client operation are removed.
The initial design does not introduce Workspace decommission.

Foreign keys from AgentSession to Agent and Workspace, and from Agent to Workspace,
use restrictive deletion semantics. Parent aggregate deletion can therefore occur
only after lifecycle-owned children have been explicitly finalized.

## Consequences

- The lifecycle orchestrator has a complete, directly observable set of required
  participants for each transition.
- Archive and restore can preserve transactional failure semantics without waiting
  for asynchronous consumer acknowledgements.
- Durable purge jobs may retry participant work directly without introducing a
  distributed event-consumer completion saga.
- Event consumers are limited to projections and side effects whose failure can be
  retried or reconciled without changing canonical lifecycle success.
- Archive and restore retain one atomic database boundary across core and
  participant state changes.
- Purge never holds the final database transaction open across external cleanup.
- Participant implementations share one predictable phase and failure contract
  instead of defining arbitrary lifecycle workflows.
- Participant discovery is deterministic and does not depend on import side
  effects.
- Domain-specific lifecycle behavior remains inside the owning domain while the
  central orchestrator depends only on the participant contract.
- Explicit preserve and no-action policies distinguish deliberate lifecycle
  behavior from an omitted integration.
- Operators can identify the exact participant and phase blocking a purge.
- Completed external cleanup is not repeatedly executed when an unrelated
  participant retries.
- Purge cleanup still requires idempotency around the external-side-effect and
  checkpoint boundary.
- The participant set for an irreversibly fenced purge is stable and auditable.
- User-facing session removal remains the existing reversible archive transition.
- Permanent session deletion has one durable owner and cannot be initiated through a
  request-path cleanup implementation.
- Leaked permanent-delete routes or client surfaces are removed rather than adapted
  into a second purge trigger.
- Agent Delete remains available as a durable decommission request while losing its
  direct row-deletion and session-cascade behavior.
- Unlimited retention prevents Agent decommission admission rather than creating an
  indefinitely pending Delete operation.
- Team-primary sessions remain protected from ordinary archive but can be retired
  by irreversible Agent decommission.
- Workspace Delete is removed until a separate Workspace decommission contract is
  designed.
- Parent aggregate foreign keys become bypass guards rather than cascading
  permanent-session deletion paths.
- Required external-resource metadata cannot disappear through an implicit parent
  cascade before cleanup and verification succeed.
- Direct deletion paths that bypass lifecycle finalization fail on restrictive
  foreign keys instead of silently removing or mutating lifecycle roots.
- Safe database cascades remain available for simple children without expanding the
  participant surface for every internal detail table.
- Lifecycle execution order is explicit and reviewable rather than encoded in
  registry placement or arbitrary numeric priority.
- Independent participants remain eligible for future parallel external cleanup.
- A failed prerequisite does not inflate retry counts for dependent participants
  that were never attempted.
- CI validates the same PostgreSQL referential-action graph that production
  executes rather than inferring safety only from model declarations.
- Risky lifecycle relationships fail with actionable path diagnostics before
  deployment.
- Narrow executable exceptions preserve flexibility without turning the validator
  into a broad allowlist.
- Lifecycle event infrastructure remains proportional to its non-authoritative
  role and does not introduce a distributed completion dependency.
- Consumers that need fresh derived state must support canonical refetch or
  reconciliation rather than relying exclusively on event delivery.
- A future guaranteed-delivery requirement remains explicit instead of silently
  changing the delivery contract of existing lifecycle events.
- Preparatory implementation can remain reviewable without exposing two production
  lifecycle authorities.
- Final cutover removes legacy direct-delete and domain-specific lifecycle branches
  instead of preserving them as rollback code.
- Existing unstarted purge work adopts the current participant contract lazily at
  irreversible fencing rather than requiring a bulk progress-row backfill.
