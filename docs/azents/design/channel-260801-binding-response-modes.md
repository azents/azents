---
title: "External Channel Binding Response Modes Design"
created: 2026-08-01
updated: 2026-08-01
implemented: 2026-08-01
tags: [architecture, external-channel, agent, session, backend, frontend]
document_role: primary
document_type: design
snapshot_id: channel-260801
---

# channel-260801/DESIGN: External Channel Binding Response Modes

- Snapshot: `channel-260801`
- Document reference: `channel-260801/DESIGN`
- Mode: Collaborative

## Inputs

- Requirements:
  [channel-260801/REQ](../requirements/channel-260801-binding-response-modes.md)
- Architecture decisions:
  [channel-260801/ADR](../adr/channel-260801-binding-response-modes.md)
- Preserved synchronous ingestion decisions:
  [channel-260729/ADR](../adr/channel-260729-responsive-context-preserving-conversations.md)

## Summary

Add one required response-mode enum to the Agent and one required concrete mode to each
External Channel binding. Both default and migrate to `all_messages`, preserving the
current behavior where an eligible ordinary message in an already bound conversation
continues the same Session without another mention.

Agent administrators manage the Agent default from the existing External Channels page
under Agent Settings. They manage a connected binding's concrete mode from Session
Channels. Binding creation copies the Agent default in both normal synchronous
ingestion and administrator Allow flows. Later Agent-default changes never rewrite
existing bindings.

Provider adapters remain unchanged in authority: they authenticate callbacks and
classify provider-native explicit invocation. Shared synchronous ingestion resolves the
resource and connected binding, then combines that explicit-invocation signal with the
binding mode. `all_messages` retains ordinary bound continuation. `mention_only`
ignores an ordinary non-invocation without canonical mailbox input, Session wake, or
conversation-position advancement, allowing the ignored provider message to remain in
the bounded history read by a later eligible mention.

## Current Behavior and Gaps

Slack already subscribes to `app_mention`, `message.channels`, and `message.groups`.
Discord Gateway already enables Guild messages and message content. Both providers
normalize every supported original message into an
`ExternalChannelTriggerLocator.invocation` signal and call the same synchronous
ingestion service.

The current ingestion store uses `invocation=False` only to prevent creation of a new
resource. If the provider resource already exists, ingestion resolves any connected
binding and admits an eligible ordinary human message as a continuation. This is the
implemented `channel-260729/REQ-2` behavior and is equivalent to `all_messages`.

The current system has these gaps relative to `channel-260801/REQ`:

- no Agent-owned default response mode;
- no concrete binding response mode;
- no management projection or mutation for either setting;
- no `mention_only` gate in shared ingestion; and
- an existing resource with no connected binding can pass beyond resource resolution
  on a non-invocation, even though an unbound or disconnected conversation must require
  an explicit invocation before a new binding is created.

The last item is implementation drift from the existing explicit unbound-conversation
invocation rule. The mode-aware shared gate corrects it without introducing a separate
compatibility path.

## Traceability

| Requirement | ADR decisions | Design mechanism |
| --- | --- | --- |
| `channel-260801/REQ-1` | `ADR-D3` | Required Agent enum, Agent-scoped External Channel read/update API, Agent Settings editor |
| `channel-260801/REQ-2` | `ADR-D2`, `ADR-D3` | Both binding-creation paths copy the transaction-visible Agent default into a required binding column |
| `channel-260801/REQ-3` | `ADR-D3` | `ManagedBinding.response_mode`, connected-only update API, Session Channels editor |
| `channel-260801/REQ-4` | `ADR-D1`, `ADR-D2` | Shared pre-history gate plus final admission recheck; ignored non-mentions do not advance position |
| `channel-260801/REQ-5` | `ADR-D1` | `all_messages` retains the existing bound-continuation path |
| `channel-260801/REQ-6` | `ADR-D3` | Non-null `all_messages` server defaults and migration for Agent and binding rows |
| `channel-260801/REQ-7` | `ADR-D2` | Current committed mode is read in existing transactions; no retroactive scan or running-work mutation |
| `channel-260801/REQ-8` | `ADR-D1`, `ADR-D2` | Existing access, author, lifecycle, mailbox, wake, and delivery checks remain downstream authorities |

## Domain and Persistence Model

### Response-mode enum

Add `ExternalChannelResponseMode` to the core External Channel enums:

- `MENTION_ONLY = "mention_only"`
- `ALL_MESSAGES = "all_messages"`

Persist it through one PostgreSQL enum type named
`external_channel_response_mode`.

### Agent default

Add a required `external_channel_default_response_mode` column to `agents`.

