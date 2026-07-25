---
title: "Team Session Execution Boundaries Requirements"
created: 2026-07-24
updated: 2026-07-24
tags: [session, authorization, engine, security]
document_role: primary
document_type: requirements
snapshot_id: session-260724
---

# Team Session Execution Boundaries Requirements

- Snapshot: `session-260724`
- Document reference: `session-260724/REQ`

## Confirmation Status

The requester confirmed this complete Requirements snapshot on 2026-07-24 after reviewing the Team
Session User-dependency audit and every identified User-information usage category. ADR and Design
work may proceed from this snapshot.

## Problem

Azents currently copies the User associated with some Session wake-ups into shared Engine, Worker,
Toolkit, Memory, file, Artifact, provider-output, continuation, and subagent paths. That User is not a
stable property of a Team Session. Different Workspace members can submit different inputs, while
External Channel, recovery, continuation, and agent-originated work may have no Azents User at all.
Using the wake-up User as ambient execution context therefore makes one Team Session behave
differently by invocation source and mixes request authorization, input authorship, personalization,
credential selection, and resource access.

At the same time, removing User checks indiscriminately would allow unauthorized callers to trigger or
read Team Session work and would erase who sent each message. Team Sessions need separate boundaries
for requester authorization, durable per-message sender metadata, internal workload authority,
Team-owned resources and capabilities, and optional User-specific behavior reserved for a future
User Session.

## Primary Actor

A Workspace member collaborating with other members through a Team Session.

## Primary Scenario

A Workspace member submits an input to a Team Session. Azents authenticates the requester and verifies
current Team Session access before creating any durable input or execution side effect. The accepted
input becomes a durable message whose sender metadata identifies that authenticated User. The Team
Session then executes through its Engine, Worker, Runtime, Team-scoped Tools, files, recovery,
continuation, and subagents without a User in execution context. Generated results belong to the Team
Session, and each later user-facing view or download is authorized for its current requester
independently.

## Supporting Scenarios

- Different Workspace members submit inputs to the same Team Session, and each durable input retains
  its own sender metadata without changing shared Session execution behavior.
- An accepted human attachment is later promoted and consumed even if execution resumes without the
  original sender or that User is no longer the current requester.
- A verified External Channel invocation retains provider-principal sender metadata and executes in
  the linked Team Session without an Azents User.
- A recovery worker, idle continuation, or subagent resumes authorized Team Session work without
  reconstructing, choosing, or impersonating a User.
- A future User Session has a durable associated User, but only User-specific capabilities such as
  User Memory or User-brought Tools require and consume that identity.

## User Relationship Model

User identity has three independent roles. None may be inferred from another.

| Role | Meaning | Authority |
|---|---|---|
| Current requester or viewer | The authenticated User attempting to send, mutate, control, view, subscribe to, or download Team Session data. | Determines whether the current user-facing operation is admitted. |
| Message sender | Immutable metadata describing who sent one already-admitted durable input message. A human sender may reference an Azents User; provider, Agent, and system messages use their own sender representation. | Message metadata only. It has no relationship to why execution runs and grants no execution, capability, resource, or result-access authority. |
| Session-associated User | The durable User for whom a future User Session exists. Team Sessions have no associated User. | Supplies identity only to explicitly User-specific capabilities such as User Memory and User-brought Tools, independently of who sent or currently views a message. |

## Goals

- Make Team Session execution independent of any User identity.
- Preserve who sent each durable message as source metadata, using an authenticated User reference
  only for human-originated messages.
- Keep user-facing execution, mutation, viewing, and download access authenticated and authorized.
- Make internal execution depend on canonical Session and workload authority rather than wake-up
  hints or a borrowed User.
- Make a wake-up a pure work-availability signal rather than an execution-data envelope.
- Make Team-scoped Tools, credentials, files, artifacts, model input/output, recovery, continuation,
  External Channel, and subagent behavior consistent across invocation sources.
- Establish a boundary that can later support User Sessions without changing Team Session semantics.

## Non-Goals

- Implementing User Session storage, routing, private visibility, primary-session selection, or UX.
- Allowing anonymous callers or unauthorized Workspace users to execute, view, mutate, or download a
  Team Session.
- Changing the current Workspace-shared visibility model of Team Sessions.
- Making User Memory, User-brought Tools, personal OAuth credentials, account data, or other
  User-owned capabilities available in Team Sessions by borrowing a message sender or requester.
- Removing sender metadata from durable input messages or separate audit metadata from public
  operations where the product records it.
- Weakening Workspace, Agent, Session tree, External Channel grant, worker ownership, Run lineage, or
  Runtime isolation.
- Preserving legacy fallback behavior that synthesizes or guesses a User.

## Requirements

### REQ-1. Authorize every user-facing Team Session boundary

Every user-facing request to execute, mutate, control, view, subscribe to, or download Team Session
resources must authenticate the current requester and verify current access before creating or
revealing side effects.

**Acceptance criteria**

- An unauthenticated or unauthorized User cannot create an input, action, command, retry, stop,
  mutation, subscription, view, or download for the Team Session.
