---
title: "Team Session Execution Boundaries"
created: 2026-07-24
tags: [session, authorization, engine, security, architecture]
document_role: primary
document_type: adr
snapshot_id: session-260724
---

# Team Session Execution Boundaries

- Snapshot: [session-260724/REQ](../requirements/session-260724-team-session-execution-boundaries.md)
- Document reference: `session-260724/ADR`

## Context

The confirmed Requirements separate three independent User relations:

1. the authenticated requester or viewer for one public operation;
2. immutable sender metadata on one admitted input message; and
3. the durable associated User of a future User Session.

A Team Session has no associated User and no User field in its execution layers. Message sender
metadata is unrelated to execution. A Session wake-up is a pure work-availability signal. Internal
execution derives authority and context from durable Session and workload state. Accepted input
resources and generated resources belong to Session workload lineage. Explicitly User-owned
capabilities remain unavailable in Team Sessions.

The supporting
[Team Session User Dependency Audit](../design/session-user-dependency-audit-2026-07-24.md)
records the current dependency paths and correctness gaps. This ADR records only hard-to-reverse
implementation decisions needed to satisfy the confirmed Requirements and does not reopen the
product contracts fixed by `session-260724/REQ`.

## Decision Topics

The requester confirmed this complete discussion backlog before individual decision review:

1. **Team Session and User Session persistence model**: how Session kind and the durable
   Session-associated User are represented.
2. **Execution context separation**: how generic `user_id` is removed and an associated User reaches
   only explicitly User-owned capabilities.
3. **Input-message sender model**: how Human User, External Provider, Agent, and System senders are
   represented on durable input messages.
4. **Execution-context construction after a pure wake-up**: where Worker execution derives canonical
   Session, Agent, Workspace, Run, prompt, interface, and admitted work data.
5. **Input and attachment admission boundary**: the transaction boundary for message creation, sender
   recording, file authorization, Session claim, promotion, and recovery.
6. **Session-owned resource model**: ownership and creator/source representation for ExchangeFile,
   ModelFile, Artifact, and provider output.
7. **Migration and cutover**: the removal order for ambient User carriers and User-required schemas
   without parallel compatibility or fallback paths.

The topics are reviewed in this dependency order. Reversible implementation details such as class
names, module placement, logging fields, ordinary test fixture layout, and removal of unused
parameters are handled in Design rather than elevated into ADR decisions.

## Decisions

### session-260724/ADR-D1. Root AgentSession owns the future User Session association

