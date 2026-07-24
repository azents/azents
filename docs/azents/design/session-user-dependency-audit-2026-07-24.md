---
title: "Team Session User Dependency Audit"
created: 2026-07-24
tags: [session, authorization, engine, security, audit]
document_role: supporting
document_type: supporting-audit
---

# Team Session User Dependency Audit

## Purpose

This audit classifies every User dependency found on the actual Team Session admission, execution,
resource, continuation, and result-access paths before the `session-260724` Requirements snapshot is
confirmed. It does not decide the final architecture. It identifies which User dependencies express a
real product boundary and which ones are accidental coupling to the User that happened to wake a
Session.

The raw AST inventory found 429 function parameters related to User identity across the Python
application. A bounded review reduced that set to 157 production functions in Session-relevant API,
service, Engine, Worker, file, and External Channel areas. The table below groups helpers that share
one semantic dependency and records the authoritative source and required disposition for each group.

## Confirmed Product Premise

- A Team Session has no User in its execution context.
- An authenticated User is still required at user-facing Team Session request and result-read
  boundaries.
- Every durable input retains sender metadata describing who sent that message.
- A human sender references the authenticated requester. External, system, and agent-authored input
  messages use their own sender representation and do not acquire an Azents User by fallback.
- Recovery, continuation, wake-up, and other internal execution operations have no initiating User
  and do not receive sender metadata unless they create an actual durable input message.
- Human attachment access is checked when the input is admitted. Once accepted, the attachment is a
  Session resource and later execution does not reauthorize it through the human sender.
- A Session wake-up is a pure work-availability signal. Except for the minimum Session routing
  identity, it does not transport execution data or authority.
- Agent-, Tool-, Provider-, and system-generated resources belong to Session workload lineage. Their
  creator metadata records the actual source and does not require or borrow a Human User.
- A future User Session may carry a durable Session-associated User, but only User-specific
  capabilities explicitly defined as User-owned consume it. The currently identified capabilities
  are User Memory and future User-brought Tools; generic execution layers have no `user_id`.

## Confirmed User Relationship Model

| Relation | Source and lifetime | Meaning |
|---|---|---|
| Current requester or viewer | The authenticated User for one public request or WebSocket connection. | Determines whether that user-facing operation may send, mutate, control, view, subscribe to, or download Session data. |
| Message sender | Immutable metadata on one durable input message. A human sender references an Azents User; provider, Agent, and system messages use their own sender representation. | Answers only who sent that message. It has no relationship to why execution runs and is not execution, capability, resource, or result-access authority. |
| Session-associated User | A durable relation belonging only to a future User Session. A Team Session has none. | Supplies identity to explicitly User-specific capabilities such as User Memory and User-brought Tools regardless of who sent or currently views a message. |

These relations are independent. Current access does not follow from previous authorship, message
sender metadata does not select an execution User, and a future User Session's associated User does
not change when another authorized User sends or views a message.

## Classification Legend

| Classification | Meaning |
|---|---|
| Request authorization | Authenticated requester admission at a public mutation or control boundary. |
| Result-read authorization | Authenticated viewer admission for history, live state, or download. |
| Message metadata / request audit | Sender metadata for one input message or separate requester audit data for one public operation. Neither represents a User who caused internal execution. |
| Input-owned data admission | Use of the authenticated requester to validate and claim resources submitted with that input. |
| User-owned data | Data whose domain ownership is intrinsically one User. |
| Credential selection | Selection of a credential or external grant that belongs to a User. |
| Personalization | User-specific behavior such as User Memory. |
| Provider identity | External provider principal, distinct from an Azents User. |
| Execution authority | Durable authority to perform already-admitted Session work. |
| Accidental coupling | User identity is used where Session, Run, Workspace, Agent, or workload lineage is authoritative. |

Disposition terms are `retain`, `replace`, `separate`, `nullable`, and `remove`.

## Principal Carrier Findings