- Authorization occurs before creating an InputBuffer, pending command, Run, broker wake-up, resource
  claim, or equivalent durable side effect.
- Message and TurnAction composer inputs enforce the same requester-access boundary.
- A Session identifier, file identifier, previous authorship, or previous participation never grants
  access by itself.
- Losing Workspace access prevents subsequent user-facing Team Session access without changing the
  Session's internal execution identity, message sender metadata, or future User Session association.

### REQ-2. Team Session execution has no User context

After work is admitted, a Team Session has no User field or User concept in its Session, Run, Engine,
Worker, Runtime, Toolkit, Tool, scheduler, recovery, continuation, or subagent execution context.

**Acceptance criteria**

- Team Session behavior does not depend on which authorized Workspace member sent an input message.
- A Run that processes inputs from different Users does not choose one of them as the Run User.
- Recovery, continuation, External Channel, handover, and subagent paths expose the same Team-scoped
  capabilities as a web-originated path.
- Internal callers do not substitute an empty-string User, Agent creator, Workspace owner, grant
  approver, current viewer, message sender, or pending-command requester as execution User.
- Transient wake-up and stop signals carry only the minimum routing identity needed to notify the
  target Session. They carry no requester, sender, associated User, Agent, Workspace, interface,
  prompt, capability, or execution context.

### REQ-3. Each durable message retains sender metadata

Each durable input message must retain immutable metadata describing who sent it. An authenticated
User reference is one possible human sender representation, not a shared Actor or execution User.

**Acceptance criteria**

- Messages from different Users in the same Session or Run retain their respective sender User
  references after buffer promotion, reload, and recovery.
- Human message, action, and command sender metadata comes from the authenticated admission boundary,
  not a client-supplied identity field.
- Sender metadata survives deletion of transient buffering records.
- External provider messages identify their provider principal, agent-authored messages identify
  their sending Agent, and system-generated input messages identify themselves as system messages.
  Recovery, continuation, and wake-up operations do not acquire sender metadata merely because they
  cause work to run.
- Processing one message never changes another message's sender or establishes a current User for
  later execution.
- Sender metadata describes only who sent that input message and is not used for Tool, resource,
  personalization, credential, or execution access.
- The authenticated requester or viewer for a later operation is evaluated independently of stored
  sender metadata.

### REQ-4. Internal execution uses canonical, fail-closed workload authority

Every internal Team Session execution must be traceable to admitted durable work and valid canonical
Session lineage rather than to a User identity or unverified wake-up metadata.

**Acceptance criteria**

- The executing Agent, Workspace, Session tree, and Run are derived from and validated against the
  claimed active Team Session and its durable relationships.
- A wake-up communicates only that durable work may be available. No wake-up field supplies or
  overrides an execution fact or authority.
- Request-specific prompts, interface metadata, and other work inputs are durably admitted before the
  signal is sent and are loaded from that durable work rather than from the signal.
- A broker producer cannot cause one Agent or Workspace to execute against another Session by
  supplying identifiers or context in a wake-up.
- Web-originated work exists only after REQ-1 succeeds.
- External Channel work exists only after provider authenticity, connection, route, grant, binding,
  invocation-batch, and Session association checks succeed.
- Worker, scheduler, recovery, and continuation work executes only after the relevant durable owner,
  generation, lease, active-state, Run, or work claim succeeds.
- Subagent work executes only through valid root tree, parent Run, target SessionAgent, and durable
  mailbox or Run lineage.
- Invalid, inactive, archived, stale, cross-Session, or cross-Workspace work fails closed before Tool
  or model execution.

### REQ-5. Accepted input resources and generated resources are Session-owned

Resources accepted for or created by Team Session execution must use their canonical Workspace,
Agent, Session, root-tree, Run, Tool-call, or input-claim ownership and must not require a User owner
solely because the operation occurs during a Team Session.

**Acceptance criteria**

- Human uploads are authorized and claimed with the authenticated sender during input admission.
- After a successful claim, attachment promotion and model-input preparation use the claimed
  Session/root ownership without reauthorizing or impersonating the original sender.
- Agent-generated Exchange files, Artifacts, ModelFiles, provider outputs, and equivalent resources can
  be created, materialized, imported, and retained without a User.
- Generated-resource creator metadata identifies its human sender, Agent, Run, Tool call, provider
  response, or system operation as applicable without requiring a Human User creator.
- Transcript FileParts remain available to later Team Session model calls after recovery or a
  different member's input.
- Removing a human message sender from the Workspace does not invalidate already accepted Team
  Session-owned work or resources.
- User-facing view and download operations still require REQ-1 authorization for the current viewer.

### REQ-6. Team-scoped capabilities do not require a User

Capabilities whose semantics are Workspace-, Agent-, Session-, Run-, Runtime-, Toolkit-, or
system-scoped must remain available in a Team Session without User identity.

**Acceptance criteria**

- Workspace Toolkit configurations, attached Agent Toolkits, toolkit-level OAuth connections, and
  Workspace LLM integrations resolve from their canonical shared configuration.
- Runtime process and file operations, Agent-scoped shared Memory, Team Session files, Artifacts,
  ModelFiles, provider output, and equivalent shared capabilities do not become unavailable because a
  User is absent.