- type: `external_channel_response_mode`;
- nullable: false;
- Python default: `ExternalChannelResponseMode.ALL_MESSAGES`;
- server default: `all_messages`; and
- migration value for every existing Agent: `all_messages`.

The internal Agent repository model includes the required field so binding creation can
copy it. Internal Agent creation passes the product default explicitly. The public
generic Agent response, create request, and patch request remain unchanged.

The Agent repository adds focused read/update support for the scalar. External Channel
management uses that support after its existing Agent ownership and AgentAdmin checks.

### Binding concrete mode

Add a required `response_mode` column to `external_channel_bindings`.

- type: `external_channel_response_mode`;
- nullable: false;
- server default: `all_messages`; and
- migration value for every connected or disconnected historical binding:
  `all_messages`.

`ExternalChannelBinding`, `ExternalChannelBindingCreate`, and `ManagedBinding` expose
the required enum. There is no nullable state, inheritance marker, route fallback, or
`use_agent_default` value.

### Migration

Generate one new Alembic revision from the current head. The revision:

1. creates `external_channel_response_mode`;
2. adds the required Agent default column with `all_messages`;
3. adds the required binding concrete-mode column with `all_messages`; and
4. preserves the server defaults for future rows.

The downgrade drops the two columns before dropping the enum. The implementation
updates `python/apps/azents/db-schemas/rdb/revision`. No executed migration is edited.

Because both columns are added with the current behavior as their required default,
there is no dual-read phase, nullable backfill window, or application fallback.

## Management API and Authorization

### Agent default projection

Extend the Agent-scoped `ManagedConnectionListResponse` with:

```text
default_response_mode: ExternalChannelResponseMode
```

The response already backs the External Channels Agent Settings page and is available
when no dedicated connection exists. Connection and Multi App rows remain unchanged;
the default belongs to the Agent, not to any connection or route.

Add a full-value mutation under the same Agent-scoped External Channel management
resource:

```text
PUT /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/default-response-mode
```

Request and response contain the required `response_mode`. The service:

1. verifies Workspace and Agent ownership;
2. requires an explicit AgentAdmin relationship;
3. updates only the Agent scalar; and
4. returns the canonical saved value.

The mutation does not enumerate or modify existing bindings.

### Binding projection and mutation

Add `response_mode` to every `ManagedBinding`.

Add a full-value connected-binding mutation:

```text
PUT /external-channel/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/external-channels/{binding_id}/response-mode
```

The request contains the required `response_mode`. The service reuses the existing
binding management boundary:

1. verifies the Agent belongs to the Workspace;
2. requires AgentAdmin;
3. verifies the binding belongs to the requested AgentSession and Agent;
4. requires `disconnected_at IS NULL`;
5. updates only the binding scalar; and
6. returns the canonical updated binding projection.

Unauthorized, foreign, missing, and disconnected bindings use the existing
not-found-shaped management behavior. Unsupported enum values fail request validation.
Unexpected database failures propagate through normal API error handling.

Both mutations use ordinary full-value, last-write-wins scalar updates. They add no
policy revision, expected timestamp, generation fence, or retry protocol.

### Generated clients and tRPC

Regenerate the public OpenAPI specification and both generated public clients.

The azents-web tRPC router adds:

- `updateDefaultResponseMode`; and
- `updateBindingResponseMode`.

Successful mutations invalidate the Agent External Channels query or the Session
Channels query respectively. Binding-mode mutation does not invalidate connection
catalog state, and Agent-default mutation does not invalidate existing Session
bindings.

## Binding Creation

Both binding-creation paths pass an explicit concrete mode to
`ExternalChannelBindingCreate`.

### Normal synchronous ingestion

`ExternalChannelMailboxIngestionStore._create_binding()` already loads the routed
Agent in the transaction that creates the root Session and binding. It copies
`agent.external_channel_default_response_mode` into
`ExternalChannelBindingCreate.response_mode`.

### Administrator Allow

`ExternalChannelAccessService` already loads and validates the active routed Agent in
the decision transaction. When Allow creates a new binding, it copies the same Agent
field into `ExternalChannelBindingCreate.response_mode`.

If either path reuses an existing connected binding, repository idempotency returns its
existing concrete mode. The current Agent default is not reread to overwrite that mode.

## Mode-Aware Synchronous Ingestion

### Single policy predicate

Shared ingestion owns one provider-neutral predicate:

```text
explicit invocation
OR
(connected binding exists AND binding.response_mode == all_messages)
```

The predicate produces these results:

| Binding state | Explicit invocation | Binding mode | Result |
| --- | --- | --- | --- |
| none | false | n/a | ignore; an unbound or disconnected conversation cannot start |
| none | true | n/a | continue route, access, Session, and binding resolution |
| connected | false | `mention_only` | ignore without position advancement |
| connected | false | `all_messages` | continue the existing bound-continuation flow |
| connected | true | either | continue the existing explicit-invocation flow |

Approval replay and explicit interaction continuations retain their existing
invocation authority and are not blocked by `mention_only`.

### Preparation transaction

Refactor conversation preparation so connected-binding resolution is available before
principal creation, route selection, access state, selector state, and provider-history
I/O.

After resource and connected-binding resolution:

- no binding plus a non-invocation returns `ignored`;
- `mention_only` plus a non-invocation returns `ignored`; and
- all other cases continue.

Use a new categorical ingestion reason such as
`response_mode_not_triggered` for the bound `mention_only` result. Unbound
non-invocation retains `not_an_invocation`.

The transaction may create or reuse the conversation-position row, but it does not
advance that position. It creates no mailbox item, Session wake, Channel Work,
progress/presence delivery, selector, access request, or new binding.

### Provider-history retrieval

Ignored preparation outcomes return before provider history is read. For an accepted
later mention, the unchanged exclusive start position causes the history adapter to
read through the mention and include the newest eligible visible messages, including
prior non-trigger messages, within the existing 20-message bound.

No pending-context table, alternate cursor, deferred event inbox, or message-body cache
is introduced.

### Final admission transaction

Final admission resolves the resource and connected binding again through the existing
locked path. It applies the same predicate before authorization side effects, mailbox
enqueue, position advancement, Session running transition, or provider-control intents.

This recheck uses the current committed binding value visible to the existing
transaction. It adds no new lock. If the mode changed while provider history was being
read and the current message is no longer a trigger, the fetched history is discarded,
the position remains unchanged, and the outcome is acknowledged as ignored.

If admission has already committed, a later mode mutation does not inspect, cancel, or
rewrite its mailbox item, pending wake, AgentRun, Channel Work, or delivery attempts.

### Author and access policy

The response-mode predicate does not replace author or access validation.

- Provider history must still identify the trigger as a human with a provider user ID.
- Active blocks still take precedence.
- Current grants and automatic human-access policy retain their behavior.
- Bot, app, and system callbacks cannot become invocations through `all_messages`.
- Connected Azents App/Bot output remains excluded from history and loop prevention.
- Disconnected bindings never invoke in either mode.

## Frontend Design

### Agent Settings: default mode

Add one compact settings region near the top of the existing External Channels page,
before connection-specific controls.

The region contains:

- heading: “Default response mode”;
- utility description explaining that the value is copied only to newly connected
  conversations;
- two radio choices with short descriptions:
  - “All eligible messages” — continue the current automatic participation behavior;
  - “Mentions only” — ordinary messages remain context until an explicit mention;
- an explicit Save action next to the affected setting; and
- inline saving, saved, and error feedback.

The editor keeps a saved value and local draft. Save is disabled when unchanged,
invalid, or already saving. A successful save refreshes the canonical default. It does
not imply that existing bindings changed.

The section remains visible when there are no Slack or Discord connections so the
administrator can configure the default before connecting an App.

### Session Channels: binding mode

Each binding panel displays a compact “Response mode” row near the binding identity and
connectedness badge. For a connected binding, the row contains a two-option Select and
an adjacent Save action. Keeping the control inside the binding panel makes its scope
unambiguous when one Session has several bindings.

For a disconnected or archived binding:

- the historical saved mode remains visible;
- the control is disabled/read-only; and
- the existing disconnect/archived explanation remains the lifecycle authority.

Saving one binding disables only that binding's mode control and conflicting
disconnect action. Other binding panels remain usable. A failed save retains the local
draft and shows a bounded actionable error near the affected panel.

On narrow screens, the label, Select, and Save action wrap into one vertical flow
without hiding the current mode or connectedness state.

### Localization and stories

Add natural localized labels and utility descriptions to `en-US`, `ko-KR`, `ja-JP`,
and `fr-FR`.

Update colocated Storybook fixtures and add meaningful states:

- Agent default `all_messages`;
- Agent default `mention_only`;
- changed draft and saving state;
- binding `all_messages`;
- binding `mention_only`;
- disconnected read-only binding; and
- inline mutation failure.

## Failure Handling and Observability

- A mode-based ignored callback is a normal acknowledged outcome, not an error.
- The new ingestion reason is categorical and content-free.
- Mode evaluation emits no message body, provider identity, participant identity,
  tenant, channel, Session, or binding identifier in logs.