| Carrier | Current source and lifetime | Finding |
|---|---|---|
| `InputMessage.user_id` | Copied from the REST requester before buffering. | It is not read by production Session execution. The authenticated requester is separately passed to the service, so this field is duplicate and currently dead. |
| `InputBuffer.actor_user_id` | Stored for human-originated buffers until promotion deletes the row. | It currently identifies a human sender, but cannot represent provider, agent, and system senders. It is also borrowed for delayed file authorization and is not copied into durable message sender metadata. |
| `SessionWakeUp` payload | Currently contains `agent_id`, `session_id`, `user_id`, `additional_system_prompt`, `interface`, `workspace_id`, and `workspace_handle`. | Only the minimum Session routing identity belongs in the signal. Every other field improperly makes the wake-up an execution-data envelope. |
| `InvokeInput.user_id` | Copied from `SessionWakeUp.user_id`. | The worker creates it with no messages; its attachment branch is not the current buffered-input path. It remains an ambient execution User carrier. |
| `RunContext.user_id` | Copied from `SessionWakeUp.user_id` for the full Run boundary. | A Run can consume messages from different senders and can resume without a User, so this cannot represent a message sender or Team Session authority. |
| `ToolkitContext.user_id` / `TurnContext.user_id` / `ResolveContext.user_id` | Copied from the same wake-up User into toolkit resolution and every turn. | This causes Memory, file, artifact, MCP, subagent, and lifecycle behavior to vary by the wake-up source. Team Session execution must not populate it. |
| `SessionToolkitKey` actor suffix | `user_id` or `system` is part of the session-managed toolkit instance key. | Current registered toolkits are Workspace-owned. The suffix creates sender-dependent lifecycle instances without a sender-dependent credential contract. |

## Dependency Classification

### Public admission, control, and result access

| Area and symbols | Authoritative User source | Classification | Behavior without User | Replacement or boundary | Disposition |
|---|---|---|---|---|---|
| `get_current_user`, `ChatSessionService.get_session`, `get_agent_session`, list/history/live/context methods | Authenticated HTTP/WebSocket requester | Request authorization / result-read authorization | Public request is rejected. | Keep current requester authentication plus Workspace/Agent/Session access checks at the boundary. | retain |
| Existing-session message write: `_validate_rest_session` → `create_buffered_agent_input` | Authenticated REST requester | Request authorization | Request is rejected before buffering. | Keep authorization before any InputBuffer, Run, or broker side effect. | retain |
| TurnAction write: `_write_turn_action_via_rest` → `create_buffered_agent_action_input` | Authenticated requester is available but not checked for Workspace membership on this branch | Request authorization gap | Any authenticated User with valid identifiers can reach the service path; the service validates Session/Agent state but not membership. | Apply the same current-requester Session admission check as other composer inputs before durable side effects. | retain and fix |
| `ChatWriteService` edit, command, retry, and stop entry points | Authenticated requester after route validation | Request authorization | Internal service methods assume the caller already authorized access. | Preserve a single explicit admission boundary; do not turn the stored requester into execution context. | separate |
| `RDBChatWriteRequest.user_id` and per-user idempotency key | Authenticated requester | Request audit | User-facing idempotency cannot be scoped safely. | Retain as request ownership and idempotency metadata only. It is not an execution initiator. | retain |
| `pending_command_user_id`, `stop_requested_by`, `SessionStopSignal.user_id` | Authenticated requester for public commands/stops; nullable for system operations | Request audit versus accidental broker coupling | Commands/stops can execute from durable intent; the broker signal does not read its User. | Keep separate durable requester audit only where the product needs it. Remove User from the transient stop signal and never interpret the audit field as an execution initiator. | separate |
| WebSocket subscription | Authenticated WebSocket requester at connection | Result-read authorization | Subscription is denied. | Keep Session access validation before subscribing. | retain |
| Exchange upload/download/delete REST routes | Authenticated requester | Request authorization / result-read authorization | User-facing operation is denied. | Keep requester Workspace authorization on public upload, download, and delete. | retain |

### Message sender metadata and input-owned resources