Affected requirements:
[session-260724/REQ-2](../requirements/session-260724-team-session-execution-boundaries.md#req-2-team-session-execution-has-no-user-context),
[session-260724/REQ-6](../requirements/session-260724-team-session-execution-boundaries.md#req-6-team-scoped-capabilities-do-not-require-a-user),
and
[session-260724/REQ-7](../requirements/session-260724-team-session-execution-boundaries.md#req-7-user-specific-capabilities-and-future-user-sessions-remain-separate).

The current snapshot does not add User Session persistence, routing, authorization, or UX. Every
currently implemented `AgentSession` continues to have Team Session execution semantics.

When a future snapshot implements User Sessions, the root `AgentSession` is the authoritative owner
of the product Session kind and its durable associated User. Subagent `AgentSession` rows derive that
association through their root `SessionAgent` lineage and do not duplicate it.

The existing `agent_sessions.session_kind` remains the `root` versus `subagent` tree/listing
classification. The existing `agent_sessions.primary_kind` remains the primary-conversation role and
is not overloaded with Team versus User Session semantics.

`SessionAgentContext` remains the shared root-tree Runtime, Project, and Worktree resource context. It
does not own the product identity of a User Session.

This keeps the future User association on the conversation aggregate, prevents root/subagent drift,
and avoids speculative User Session columns in the current Team-only snapshot.

Rejected alternatives:

- Storing the association on `SessionAgentContext` would mix product Session identity with a shared
  Runtime-resource context and require public Session queries to join that context.
- Duplicating the associated User on every root and subagent `AgentSession` would create multiple
  writable copies and permit tree-level drift.

### session-260724/ADR-D2. Resolve User-owned capabilities outside generic execution contexts

Affected requirements:
[session-260724/REQ-2](../requirements/session-260724-team-session-execution-boundaries.md#req-2-team-session-execution-has-no-user-context),
[session-260724/REQ-6](../requirements/session-260724-team-session-execution-boundaries.md#req-6-team-scoped-capabilities-do-not-require-a-user),
and
[session-260724/REQ-7](../requirements/session-260724-team-session-execution-boundaries.md#req-7-user-specific-capabilities-and-future-user-sessions-remain-separate).

Generic execution types, including `InvokeInput`, `RunContext`, `ToolkitContext`, `ResolveContext`,
and `TurnContext`, do not carry a User identity. Message sender metadata never enters these contexts.
Session behavior is not classified as User or System from the presence of a User field.

Team Sessions project only Workspace-, Agent-, Session-, Run-, Runtime-, Toolkit-, and system-scoped
capabilities. They do not invoke a User-capability projection path.

A future User Session invokes a separate User-capability resolver with the durable associated User
owned by its root `AgentSession`. That resolver may construct explicitly User-owned capabilities,
currently User Memory and future User-brought Tools. The constructed capability captures the identity
it requires without exposing that identity to the Engine, ordinary Toolkits, or per-turn contexts.

This makes access to a User identity an explicit capability registration boundary rather than an
ambient nullable field available to every provider.

Rejected alternatives:

- Adding `UserCapabilityContext | None` to the generic Toolkit resolution contract would leave every
  Toolkit able to depend on User identity and preserve an ambient nullable path in Team Sessions.
- Allowing each User-owned capability to resolve the associated User independently from `session_id`
  would duplicate root-lineage lookups and hide inconsistent Session-ownership dependencies inside
  individual implementations.

### session-260724/ADR-D3. Each input-message kind owns its sender metadata

Affected requirements:
[session-260724/REQ-2](../requirements/session-260724-team-session-execution-boundaries.md#req-2-team-session-execution-has-no-user-context),
[session-260724/REQ-3](../requirements/session-260724-team-session-execution-boundaries.md#req-3-each-durable-message-retains-sender-metadata),
and
[session-260724/REQ-7](../requirements/session-260724-team-session-execution-boundaries.md#req-7-user-specific-capabilities-and-future-user-sessions-remain-separate).

Sender metadata remains part of the concrete durable input-message payload rather than becoming a
shared Actor, execution principal, or normalized sender aggregate.

Human-authored durable input messages store `sender_user_id`. The transient
`InputBuffer.actor_user_id` concept is removed or renamed to represent only this Human message-sender
field, and buffer promotion copies it into the durable Human input-message payload before the buffer
is deleted.

Agent-authored messages continue to identify their sender through the existing
`AgentMessagePayload` source SessionAgent and Run fields. External Channel messages continue to use
the existing provider, principal, provider-user, display-name, and author-type fields.
System-generated input messages identify themselves through their concrete event kind and payload.
Recovery, continuation, and wake-up operations do not receive sender metadata merely because they
cause work to run.

A shared sender shape may be produced by read or UI projection code when needed, but it is not the
durable source model.

Rejected alternatives:

- A common tagged sender union would duplicate existing Agent and External message source fields and
  risk recreating a generic Actor abstraction.
- A separate message-sender table would add a join and lifecycle aggregate for metadata that belongs
  to exactly one message while still duplicating the existing variant-specific payloads.

### session-260724/ADR-D4. Build one canonical execution snapshot after Session ownership claim

Affected requirements:
[session-260724/REQ-2](../requirements/session-260724-team-session-execution-boundaries.md#req-2-team-session-execution-has-no-user-context),
[session-260724/REQ-4](../requirements/session-260724-team-session-execution-boundaries.md#req-4-internal-execution-uses-canonical-fail-closed-workload-authority),
and
[session-260724/REQ-6](../requirements/session-260724-team-session-execution-boundaries.md#req-6-team-scoped-capabilities-do-not-require-a-user).

`SessionWakeUp` carries only the minimum Session routing identity. The Session owner-generation claim
is the first execution-authority fence after a wake-up.

After that claim, one canonical context-loading boundary reloads and validates the active
`AgentSession`, Agent, Workspace, root `SessionAgent` tree, `SessionAgentContext`, owner generation,
and the relevant durable InputBuffer, pending command, AgentRun, or External Channel work. It
produces an immutable execution snapshot consumed by RunExecutor and Toolkit preparation.

Agent ID, Workspace ID and handle, root lineage, execution mode, interface/source metadata, requested
inference data, and prompt inputs come from their canonical durable records rather than from the
broker signal. The currently unused transient `additional_system_prompt` field is removed. Any future
request-specific prompt or interface input must be durably admitted before wake-up.

The loader composes existing durable aggregates rather than introducing a generic
`session_work_items` table that would duplicate InputBuffer, pending-command, and AgentRun state.
Domain-specific loaders may remain separate internally, but the Worker consumes one validated
snapshot and does not perform independent identity lookups throughout execution.

Rejected alternatives:

- A generic work-envelope table would create overlapping lifecycle and claim state beside the
  existing durable work records.
- Independent lazy lookups by RunExecutor, Toolkit providers, and resource services would permit
  inconsistent snapshots and repeated or missing lineage validation.

### session-260724/ADR-D5. Atomically admit sender-bearing input and root-owned attachments

Affected requirements:
[session-260724/REQ-1](../requirements/session-260724-team-session-execution-boundaries.md#req-1-authorize-every-user-facing-team-session-boundary),
[session-260724/REQ-3](../requirements/session-260724-team-session-execution-boundaries.md#req-3-each-durable-message-retains-sender-metadata),
[session-260724/REQ-4](../requirements/session-260724-team-session-execution-boundaries.md#req-4-internal-execution-uses-canonical-fail-closed-workload-authority),
[session-260724/REQ-5](../requirements/session-260724-team-session-execution-boundaries.md#req-5-accepted-input-resources-and-generated-resources-are-session-owned),
and
[session-260724/REQ-8](../requirements/session-260724-team-session-execution-boundaries.md#req-8-valid-team-session-output-is-not-lost-because-user-context-is-absent).

The authenticated requester is reauthorized inside the admission transaction while the target active
Team Session and its root lineage are locked. Public-route prevalidation may remain for response
mapping, but it is not the transaction's authorization evidence.

One admission transaction validates the Agent, Workspace, Session, root lineage, current requester
access, idempotency identity, and all referenced ExchangeFiles; creates the InputBuffer with its
Human `sender_user_id`; atomically binds the referenced source and preview files to the root Session
retention owner; and marks the Session eligible to run. The transaction commit is the acceptance
point. Any validation, conflict, or claim failure rolls back all of those effects.

An idempotent retry resolves to the same accepted input only when its canonical sender, content,
attachments, action, inference request, and other admitted data match. Reusing an idempotency key
with different admitted data fails as a conflict rather than silently returning or modifying the
previous input.

The pure Session wake-up is published only after the admission commit and is not part of that
transaction. A notification failure does not revoke or delete accepted work. Repeated idempotent
notification attempts and the existing durable stuck-Session recovery path may re-enqueue the
Session without duplicating the input. Exact public response and immediate retry mechanics for a
post-commit notification failure belong in Design, but they must represent it as a delivery delay
rather than an admission rollback.

After owner-generation and FIFO claims, Worker promotion resolves an attachment only through its
Workspace, Agent, and root-Session retention ownership. It never reauthorizes through the stored
Human sender. ModelFiles created from accepted input use Session, input, and Run lineage. Promotion
copies `sender_user_id` and the prepared FileParts into the durable message event, associates the
event with the Run when applicable, and deletes the InputBuffer in one transaction.

Attachment preparation that performs object-storage work remains retryable outside the promotion
transaction. If preparation or the subsequent FIFO revalidation fails, the InputBuffer and root
claim remain durable, partially created ModelFiles are discarded, and a later attempt may safely
retry. Sender removal or loss of Workspace membership after admission does not invalidate that
already accepted work.

Rejected alternatives:

- Adding a transactional wake-up outbox would introduce a second delivery lifecycle for a
  non-authoritative hint while the durable Session state and stuck-Session recovery already provide
  the recovery source.
- A two-stage pending-admission state machine that materializes attachments before final acceptance
  would add an orphanable lifecycle, external-storage compensation, and request latency without
  improving the canonical Session ownership boundary.

### session-260724/ADR-D6. Keep resource-specific ownership and typed provenance

Affected requirements:
[session-260724/REQ-1](../requirements/session-260724-team-session-execution-boundaries.md#req-1-authorize-every-user-facing-team-session-boundary),
[session-260724/REQ-4](../requirements/session-260724-team-session-execution-boundaries.md#req-4-internal-execution-uses-canonical-fail-closed-workload-authority),
[session-260724/REQ-5](../requirements/session-260724-team-session-execution-boundaries.md#req-5-accepted-input-resources-and-generated-resources-are-session-owned),
[session-260724/REQ-6](../requirements/session-260724-team-session-execution-boundaries.md#req-6-team-scoped-capabilities-do-not-require-a-user),
and
[session-260724/REQ-8](../requirements/session-260724-team-session-execution-boundaries.md#req-8-valid-team-session-output-is-not-lost-because-user-context-is-absent).

The persistence model retains each resource type's canonical ownership and lifecycle rather than
introducing a polymorphic `session_resources` aggregate. What is shared is the internal authority
validation contract derived from the canonical execution snapshot, not one universal owner or
creator schema.

An ExchangeFile is scoped by Workspace and Agent and, after input admission or when created as
Session output, is retained by the root AgentSession. A Human upload may exist temporarily as an
unbound Workspace-and-Agent-scoped resource before admission. Generated ExchangeFiles and their
derived previews are bound to the current root Session when created.

The required `created_by_user_id` field is replaced by typed creation provenance. Human upload
provenance may reference the authenticated uploader. Agent, Tool, provider, and system output
provenance records the applicable creating Session, Run, Tool or provider call, output position, or
system operation without borrowing a User. Provenance is not ownership or access authority. Exact
columns, enums, constraints, and derived-preview representation belong in Design.

A ModelFile remains owned by its Workspace, Agent, and exact AgentSession, with its input, Run, or
generated-output source recorded through the ModelFile's applicable lineage. Creation,
materialization, and internal download validate Session and Run authority and do not require a User.

An Artifact retains its existing Workspace, AgentSession, AgentRun, and optional Tool-call lineage.
Internal Artifact creation and resolution use that lineage without requester authorization.

A transcript FilePart is a durable reference rather than a resource owner. Its referenced ModelFile
must belong to the valid Session lineage for the event and Run that consume it, including after
recovery.

Internal ExchangeFile, ModelFile, and Artifact operations accept validated Session workload
authority. User-facing upload, view, download, and delete operations independently authenticate and
authorize the current requester. A stored uploader, creator, sender, Run, Tool call, or previous
viewer never grants public access.

Resource retention and archived-Session cleanup continue to follow the resource's root-Session or
exact-Session lifecycle. Provenance does not change retention ownership.

Rejected alternatives:

- A common `session_resources` table would duplicate the existing resource identities and lifecycle
  state, require cross-table admission transactions, and force distinct Exchange, ModelFile, and
  Artifact retention semantics into one aggregate.
- Making `created_by_user_id` nullable while storing non-Human sources only in free-form metadata
  would not enforce source identity, would preserve the misleading generic creator concept, and
  would allow provenance to be reused accidentally as authority.

### session-260724/ADR-D7. Deploy one coordinated clean cutover without runtime compatibility

Affected requirements:
[session-260724/REQ-2](../requirements/session-260724-team-session-execution-boundaries.md#req-2-team-session-execution-has-no-user-context),
[session-260724/REQ-3](../requirements/session-260724-team-session-execution-boundaries.md#req-3-each-durable-message-retains-sender-metadata),
[session-260724/REQ-4](../requirements/session-260724-team-session-execution-boundaries.md#req-4-internal-execution-uses-canonical-fail-closed-workload-authority),
[session-260724/REQ-5](../requirements/session-260724-team-session-execution-boundaries.md#req-5-accepted-input-resources-and-generated-resources-are-session-owned),
[session-260724/REQ-6](../requirements/session-260724-team-session-execution-boundaries.md#req-6-team-scoped-capabilities-do-not-require-a-user),
and
[session-260724/REQ-8](../requirements/session-260724-team-session-execution-boundaries.md#req-8-valid-team-session-output-is-not-lost-because-user-context-is-absent).

The implementation may be prepared through multiple reviewed PRs, but the operational transition is
one coordinated cutover. Old and new execution semantics are not deployed concurrently.

Before migration, public and External Channel input admission is paused, Worker and scheduler
processes are drained to durable recovery boundaries, and a database backup is taken. Active or
pending work remains represented by AgentSession, InputBuffer, pending-command, AgentRun, and
SessionAgent lineage.

Only new forward migrations are created. Executed migrations are never modified. Migration files are
generated through the repository Alembic workflow and then completed with the required deterministic
data migration and constraints.

Pending Human InputBuffers preserve their sender by renaming or directly migrating
`actor_user_id` to `sender_user_id`. Existing durable Human message payloads are backfilled only when
an authoritative persisted relation identifies their sender. A historical message whose sender
cannot be reconstructed records unavailable sender provenance explicitly and does not infer a User
from the Agent creator, Workspace owner, current viewer, attachment uploader, or any other relation.
Only pre-cutover historical messages may lack a Human sender reference; every newly admitted Human
message requires one.

Existing ExchangeFile uploads preserve the authenticated uploader as Human provenance. Existing
generated files are backfilled from durable Session, Run, Tool, provider-output, and root-retention
relationships when those sources are authoritative. Rows whose exact generating source cannot be
reconstructed receive explicit migration provenance rather than a fabricated User or Run. The
required `created_by_user_id` ownership constraint is removed after provenance migration.

The application cutover removes ambient User fields, legacy internal resource APIs, User-qualified
Toolkit lifecycle keys, and old broker payload handling. It writes only the new sender and resource
provenance models and accepts only the pure Session wake-up and stop-signal contracts. There is no
dual-write, old-field read fallback, nullable execution User, or version-dispatch path.

Old Redis broker messages are discarded rather than decoded through a compatibility adapter.
Pending InputBuffers, pending commands, recoverable AgentRuns, stop intent, and running Sessions are
rediscovered from the database and re-enqueued as pure Session wake-ups. Recovered work claims a new
owner generation and rebuilds its canonical execution snapshot and Session-managed Toolkits.

Rollback after the cutover begins uses the pre-cutover database backup, previous application images,
and reconstructed broker notifications. The previous application is not started against database
state written by the new model.

Rejected alternatives:

- An expand-and-contract rolling deployment would require dual-read, dual-write, versioned broker
  payloads, or execution fallbacks and would permit old Workers to interpret newly admitted work
  under the wrong authority model.
- Deleting existing Sessions, message history, or file resources to avoid migration would violate
  the durable work, recovery, and resource-preservation requirements.