- No new routine log line is required for successful management changes.
- Existing retryable classification remains limited to authority, provider-history,
  coordination, database, position, and wake failures.
- A setting change never depends on provider availability because it mutates only
  Azents-owned state.
- Provider-control delivery remains independent from accepted mailbox execution.

## Migration, Rollout, and Rollback

One additive migration and one application rollout are sufficient.

1. Apply the additive enum and required columns with `all_messages` defaults.
2. Deploy backend code that reads and writes both required fields.
3. Deploy regenerated clients and azents-web controls.

The schema addition is backward-compatible with the prior application because old code
ignores the new columns and database defaults populate binding rows it creates during a
mixed-version window. New code never encounters null.

No feature flag or data backfill job is required. Deployment alone preserves current
behavior. A code rollback may leave the additive columns in place safely. A database
downgrade is permitted only after all code that reads the columns has been rolled back.

## Test Strategy

### E2E primary verification matrix

| Scenario | Surface | Evidence |
| --- | --- | --- |
| Read and save Agent default | Public API and Web Surface Agent Settings | Canonical value changes and survives reload |
| New Slack binding copies default | Public API plus deterministic Slack fake | Binding projection reports the saved default |
| New Discord binding copies default | Public API plus deterministic Discord fake | Binding projection reports the saved default |
| Existing/default `all_messages` continuation | Provider callback and Session history | Ordinary eligible message creates one canonical input and normal response flow |
| `mention_only` ignores ordinary message | Provider callback, Session state, provider evidence | No new canonical input, wake, progress, or response |
| Later mention includes ignored context | Provider fake history and Session projection | Later input contains ordered bounded context through the mention |
| Binding mode edit | Session Channels Web Surface and public API | Saved mode survives reload and affects later callbacks |
| Disconnected binding is read-only | Public API and Web Surface | Mutation is unavailable/not found while historical mode remains visible |
| Existing access and author rules | Slack and Discord provider fakes | Blocked and nonhuman authors remain non-invoking |

### Backend tests

- RDB enum defaults and migration shape;
- Agent repository default read/update;
- binding create, idempotent reuse, projection, and connected-only update;
- both production binding-creation paths copy the Agent default;
- AgentAdmin authorization and cross-Workspace/Agent/Session not-found behavior;
- shared ingestion predicate for every table row in the mode matrix;
- early ignored outcome performs no provider-history read;
- final admission recheck discards stale fetched history without advancing position;
- later mention reads context from the unchanged position;
- duplicate delivery, position mismatch, approval replay, and wake recovery remain
  unchanged; and
- bot/app/system and connected-bot exclusion remain unchanged.

### Frontend tests

- container ADTs for loading, error, loaded, saving, and mutation failure;
- dirty-state and save-enabled calculations;
- tRPC input mapping and relevant query invalidation;
- pure component stories for the states listed above; and
- Web Surface journey for the primary Agent Settings and Session Channels scenario.

### Fixtures and CI

Existing Slack and Discord fakes already support ordinary message callbacks, provider
history, synchronous acknowledgement, and bound continuation. Extend them only where a
public management call or evidence assertion is missing; do not add direct product-row
mutation.

Required deterministic CI runs backend quality/tests, TypeScript format/lint/typecheck/
build, generated-client drift checks, deterministic E2E, and Web Surface E2E according
to path filtering. No live-provider credential is required, and no required scenario
may skip because a local provider fake prerequisite is missing.

## Removal and Replacement

| Existing unit or behavior | Why it becomes obsolete | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Unconditional ordinary continuation for every existing resource/binding | Connected bindings can now require mentions | One shared mode-aware predicate using the concrete connected binding | Preparation and final admission paths | Search and tests prove no continuation path bypasses the predicate |
| Existing-resource non-invocation proceeding when no connected binding exists | It can recreate a binding after disconnect without an explicit invocation | No-binding plus non-invocation returns the existing ignored outcome | Resource/conversation resolution | Disconnected-resource E2E proves an ordinary message cannot create a new binding |
| Conversation resolution that creates principal/selector/access state before response-mode gating | Ignored `mention_only` messages should stop before unrelated durable side effects and provider I/O | Resolve connected binding first, then continue full conversation resolution only for a trigger | Shared ingestion preparation and acceptance helpers | Unit tests assert no selector, access request, mailbox, wake, or provider-history read |
| Binding constructors without a concrete mode | A binding may not inherit or fall back dynamically | Required `ExternalChannelBindingCreate.response_mode` in all production/test callers | Domain model and repository constructor call sites | Repository-wide search finds no constructor without the required field |
| Management projections without Agent/binding mode | Settings cannot be observed or edited | Agent-scoped default projection and `ManagedBinding.response_mode` | Public API, generated clients, tRPC, UI fixtures | OpenAPI/client drift checks and Storybook type checking |
| Tests that assume implicit bound continuation | The assumption must be explicit after configurable modes exist | Default `all_messages` fixtures plus dedicated `mention_only` scenarios | Backend, E2E, and Storybook fixtures | Search and review show every mode-sensitive fixture states or inherits the documented default |