| Area and symbols | Authoritative User source | Classification | Behavior without User | Replacement or boundary | Disposition |
|---|---|---|---|---|---|
| `InputMessage.user_id` | REST requester, duplicated beside service `user_id` | Accidental coupling / duplicate provenance | No production behavior changes because the field is not consumed. | Construct message sender metadata once at the admission service boundary. | remove |
| `InputBuffer.actor_user_id` for human message/action/setup buffers | Authenticated requester admitted for that exact input | Human sender metadata / input admission | The human sender would be unknown; attachments cannot currently be prepared. | Replace it with the human-User variant of per-message sender metadata. It must not become Session, Run, or Toolkit context. | replace |
| `InputBuffer.actor_user_id=None` for External Channel, continuation, and agent terminal result buffers | Provider, Agent, or system message sender rather than an Azents User | Sender metadata gap | A null User is correct, but the durable message may still need its actual non-User sender representation. | Persist provider principal, sending Agent, or system message type only when an actual durable input message exists. Do not assign sender metadata to continuation or execution itself. | replace |
| `InputBufferService.buffer_to_user_message` and durable `UserMessagePayload` | Should receive sender metadata from the admitted input | Provenance / audit gap | Buffer deletion permanently loses the human sender, and other source types lack one durable sender representation. | Persist sender metadata on the specific durable input-message event without placing it in execution context. | retain and fix |
| `ExchangeFileService.claim_input_attachments` | Authenticated human sender at admission | Input-owned data admission | Human upload cannot be claimed safely. | Keep requester membership and scope validation in the same transaction as input acceptance. | retain |
| Delayed attachment preparation using `buffer.actor_user_id` | Previously admitted human sender | Accidental coupling | Promotion raises for a missing User and rechecks the sender's membership after admission. Accepted work can fail if the sender is removed before promotion. | After claim, resolve by the claimed file's Agent/root-Session ownership and the worker's valid workload lineage. The original sender remains metadata only. | separate |
| External Channel `provider_user_id`, `principal_id`, grant, binding, route, and invocation batch | Verified provider event and External Channel records | Message sender metadata versus admission authority | No Azents User is expected. | Preserve the provider principal only as the admitted message's sender. Grant, binding, route, and invocation records independently determine admission and workload validity. | retain |

### Worker and Engine execution context

| Area and symbols | Authoritative User source | Classification | Behavior without User | Replacement or boundary | Disposition |
|---|---|---|---|---|---|
| `SessionWakeUp.user_id` | Latest producer that happened to enqueue a wake-up | Accidental coupling | Recovery and External Channel already pass `None`; web behavior differs from those paths. | Remove it. A wake-up identifies work availability only. | remove |
| `SessionStopSignal.user_id` | Stop producer | Accidental coupling in broker envelope | No effect; runner ignores it. | Durable stop intent retains optional requester audit. | remove |
| `InvokeInput.user_id` in worker execution | Copied from wake-up | Accidental coupling | Model/tool/file behavior becomes path-dependent. | Buffered input supplies per-input data; Team Session run resolution has no User. | remove from Team Session path |
| `RunContext.user_id` | Copied from wake-up for the whole Run | Accidental coupling | File materialization and all turn contexts lose User-dependent behavior. | RunContext carries Run authority, owner generation, tool-admission barrier, model transport, and event publication, not a Team Session User. | remove from Team Session path |
| Toolkit/turn/resolve context User | Copied from RunContext/wake-up | Accidental coupling plus future personalization hook | Memory, files, artifacts, subagents, and toolkit lifecycle vary by wake-up source. | Team Session passes no User. A future User Session obtains its User from durable Session association and exposes it only through explicit User-specific capability context. | separate |
| `SessionType.USER` / `SYSTEM` chosen from or used alongside User presence | Wake-up User presence rather than Session product type | Accidental coupling | Team web runs appear User-like while recovery appears system-like for the same Session. | Represent Team Session and future User Session semantics independently of invocation source. | separate |
| `SessionToolkitScope` actor-qualified key | Wake-up User | Accidental coupling | Toolkit instances are replaced or duplicated when senders or wake-up paths change. | Key Workspace/Agent/Toolkit-owned instances by stable Toolkit source and revision within the Session lifecycle. | remove |
| Worker owner generation, active Session/root status, InputBuffer claim, AgentRun claim, action owner generation, and SessionAgent lineage | Durable DB state plus broker ownership | Execution authority | Invalid or stale work fails closed at durable claims. | Reuse these primitives as the internal workload authority. | retain |
| `SessionWakeUp.agent_id`, `workspace_id`, `workspace_handle`, `additional_system_prompt`, and `interface` | Broker producer payload | Execution authority and durable-input gap | Producer-supplied identity is not consistently compared with the canonical Session, and request data exists only in the transient signal. | Remove these fields from the signal. Load Agent, Workspace, interface, prompt, and other execution data from the claimed Session and durably admitted work. | remove and fix |