- Session-managed Toolkit lifecycle is stable when different Users submit inputs or when execution
  resumes from a Userless path.
- Agent-scope Memory remains available in Team Sessions.
- A capability that is intrinsically User-specific is unavailable in a Team Session and never selects
  a User from the latest message sender, wake-up, Agent creator, Workspace owner, approver, or viewer.
- Legacy MCP per-user OAuth and GitHub per-user PAT modes are not valid Team Session capabilities and
  are not retained as fallback credential paths.

### REQ-7. User-specific capabilities and future User Sessions remain separate

The Team Session contract must preserve a separate future model in which a User Session has a durable
Session-associated User and only explicitly User-specific capabilities consume it.

**Acceptance criteria**

- Team Session type, per-message sender metadata, request viewer, and future User Session association
  remain distinct concepts.
- User-scope Memory and future User-brought Tools are unavailable in Team Sessions.
- The Team Session migration does not encode a message sender, wake-up User, nullable ambient User, or
  latest requester as the future User Session ownership model.
- A future User Session's associated User does not change when another authorized User sends or views
  a message in that Session.
- Future User Memory and User-brought Tool access can use a User Session's durable associated User
  without changing Team Session execution behavior.
- User-brought Tools are the only future model for personal Tool credentials. Removed MCP per-user
  OAuth and GitHub per-user PAT models are not revived or adapted as compatibility paths.
- No User Session persistence, routing, authorization, or UX is required in this snapshot.

### REQ-8. Valid Team Session output is not lost because User context is absent

A valid Team Session model or Tool result must not be discarded, retried, or made inaccessible solely
because no User exists in execution context.

**Acceptance criteria**

- Responses containing generated text, reasoning, Tool calls, files, Artifacts, ModelFiles, provider
  files, or attachments are admitted when their Session workload authority and resource lineage are
  valid.
- A valid provider-generated file does not convert an otherwise successful model response into a
  User-authentication failure.
- MCP and other Tool-generated binary output can be captured under Session/Run/Tool-call authority.
- Retry behavior does not repeat successful provider-side generation solely because ambient User
  context is absent.
- Failures identify the actual invalid Session authority, resource ownership, capability, or storage
  condition instead of claiming that a Team Session generally requires a User.

## Fixed Constraints

- Every currently implemented AgentSession in this snapshot follows Team Session execution semantics;
  User Sessions remain unimplemented.
- Team Session execution has no ambient User identity.
- A Session wake-up is a pure work-availability signal with only the minimum routing identity; all
  execution data and authority come from durable Session and workload state.
- Every durable input message retains sender metadata. Authenticated human identity appears only as
  the human-sender variant for that specific admitted message.
- Sender metadata answers only who sent an input message. There is no initiating User or User that
  caused internal execution, and sender metadata never grants execution, capability, resource, or
  result-access authority.
- Public control operations may keep separate requester audit metadata, but that metadata is not
  message sender metadata and never enters execution context.
- Current requester authorization, per-message sender metadata, and a future User Session's associated
  User are independent relations and are never inferred from one another.
- Legacy MCP per-user OAuth and GitHub per-user PAT runtime paths are removed rather than preserved.
  Future personal Tool credentials belong to the User-brought Tool model.
- User-facing execution and result access remain authenticated and authorized.
- Internal authority is derived from canonical durable Session and workload state and cannot be
  granted by supplying identifiers alone.
- User-specific capability authority is never inferred from Team Session participation or input
  authorship.
- External provider identity remains distinct from Azents User identity unless a separate product
  contract explicitly links them.
- No legacy fallback, synthetic User, or empty-string User compatibility path is introduced.
- Git-tracked artifacts and operator-facing errors remain in English.

## Open Assumptions

- None. Repository-specific implementation choices and migration details belong in the ADR and Design
  after this Requirements snapshot is confirmed.

## Confirmation

The requester confirmed the Team Session and future User Session execution-context premise on
2026-07-24. The requester also confirmed on 2026-07-24 that input identity is represented only as
per-message sender metadata rather than as an Actor or execution User. The requester confirmed the
three independent User relations—current requester authorization, message sender metadata, and future
User Session association—on 2026-07-24. The requester further confirmed that attachment access is
checked at input admission and that an accepted attachment becomes a Session resource without later
reauthorization through its human sender. The requester confirmed that `SessionWakeUp` is a pure
signal and must not transport execution information beyond the minimum Session routing identity.
The requester also confirmed that legacy MCP per-user OAuth and GitHub per-user PAT behavior is
removed, and that future personal Tool credentials are redesigned as User-brought Tools associated
with a User Session. The requester confirmed that Agent-, Tool-, Provider-, and system-generated
resources are owned by Session workload lineage and use source metadata rather than a required Human
User creator. The requester clarified that there is no User who initiated or caused internal
execution: User identity on an input message means only that message's sender. The requester
confirmed that a future User Session's associated User is available only to capabilities explicitly
defined as User-owned, currently User Memory and future User-brought Tools, and that generic execution
layers have no `user_id`. The requester confirmed the complete Requirements snapshot on 2026-07-24.