No provider transport, callback subscription, route access policy, conversation-position
model, mailbox/wake contract, provider-control delivery path, or compatibility fallback
is removed.

## Feasibility Validation

| Requirement or decision | Result | Repository evidence and implementation path |
| --- | --- | --- |
| `channel-260801/REQ-1` Agent default management | feasible | `RDBAgent` already owns required scalar settings; Agent-scoped External Channel list and AgentAdmin mutation boundaries already back the target Settings page |
| `channel-260801/REQ-2` creation-time copy | feasible | Production has exactly two `ExternalChannelBindingCreate` call sites: normal synchronous ingestion and administrator Allow; both already load the routed Agent in the binding transaction |
| `channel-260801/REQ-3` connected binding management | feasible | `ManagedBinding`, Session Channels list, AgentAdmin-gated disconnect service, binding ownership query, and `lock_binding()` provide the projection and connected-only mutation pattern |
| `channel-260801/REQ-4` mention-only behavior and later context | feasible | Shared preparation can stop before history; PostgreSQL position remains unchanged; the existing exclusive-start/inclusive-trigger history collector then includes prior visible messages on a later mention |
| `channel-260801/REQ-5` all-messages behavior | feasible | Existing connected-resource/binding ingestion already admits ordinary eligible human continuations and is validated by `channel-260729` evidence |
| `channel-260801/REQ-6` compatibility migration | feasible | The migration head is linear and an additive PostgreSQL enum plus non-null `all_messages` defaults can represent every existing Agent and binding without fallback |
| `channel-260801/REQ-7` non-retroactive mode changes | feasible | Preparation and final admission are separate short transactions; final admission already re-resolves the locked binding, while accepted mailbox and AgentRun state have no reverse mutation dependency |
| `channel-260801/REQ-8` policy and lifecycle preservation | feasible | Author, block, grant, connection, Agent lifecycle, mailbox, wake, Channel Work, and delivery checks remain downstream in the existing shared acceptance path |
| `channel-260801/ADR-D1` shared policy authority | feasible | Slack HTTP, Slack Socket, and Discord Gateway already enter one `ExternalChannelConversationIngestionService`; adapters need no policy lookup |
| `channel-260801/ADR-D2` existing transaction semantics | feasible | `lock_connected_binding_by_resource()` and `lock_binding()` already use short `FOR UPDATE` reads; ordinary updates receive PostgreSQL row locking without a new synchronization primitive |
| `channel-260801/ADR-D3` Agent scalar plus External Channel API | feasible | The Agent repository can carry the internal field without adding it to `AgentOutput` or `AgentResponse`; `ManagedConnectionListResponse` and External Channel tRPC/UI already form a separate public management contract |
| Deterministic verification | feasible | Slack and Discord fakes already support ordinary callbacks and bounded history pages; public API E2E, Web Surface E2E, Storybook, and generated-client checks are established |
| Documentation lifecycle | feasible | The same-basename Requirements, ADR, and Design pass snapshot validation; all affected Living Specs exist |

### Non-blocking risks

- Conversation resolution currently combines binding, principal, route, and selector
  work. The implementation should replace that narrow unit with an explicit
  binding-first flow rather than layering a late conditional around side effects.
- A mode change during provider-history I/O can discard one bounded read. This is
  acceptable and retry-free because the callback is acknowledged as ignored and the
  durable position remains unchanged.
- Existing tests and static fixtures construct Agent and binding records extensively.
  Required enum fields will cause broad compile/test edits, but every constructor is
  searchable and no runtime compatibility fallback is needed.
- The Web Surface currently models disconnect as the only binding mutation. Its action
  state should be generalized carefully so one binding save does not disable unrelated
  panels.

No requirement or accepted ADR decision is blocked or conditional.

## Implementation Scope

The feature is suitable for one focused PR. It spans schema, backend domain and
management, OpenAPI-generated clients, azents-web controls, deterministic E2E, and
Living Spec updates, but it has one additive migration and no independently deployable
phase or external-provider rollout dependency.

Implementation must update the relevant Living Specs after behavior and tests are
complete. The Requirements, ADR, and this Design remain development snapshot records;
current implemented behavior belongs in the Specs.