### Memory, credentials, and Toolkits

| Area and symbols | Authoritative User source | Classification | Behavior without User | Replacement or boundary | Disposition |
|---|---|---|---|---|---|
| Agent-scope Memory list/get/search/save/delete and prompt summaries | Agent identity | Shared Agent data | Already works without User. | Continue exposing Agent scope in Team Sessions. | retain |
| User-scope Memory and User Memory prompt section | Explicit User identity | User-owned data / personalization | Correctly unavailable or omitted when User is absent. | Team Session must not select a User from message sender metadata or a wake-up. Future User Session may supply its durable associated User. | nullable and separate |
| Workspace `ToolkitConfig`, encrypted credentials, Agent attachment, and toolkit-level MCP OAuth | Workspace/Toolkit configuration | Credential selection, but not User credential selection | Runtime resolution generally works without User. | Treat attached Toolkits and their credentials as Workspace/Agent capabilities. | retain |
| GitHub Platform App installation access validation during Toolkit create/update | Authenticated manager configuring the Toolkit | Request authorization / credential admission | Configuration cannot be safely accepted. | Keep User validation at configuration time; runtime uses the admitted Toolkit credential and does not reselect the executing User. | retain |
| GitHub `GitHubSecretsPAT` stored in `ToolkitConfig.encrypted_credentials` | Workspace Toolkit configuration | Shared credential selection | Runtime resolves the same PAT without a User. | Retain only as a Workspace-shared Toolkit credential; it is not the removed GitHub per-user PAT model. | retain |
| LLM provider integrations and OAuth refresh | Workspace-owned integration | Shared credential selection | Works without User. | Resolve from the Agent's selected Workspace integration. | retain |
| `EnvVarToolkitProvider` structured log `user_id` | Wake-up User | Accidental coupling | Only the log field changes. | Log Session/Run/Workspace/Toolkit identity; do not log a Team Session execution User. | remove |
| Generic `ToolkitProvider.validate_credentials(user_id, ...)` | Authenticated Toolkit manager | Request authorization / credential admission | Configuration validation lacks requester context where provider ownership matters. | Keep this API on management paths; do not carry it into runtime resolution. | separate |
| Toolkit OAuth state `user_id` | Authenticated manager starting the connection | Management-flow residue | The exchange route ignores the verified state User and independently checks current Toolkit write permission. | Remove the unused User field unless a future explicit audit record requires it; never treat it as OAuth grant ownership. | remove |
| MCP `SessionType` selected from `ResolveContext.user_id` | Wake-up User presence | Accidental coupling | Toolkit-level MCP behavior is classified as User or System by invocation source even though credential selection is toolkit-level. | Derive Session behavior from durable Session type and remove wake-up User from MCP resolution. | remove |
| Legacy MCP per-user OAuth and GitHub per-user PAT | Historical tables, APIs, and runtime designs | Removed User-owned credential selection | Current production runtime has no `oauth2_per_user`, `mcp_oauth2_tokens`, `per_user_pat`, or `github_pats` path. | Do not restore compatibility. Preserve executed migrations and immutable historical documents, but remove any remaining live schema/API/runtime residue. | remove |
| Future User-brought Tools | Future durable User Session association | User-owned credential selection | Not implemented and unavailable in Team Sessions. | Redesign personal Tool credentials only through User-brought Tools in future User Session work. Never borrow a message sender or requester. | nullable and future |

### Runtime files, ExchangeFile, ModelFile, Artifact, and provider output

| Area and symbols | Authoritative User source | Classification | Behavior without User | Replacement or boundary | Disposition |
|---|---|---|---|---|---|
| Pure Runtime file tools: read text, write, edit, delete, glob, grep | No semantic User; parameters are unused compatibility plumbing | Accidental coupling | They already work with an empty string. | Remove User parameters and use Runtime/Agent/Session storage authority. | remove |
| `ModelFileService.create*` used for input promotion and `read_image` | Wake-up User or delayed human-sender membership | Accidental coupling | Creation is denied without User or after sender membership changes. | Provide Session/Run-authorized creation for accepted input and runtime-generated model files. | separate |
| `ModelFileService.download_for_agent` and `ModelFileMaterializer` | Wake-up User membership | Accidental coupling | Materializer clears the resolver and returns, so transcript FileParts are not supplied to the model. | Resolve by ModelFile Agent/Session ownership plus the current valid Run. | separate |
| `read_image` | Wake-up User | Accidental coupling | The runtime file can be read, but ModelFile creation fails. | Use current Run/Session ownership to create the ModelFile. | separate |
| `ExchangeFileService.create_artifact` and `present_file` | Wake-up User membership and non-null `created_by_user_id` | Accidental coupling plus creator schema constraint | Tool returns access denied; generated attachment is not created. | Create Session-owned Exchange output with system/Session creator provenance; keep human uploader provenance only for uploads. | separate |
| `ExchangeFile.created_by_user_id` non-null FK | Human uploader or borrowed execution User | Provenance / accidental ownership | Userless output cannot be represented. | Model creator provenance without requiring every ExchangeFile to have a User. | separate |
| `import_file` Exchange resolver | Wake-up User membership only; current resolver does not require current Session/root | Accidental coupling | Team Session cannot import when User is absent. | Resolve by current Agent/root-Session retention ownership and active Run authority. | separate |
| `ArtifactService.create` and MCP artifact sink | Wake-up User membership | Accidental coupling | Artifact creation is denied; MCP sink is disabled when User is absent. | Create Artifact from validated Session/Run/tool-call lineage. | separate |
| `ArtifactService.resolve` used by `import_file` | Wake-up User membership | Accidental coupling | Internal Artifact cannot be imported without User. | Resolve internal Artifact by current Session/Run ownership; keep any future public read boundary separate. | separate |
| Provider/client generated image materialization | Wake-up User is mandatory; Workspace membership is rechecked | Accidental coupling | A valid provider response raises `ModelCallError`, which can fail/retry the run and lose otherwise valid output admission. | Validate Session, Agent, Workspace, Run, and retention-root lineage; store output without a User owner. | separate |
| Public Exchange file download/delete | Current authenticated viewer | Result-read authorization | Public access is denied. | Keep viewer authorization separate from internal creation/materialization/import. | retain |

### Recovery, continuation, External Channel, and subagents

| Area and symbols | Authoritative User source | Classification | Behavior without User | Replacement or boundary | Disposition |
|---|---|---|---|---|---|
| External Channel event and access-release wake-ups | No Azents User | Message admission and workload validity | Core execution starts, but User-coupled files, artifacts, and personalization differ or fail. | Provider principal belongs only to the admitted message. Verified event, connection, grant, binding, invocation batch, and Session association validate the work independently. | retain Userless behavior |
| Stuck-session recovery `_build_resume_message` | No User | Durable recovery | Recovery already wakes with `user_id=None`; User-coupled facilities are unavailable. | Continue from active Session and recoverable Run snapshots without inventing an initiating User or sender. | retain Userless behavior |
| Idle continuation | Reuses the prior `SessionWakeUp`, so execution data depends on the last producer | Accidental coupling | Toolkit reconstruction can differ after handover or External Channel execution. | Create a new pure signal and resolve all Session, Workspace, prompt, interface, and Toolkit context from durable state. | remove borrowed payload |
| Subagent spawn/message/follow-up `actor_user_id=self.user_id` | Parent wake-up User | Accidental sender coupling | Agent-authored mailbox messages misleadingly inherit a human User or become null by wake-up path. | For an actual agent-authored mailbox message, record the sending Agent as message sender metadata. Parent Run and SessionAgent lineage remain workload validation, not sender User identity. | remove |
| Subagent wake-up and interrupt signal User | Parent wake-up User | Accidental coupling | Child Toolkit/file behavior changes by parent invocation source; signal User is not consumed. | Child work is authorized by root tree, parent Run, target SessionAgent, and durable mailbox/Run state. | remove |
| Subagent tree/target validation in `AgentMailboxService` and subagent tool | SessionAgent root/parent/target lineage | Execution authority | Invalid tree or inactive target fails closed. | Retain as the internal authority and strengthen canonical Session identity loading. | retain |

## Current Security and Correctness Gaps

1. **TurnAction admission bypass**: the composer TurnAction branch does not call the existing REST
   Session access validator, and its service method does not check Workspace membership.
2. **Durable sender loss**: `actor_user_id` is deleted with the InputBuffer, non-human sources lack a
   shared sender representation, and the durable user-message event contains no sender metadata.
3. **Wake-up payload drift**: one Team Session behaves differently depending on identity, prompt, and
   interface data supplied by the latest REST, recovery, External Channel, handover, or subagent
   wake-up.
4. **Canonical identity gap**: the Worker claims the Session but does not consistently derive and
   validate Agent/Workspace identity from that Session before using wake-up envelope fields.
5. **Accepted attachment reauthorization**: promotion reuses the human sender as an execution-time
   viewer and can fail after the input was already accepted and its files claimed.
6. **File and Artifact execution failure**: ModelFile materialization, `read_image`, `present_file`,
   `import_file`, Artifact creation/import, and MCP artifact capture depend on a User who is not part of
   Team Session execution authority.
7. **Provider output loss/failure**: generated image output requires a User and converts absent User
   context into a model-call failure.
8. **Agent-authored sender corruption**: subagent mailbox messages can be labeled with the human who
   woke the parent even though another agent sent the message.
9. **Toolkit lifecycle instability**: Workspace-owned Toolkit instances are keyed by the wake-up User,
   while current runtime credentials are not per-user.
10. **Residual MCP Session classification**: MCP maps `ResolveContext.user_id` presence to
    `SessionType.USER` or `SYSTEM` even though its OAuth and static credentials are Toolkit-level.

## Requirements Implications

The Requirements snapshot should:

- retain public requester and viewer authorization, including a uniform pre-side-effect admission
  rule;
- require durable per-message sender metadata rather than an Actor abstraction or Session- or
  Run-wide User;
- keep requester authorization, message sender metadata, and a future User Session's associated User
  as independent relations that are never inferred from one another;
- require a pure wake-up signal with only minimum Session routing identity and move every prompt,
  interface, identity, and execution input into durable admitted work;
- state that accepted input resources are consumed under Session workload authority without
  reauthorizing the original sender;
- require canonical Session-derived Agent/Workspace identity for internal execution;
- distinguish Team-scoped capabilities from User-specific capabilities;
- require Userless file, Artifact, ModelFile, provider-output, recovery, continuation, External
  Channel, and subagent behavior;
- keep User Memory and future User-brought Tools unavailable in Team Sessions;
- prohibit compatibility restoration of removed MCP per-user OAuth and GitHub per-user PAT paths; and
- move audit-completeness mechanics out of product Requirements and into design verification.

## Scope Exclusions

- User Session storage, routing, visibility, and UX are future work.
- Toolkit management authorization remains a public management concern and is not removed.
- Historical per-user MCP OAuth and GitHub PAT designs are not current runtime behavior. Executed
  migrations and immutable historical documents remain as history; they are not compatibility
  requirements. Current MCP OAuth and GitHub Toolkit credentials are Toolkit-level.
- User-brought Tool persistence, connection UX, authorization, and runtime projection belong to
  future User Session work.
- Non-Agent `RDBSession` and unrelated account/authentication tables are outside the actual
  AgentSession execution path.
