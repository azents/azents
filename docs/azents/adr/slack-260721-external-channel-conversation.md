---
title: "External Channel Agent Conversation"
created: 2026-07-21
tags: [slack, integration, agent, security, architecture]
document_role: primary
document_type: adr
snapshot_id: slack-260721
---

# External Channel Agent Conversation

- Snapshot: `slack-260721`
- Document reference: `slack-260721/ADR`
- Requirements: [External Channel Agent Conversation Requirements](../requirements/slack-260721-external-channel-conversation.md) (`slack-260721/REQ`)

## Status

Accepted.

## Context

`slack-260721/REQ` requires Azents to support explicit, secure Agent conversation through external collaboration channels. The first usable provider is a manually created per-Agent dedicated Slack App, but the product boundary must allow one Agent to hold multiple Slack connections and future Discord, GitHub comment, Jira, and other provider connections.

An external Slack thread may start or join an Agent session. The complete attributed thread remains visible as context, while only approved human participants may invoke the Agent. Ordinary model output and Web conversation are never relayed automatically. The Agent communicates externally only through explicit channel actions, and each linked external conversation may own independent follow-up work, continuation, and a temporary progress projection.

The Requirements also define terminal thread and connection disconnect behavior, durable access decisions, no implicit Slack-to-Azents identity linking, and preservation of Agent history after external communication stops.

## System-Grounded Framing

### Current Azents boundaries

- The current repository contains no active Slack adapter, API, model, or Web surface. This snapshot introduces a new product surface rather than extending a current Slack implementation.
- `AgentSession` is the conversation and serialized execution boundary. It owns canonical events, input buffers, runs, Goal, Todo, Toolkit State, Web history/live projection, and idle continuation.
- Accepted model-facing input is persisted through session input buffers. The producing domain owns acceptance idempotency and whether an input wakes the session or remains queue-only.
- Canonical events provide append-only transcript and history identity, including a session-scoped unique `external_id` that can support deterministic external-event admission.
- The idle continuation lifecycle can persist continuation input and wake a successfully completed session, but the current Goal provider represents only one session-scoped Goal.
- The current Todo is one session-scoped Toolkit State list and cannot represent multiple linked external conversations independently.
- Toolkit configurations provide encrypted credential storage, Agent attachment, model-visible tools, and source snapshots. They currently represent executable capabilities rather than inbound communication, external participant authorization, or linked-conversation lifecycle.
- Web history and live state are internal projections. They are not a durable outbound-delivery record for an external provider.

### Slack platform constraints

- A dedicated Slack App can route events by app and workspace identity and can use installation-specific bot credentials and signing secrets.
- Initial direct mentions and subsequent thread messages require different Slack event subscriptions and internal invocation filtering.
- Thread history is available only within the installed App's channel membership and granted history scopes. Slack does not guarantee ordered delivery across distinct events.
- Slack event acknowledgement must be decoupled from Agent execution, and provider event identity must be durably deduplicated.
- Ephemeral messages are insufficient as the durable approval entry point.
- Long-lived progress is best represented as Azents-owned durable work projected into one ordinary App-authored Slack message. Slack streaming and native task presentation may be optional rendering optimizations, not canonical state.
- Progress updates and deletion are external side effects that require durable target identity, retry, reconciliation, and best-effort cleanup after credential revocation.

### Historical implementation evidence

The prior Slack and Discord implementation was removed from `menufans/menufans` by commit `802af09a19c858a4ff0d5f08505ce8f156026612` on 2026-06-15.

Useful historical patterns include:

- dedicated App credentials and signing-secret verification selected by `api_app_id`;
- multiple Slack installations in one workspace;
- normalized Slack team, channel, thread, message, event, and actor identity;
- linked external watch identity and explicit Slack read/write tools; and
- shared AgentSession use for Web and Slack-originated work;
- a historical per-watch delivery table with `(watch_id, source_event_id)` uniqueness and conflict-safe first-delivery admission in commit `34e9d5f5f27c`;
- mention-start and existing-bot-thread filtering in commit `135228e8e`;
- best-effort deletion of orphaned Slack control messages in commit `390078e2e`; and
- operational fixes for Slack client lifecycle, stream flush ordering, and status-update failure handling.

Commit `761d1c075799` deliberately removed the worker Slack and Discord conversation adapters and stopped automatic broker dispatch and platform reply. This is evidence that inbound external events and ordinary Agent output should not be re-coupled through a transparent response adapter.

Historical assumptions that do not satisfy the confirmed Requirements include:

- generic channel-message watching instead of mention-started linking;
- Platform App Agent selection and Slack-to-Azents account linking;
- no participant Allow, Deny, Block, or separate invocation authority;
- no durable provider-event inbox or acceptance deduplication;
- no channel-specific work, progress, or continuation state;
- broad provider-coupled Slack tools without the confirmed explicit-publication contract; and
- no terminal disconnect and cleanup lifecycle that preserves historical session state.

## Feasibility Summary

No requirement-level blocker was found in the current repository or official Slack platform capabilities.

The highest-risk design area is `slack-260721/REQ-8` and `slack-260721/REQ-10`: one Agent session may contain multiple linked external conversations with independent unfinished work, while AgentSession execution remains one serialized FIFO stream. The design must aggregate continuation without losing per-channel identity, clearing unrelated work, or producing duplicate wake-ups.

Other unresolved points are architecture choices rather than Requirement changes.

## Decision Backlog

The following design points are resolved by the accepted decisions below.

1. **External-channel domain boundary** — whether connection, linked conversation, participant access, and channel work are first-class external-channel concepts or extensions of Toolkit configuration.
2. **Provider connection ownership** — Agent/workspace ownership, dedicated-App identity, many same-provider installations, credential lifecycle, and relationship to model-visible tools.
3. **Canonical external event and message identity** — provider event deduplication, message lifecycle identity, attributed transcript form, edits/deletes, and deterministic late-event reconciliation.
4. **Linked-conversation lifecycle** — external resource key, one-session-to-many-resource relationship, mention-start binding, rebinding, and terminal disconnect.
5. **External participant authorization** — pending approval, Session and Agent grants, Deny, Block, revocation, approver policy, and separation from Azents identity.
6. **Explicit channel action contract** — reply, no-reply completion, task/progress update, target selection, tool exposure, and fail-closed publication.
7. **Channel-work and continuation ownership** — per-linked-conversation work state, task lifecycle, multi-channel aggregation, idle continuation, compaction, recovery, and new inbound input.
8. **Outbound delivery and progress reconciliation** — durable send/update/delete intent, provider target identity, retry, rate-limit coalescing, partial failure, and operator visibility.
9. **Slack ingress and installation security** — HTTP Events API or Socket Mode, endpoint sharing across dedicated Apps, signature validation, scopes, channel membership, Slack Connect, and external revocation detection.
10. **Web and management projection** — external-origin rendering, access controls, approval management, connection/subscription management, cleanup visibility, and no-relay guarantees.
11. **Migration and verification strategy** — new persistence, event taxonomy, OpenAPI/client changes, deterministic fixtures, live Slack evidence, and recovery E2E coverage.

## Decisions

### `slack-260721/ADR-D1` — Model external channels as a first-class domain

External channel connections, linked external conversations, external participant access, channel work, inbound event admission, and outbound delivery are owned by a dedicated External Channel domain.

Slack is the first provider adapter for this domain. Future Discord, GitHub comment, Jira, and other adapters must integrate through the same domain boundary rather than defining their own Agent conversation lifecycle.

Existing Azents primitives remain reusable infrastructure:

- encrypted credential storage patterns;
- AgentSession execution and canonical transcript;
- durable input buffers and producer-owned wake behavior;
- idle continuation lifecycle;
- model-visible Tool Catalog and tool execution; and
- Web history and live projection protocols.

Toolkit configuration is not the source of truth for external connections, participants, linked conversations, channel work, or delivery lifecycle. External channel actions may still be exposed through the existing Tool Catalog.

This decision satisfies `slack-260721/REQ-1`, `slack-260721/REQ-4`, `slack-260721/REQ-6`, `slack-260721/REQ-8`, `slack-260721/REQ-10`, `slack-260721/REQ-12`, and `slack-260721/REQ-13`.

Rejected alternatives:

- Making ToolkitConfig the external-channel source of truth was rejected because executable capability attachment has a different lifecycle from inbound event admission, external participant authorization, linked conversations, channel work, and disconnect handling.
- Building a Slack-specific persistence domain first was rejected because it would defer the central multi-provider product requirement and likely require a later data and lifecycle migration.

### `slack-260721/ADR-D2` — Separate workspace-owned connections from Agent routing

An external connection is owned by the Workspace and represents one provider installation or credential boundary. It owns provider identity, encrypted credentials, connection status, and provider-level configuration independently from any Agent.

A separate Agent route links a connection to an Agent and defines whether that Agent is available through the connection.

The first per-Agent dedicated Slack connection must have exactly one active Agent route. Inbound Slack conversation does not perform Agent selection and routes directly through that active route.

The domain must permit a later platform connection to expose multiple Agent routes and perform user-visible Agent selection without migrating dedicated connection credentials or linked-conversation history. Platform routing behavior is not implemented in this snapshot.

Agent deletion, route removal or reassignment, connection disconnection, and external credential revocation are separate lifecycle operations. Removing an Agent route does not redefine provider installation identity, and disconnecting a connection terminates every route and linked conversation that depends on it.

This decision satisfies `slack-260721/REQ-1`, `slack-260721/REQ-2`, `slack-260721/REQ-3`, `slack-260721/REQ-12`, and `slack-260721/REQ-13`.

Rejected alternatives:

- Direct Agent ownership of connections was rejected because it permanently encodes the dedicated-App cardinality and couples provider credential lifecycle to Agent deletion.
- Storing one mutable `agent_id` directly on a workspace-owned connection was rejected because it would still require a relationship migration for the later platform App and would mix provider installation state with Agent routing state.

### `slack-260721/ADR-D3` — Separate provider events, external messages, resources, and session bindings

The External Channel domain maintains four distinct logical identities:

1. A provider event identifies one provider delivery and owns acceptance, retry, and deduplication lifecycle.
2. An external message identifies content that exists in the provider and owns create, edit, and delete lifecycle independently from individual event deliveries.
3. An external resource identifies the provider conversation object, such as a Slack thread, GitHub pull request, Jira issue, or Discord thread.
4. A session binding records the active or historical relationship between an external resource, Agent route, and AgentSession.

The physical persistence design may combine or split these concepts, but it must preserve their independent uniqueness and lifecycle semantics.

Within one Agent route, an external resource may have at most one active session binding. Disconnect terminates that binding without deleting the resource or historical Agent transcript. A later eligible reconnection creates a new binding instead of reactivating or rewriting the terminated binding.

One AgentSession may have multiple active bindings to different external resources. External messages from an active binding are projected into the canonical Agent transcript with durable source attribution. Context visibility is independent from invocation authority: all eligible human and bot messages may be represented as context, while only an authorized invocation produces wake behavior.

Provider event deduplication does not replace external message identity. Multiple distinct events may describe one message's creation, edit, deletion, or other lifecycle changes, and late events must reconcile against the stable external message and resource identity.

This decision satisfies `slack-260721/REQ-3`, `slack-260721/REQ-4`, `slack-260721/REQ-5`, `slack-260721/REQ-11`, `slack-260721/REQ-12`, and `slack-260721/REQ-14`.

Rejected alternatives:

- Persisting provider events directly as transcript metadata without an external resource or binding lifecycle was rejected because approval, deduplication, edits, disconnect, and reconnection would become inseparable from AgentSession history.
- Combining provider resource identity and the current AgentSession link into one mutable ExternalConversation record was rejected because terminating and later recreating a link would rewrite or ambiguously reuse historical relationship state.

### `slack-260721/ADR-D4` — Separate external principals, access requests, grants, blocks, and approvers

The authorization model follows the already confirmed product contract in `slack-260721/REQ-5` and `slack-260721/REQ-6`; it is not a separate product choice.

An external principal represents provider identity independently from any connection or Azents User. Its logical identity is provider, provider tenant or workspace, and provider user identity. Display names and email addresses are mutable profile data rather than identity keys, and identities from different providers are never merged implicitly.

A pending access request records an external principal's explicit attempt to invoke an Agent through an Agent route, external resource, and source external message. Context-only participation does not create an approval request by itself.

A Session grant authorizes the external principal to invoke the Agent within one AgentSession. An Agent grant authorizes the same provider-tenant principal to start or continue conversations with that Agent through any eligible connection. Neither grant creates an Azents account, grants Web access, or inherits the approver's permissions.

An Agent block is an independent Agent-and-principal policy that takes precedence over grants while active and suppresses invocation and approval projection. Deny terminates only the addressed pending request and does not create a persistent principal policy.

Every access decision records the external subject, deciding Azents User, decision type and scope, decision time, and the authorization policy under which the decision was permitted. The Agent policy determines whether any Azents User who can converse with the Agent or only an Agent administrator may decide requests.

The durable access request and decision are the source of truth. Slack messages and links are projections into the provider. When an Allow decision requires a new AgentSession or session binding, session creation, binding activation, grant creation, and original-message admission must have one recoverable domain operation rather than relying on the Slack projection.

This decision satisfies `slack-260721/REQ-5`, `slack-260721/REQ-6`, and `slack-260721/REQ-14`.

Connection-scoped allow lists and implicit Slack-to-Azents account linking are incompatible with the confirmed Requirements and are not considered valid implementation alternatives.

### `slack-260721/ADR-D5` — Use one atomic provider-generic channel action contract

The Agent communicates with a linked external conversation through one provider-generic channel action contract targeted by an active session binding rather than provider-native channel identifiers.

The contract has two semantic modes:

- `finish` optionally includes a message. A missing message represents no reply; a present message represents an immediate or final reply. The channel work becomes terminal and no longer requests continuation.
- `continue` optionally includes a conversational message and may create or update the channel task list. The resulting channel work must contain at least one unfinished task and remains eligible for continuation.

A continuing action may update tasks without sending a conversational message, send an intermediate message while retaining existing tasks, or atomically perform both. A finishing action closes the work independently from ordinary model output.

Ordinary assistant output never mutates channel work and never publishes externally. Separate send, Todo, and finish calls are not required to establish one logical state transition.

The accepted channel action atomically records the resulting channel-work state and durable outbound delivery intent. Provider API execution, delivery acknowledgement, retry, and projection reconciliation are defined by a later delivery decision; acceptance of the domain action is not silently inferred from ordinary assistant output.

When a session has multiple bindings, the action explicitly identifies its target binding. Provider-native resource identifiers are resolved by the External Channel domain and are not authored directly by the model.

This decision satisfies `slack-260721/REQ-7`, `slack-260721/REQ-8`, `slack-260721/REQ-9`, and `slack-260721/REQ-10`.

Rejected alternatives:

- Independent send, Todo, finish, and no-reply tools were rejected because interruption or compaction between calls can leave outbound communication and channel-work state inconsistent.
- Separate send and channel-work tools were rejected because a send call cannot prove whether the Agent intended an immediate final response or an intermediate response that requires follow-up work.

### `slack-260721/ADR-D6` — Keep all unfinished channel work in model context and use one generic continuation

Every model-producing turn for an AgentSession with active channel work includes a current Channel Work Snapshot containing all active session bindings and their ordered unfinished task state. This dynamic snapshot is loaded from canonical External Channel state and is not inferred from previous assistant output.

The compaction enricher also appends a Channel Work Snapshot for all active bindings. The compacted snapshot preserves external work obligations across context replacement, while turn-time enrichment refreshes the current canonical state so a stale compaction summary does not control continuation or completion.

When the session becomes idle after a successful run and at least one channel work remains active, the External Channel continuation provider emits one generic continuation input. The input contains stable behavioral guidance and the list of bindings with unfinished work. It does not duplicate full Todo content because the current Channel Work Snapshot is already present in model context.

The continuation scheduler does not select one focused binding, create one continuation per work item, maintain a round-robin cursor, or pre-enqueue multiple work-specific continuation inputs. The Agent inspects the complete active-work context and chooses which binding or bindings to advance through the atomic channel action contract.

Accepted user or external invocation input retains the normal session FIFO and wake behavior. Idle continuation runs only after no existing follow-up input is eligible. Completing one channel work removes it from subsequent snapshots and binding lists without affecting other active work. When no active channel work remains, the provider emits no continuation.

The snapshot representation must remain compact while preserving every active binding identity, task ordering, and task status. It must not include credentials or unnecessary raw provider payloads.

This decision satisfies `slack-260721/REQ-8` and `slack-260721/REQ-10`.

Rejected alternatives:

- Selecting one channel work per idle boundary was rejected because the complete unfinished work set is already continuously model-visible and the Agent can choose its next action without scheduler-owned focus state.
- Enqueuing one continuation per active work was rejected because it duplicates state already present in context and can create stale FIFO continuation inputs.
- Repeating every Todo item inside the continuation input was rejected because it duplicates the turn-time Channel Work Snapshot and increases context drift risk.

### `slack-260721/ADR-D7` — Durably admit provider events before asynchronous processing

The provider ingress resolves the addressed external connection, verifies the provider request, and durably admits an external event before returning a successful provider acknowledgement.

External event admission is unique by connection and provider event identity. A repeated provider delivery returns the existing admission result instead of creating another event or invocation. The transaction stores the bounded provider envelope, provider and receipt timestamps, event type, retry metadata, and processing state required for recovery.

A successful provider response is sent only after durable admission commits. Thread hydration, external resource and message reconciliation, principal resolution, access evaluation, session or binding creation, transcript projection, and Agent invocation run asynchronously outside the provider HTTP request.

A worker claims accepted events and applies idempotent domain effects with at-least-once processing. Provider event identity deduplicates delivery; external message identity reconciles message create, edit, and delete lifecycle. Distinct events are not assumed to arrive in provider message order. Canonical per-resource ordering uses provider-native message identity and timestamps with late-event reconciliation.

Context-only events and authorized invocation events share durable admission but retain separate session scheduling behavior. The External Channel producer owns whether normalized session input wakes the AgentSession or remains context-only; the low-level input-buffer writer does not infer wake behavior.

If durable admission fails, the ingress does not acknowledge success and allows the provider retry contract to recover the event. If processing fails after admission, the event remains recoverable without requiring provider redelivery.

This decision satisfies `slack-260721/REQ-3`, `slack-260721/REQ-4`, `slack-260721/REQ-5`, `slack-260721/REQ-6`, and `slack-260721/REQ-11`.

Rejected alternatives:

- Verifying and publishing only to a transient broker before acknowledgement was rejected because an acknowledged event could be lost before durable state exists and restart-safe deduplication would be unavailable.
- Completing hydration, authorization, session mutation, and Agent input admission inside the provider request was rejected because provider acknowledgement would inherit external API latency, session contention, and Agent-domain failure.

### `slack-260721/ADR-D8` — Apply channel state immediately and attempt each provider delivery once

A valid atomic channel action commits its Channel Work and Todo state immediately. The same transaction creates durable delivery-attempt records for each required external side effect, such as posting a conversational message or creating, updating, or deleting the progress projection.

After commit, the channel action tool attempts each provider operation exactly once. The system does not automatically retry failed, rate-limited, timed-out, or unknown provider operations. A later retry is a new explicit channel action or manager operation with a new delivery identity.

Each attempt records and returns a structured outcome:

- `delivered` when the provider confirms success, including the resulting external message identity;
- `failed` when the provider returns a known failure;
- `unknown` when the request outcome cannot be determined safely, including timeout or process interruption after the durable state commit; or
- `not_attempted` when execution stops before the provider request begins.

The Agent receives the actual attempt outcome through the channel-action tool result. Delivery status is also durable and appears in subsequent Channel Work model context and management projection. A failed or unknown attempt is never reported as successful.

Provider delivery failure does not roll back the committed Channel Work transition. A `finish` action remains terminal even if its final conversational message or progress deletion fails. A `continue` action retains its updated Todo state even if the conversational message or progress update fails. The Agent may react to the transparent tool result by issuing another explicit action, but the platform does not silently create another attempt.

Progress projection follows canonical desired state without automatic convergence retries:

- active work commits the latest desired progress content and attempts one create or update;
- finished work commits that no progress projection should remain and attempts one deletion;
- projection failure leaves the canonical DB state unchanged and records that Slack may be missing or stale; and
- a later explicit Channel Work update may make a new attempt to project the then-current desired state.

When one channel action requires multiple provider operations, each operation is attempted once and receives an independent result. Failure of a final conversational message does not prevent the required one-time progress deletion attempt because the committed Channel Work is already terminal.

A stale pending attempt discovered after crash recovery is marked `unknown` or `not_attempted` according to available evidence and is surfaced without automatic provider execution.

This decision satisfies `slack-260721/REQ-7`, `slack-260721/REQ-9`, `slack-260721/REQ-10`, `slack-260721/REQ-12`, and `slack-260721/REQ-13`.

Rejected alternatives:

- Direct provider execution before the domain commit was rejected because provider success could exist without the corresponding durable Channel Work state.
- Automatic durable outbox retry was rejected because the Agent would not know the immediate communication outcome and repeated provider execution could occur without a new explicit Agent decision.
- Waiting indefinitely for a terminal provider result was rejected because provider outage and rate limits would block the Agent run.

### `slack-260721/ADR-D9` — Support HTTP and Socket Mode without requiring capability parity

A Slack connection explicitly selects either HTTP Events API or Socket Mode as its active inbound transport. One connection never activates both transports concurrently, and transport switching is an explicit lifecycle operation that stops the previous transport before the replacement becomes active.

Both transports normalize provider envelopes into the same External Event admission contract from `slack-260721/ADR-D7`. Connection, provider event, message, resource, principal, and binding identity remain transport-independent.

HTTP is the reference transport for complete production capability. Multiple dedicated Apps may share one HTTP endpoint; the ingress resolves the connection from Slack App identity and verifies the request with the connection-specific signing secret before durable admission.

Socket Mode is a supported transport because it materially improves local development and can serve environments that do not expose a public HTTP callback. It uses connection-specific Socket Mode credentials and a durable connection-ownership lifecycle before forwarding envelopes to the common admission path.

Feature parity is not required. If Slack does not expose a required event, interaction, installation, revocation, or other capability through Socket Mode, that capability is unavailable for the affected Socket Mode connection. The product exposes transport capability and does not silently emulate the missing feature, fall back to HTTP, or claim parity.

Transport-specific acknowledgement, reconnect, lease, and credential behavior remain inside the Slack adapter. They do not change accepted External Event semantics or AgentSession processing.

This decision satisfies `slack-260721/REQ-2`, `slack-260721/REQ-3`, `slack-260721/REQ-11`, and `slack-260721/REQ-13`.

Rejected alternatives:

- HTTP-only support was rejected because developing and testing manually created dedicated Slack Apps without Socket Mode imposes excessive callback and tunnel overhead.
- Requiring complete HTTP and Socket Mode feature parity was rejected because provider capability gaps should remain explicit instead of adding transport-specific emulation and operational complexity.

### `slack-260721/ADR-D10` — Support App-member public and private channels and exclude Slack Connect

The first release supports Slack public and private channels only when the dedicated App is an explicit member of the channel. App membership is the common permission boundary for receiving mentions and thread events, hydrating available thread context, and publishing replies or progress messages.

The Slack adapter requests the minimum scopes needed for direct mentions, public and private channel history, App-member channel publication, and bounded user display metadata. It does not request direct-message history, reaction or shortcut capabilities, user email without a separate requirement, or permission to publish into public channels where the App is not a member.

HTTP and Socket Mode connections expose the same public/private channel product scope. Transport-specific credentials, acknowledgement, reconnect, and degraded-state behavior do not change channel eligibility.

Slack Connect shared channels are outside the guaranteed first-release scope. The adapter must not claim that cross-organization identity, shared-channel lifecycle, profile availability, or original-message link access has been verified. Later Slack Connect support may reuse the External Principal and External Resource boundaries without changing the current dedicated-App channel contract.

Direct messages, group direct messages, message shortcuts, reactions, slash commands, and bot-triggered Agent invocation remain outside the first-release scope.

This decision satisfies `slack-260721/REQ-2`, `slack-260721/REQ-3`, `slack-260721/REQ-4`, and `slack-260721/REQ-11`.

Rejected alternatives:

- Public-channel-only support was rejected because common incident, security, and support workflows operate in private channels and can use explicit App membership as a clear permission boundary.
- First-release Slack Connect support was rejected because cross-organization principal identity, shared-channel lifecycle, reduced profile metadata, and multi-workspace E2E would materially expand the initial delivery.

### `slack-260721/ADR-D11` — Use source-aware external message items and scoped management surfaces

External-channel input uses a dedicated canonical event and payload contract rather than an ordinary Azents user-message event. Model-provider compatibility may lower the item through a generic `user` role, but the lowered content uses an explicit source envelope that preserves provider, external resource, sender, author type, message kind, invocation authorization state, timestamp, and safe body.

Web presentation reuses the established internal Agent-message interaction family without conflating the two event types. An external message renders as a compact, left-aligned, collapsed source row rather than a human user bubble. The collapsed row identifies provider, external conversation or resource, sender, time, and invocation eligibility. An accessible expansion reveals the safe message body and detailed source and authorization metadata.

When the provider exposes a stable message permalink, the External Channel adapter validates that the URL belongs to the associated provider, connection, and resource before projection. Expanded details render a dedicated accessible external-link action that opens in a new tab with enforced `noopener noreferrer`. Missing or invalid links render no action and never hide canonical content.

Live and durable projections share one semantic external-message identity. Durable history replaces live state without duplicate or disappearing rows, while expansion state remains UI-local. External-message presentation, Channel Work status, and delivery results never cause ordinary Web assistant output to publish externally.

Management is placed at the lifecycle owner:

- Agent Settings contains External Channel connections, Agent routes, transport and health state, Agent-level grants and blocks, reconnect, and terminal connection disconnect.
- The AgentSession channel-management surface contains active and terminated session bindings, Session grants, Channel Work and Todo state, delivery outcomes, cleanup failures, and terminal subscription disconnect.
- The durable approval page shows the external subject, Agent, external resource, and safe source-message preview and permits Session Allow, Agent Allow, Deny, or Block only after server-side approver authorization is revalidated.

The Web projection surfaces `delivered`, `failed`, `unknown`, and `not_attempted` outbound results without rewriting canonical Channel Work state. Transport degradation and projection drift remain visible operational states rather than hidden fallback behavior.

This decision satisfies `slack-260721/REQ-6`, `slack-260721/REQ-9`, `slack-260721/REQ-12`, `slack-260721/REQ-13`, `slack-260721/REQ-14`, and `slack-260721/REQ-15`.

Rejected alternatives:

- Rendering external input as an ordinary human user bubble was rejected because it hides non-Azents provenance and invocation authority from both the user and model.
- Rendering raw provider webhook envelopes as the primary UI was rejected because transport metadata is not the user-facing conversation and may contain unsafe or irrelevant fields.
- Using generic Markdown links as the original-message contract was rejected because provider permalinks require dedicated validation and consistent external-link behavior.

### `slack-260721/ADR-D12` — Stage bounded external context until an authorized invocation from the same resource

Context-only external messages are normalized and stored in the External Channel domain without immediately entering AgentSession transcript, Web conversation, model context, or compaction state. Pending context is scoped to one external connection, Agent route, and external resource.

Only an authorized external invocation from the same external resource releases pending context. Azents Web input, generic Channel Work continuation, an authorized invocation from another binding, and context-only activity never flush the staged messages.

When an authorized external message is accepted, the processor selects retained pending messages after the resource's last projected position and through the triggering message, orders them by canonical provider message position, and projects each message into the AgentSession as an individually identifiable external-message event. The events are lowered together as one source-labeled external channel turn, with each message retaining sender, author type, authorization state, timestamp, and safe body. Only the authorized triggering message supplies invocation authority.

The Web timeline receives the external message items only after this projection. Messages remain individually expandable and linkable even when model lowering groups them into one external channel turn.

Pending context is bounded per external resource by all of the following initial limits:

- maximum age of seven days;
- maximum count of 100 messages; and
- maximum normalized body and metadata size of 256 KiB.

The earliest exceeded limit removes the oldest pending content first. The system retains enough aggregate state to report the omitted count or range and inserts an explicit truncation marker when a later authorized invocation releases the remaining context. Binary attachment content is not fetched merely for staging.

Disconnecting the session binding or its connection deletes pending content that was never projected into the AgentSession. Provider-event deduplication and bounded operational metadata may remain under their separate retention policy without preserving the removed message body.

A late provider message whose canonical position precedes an already projected trigger is not inserted retroactively into the earlier Agent turn. It remains pending for the next authorized invocation from that resource, subject to the same retention limits, and is labeled as late context when projected.

This decision satisfies `slack-260721/REQ-4`, `slack-260721/REQ-5`, `slack-260721/REQ-11`, `slack-260721/REQ-14`, and `slack-260721/REQ-15`.

Rejected alternatives:

- Immediately projecting every context-only external message into AgentSession history was rejected because unrelated Web input or continuation would expose unapproved external conversation to the model.
- Retaining pending context without age, count, or size limits was rejected because automated provider messages could create unbounded hidden storage.
- Fetching all pending context from the provider only when an authorized message arrives was rejected because rate limits, deletion, edits, connection loss, and changed membership can make context unavailable or delay Agent execution.

### `slack-260721/ADR-D13` — Treat external-channel state as non-critical to session archive and disconnect it immediately

An otherwise eligible Agent session archive is not blocked by active external-channel bindings, pending context, Channel Work, or unresolved provider cleanup. Existing critical session-execution fences, including an active AgentRun, continue to govern archive eligibility.

This later feature decision introduces a scoped terminal-on-archive policy for non-critical External Channel state. It intentionally extends the earlier `session-260721` lifecycle contract, whose generic `mutate` policy requires symmetric restore and whose initial requirements exclude destructive external cleanup during archive. Ordinary reversible participant mutations remain symmetric. A terminal-on-archive participant instead performs a required atomic database mutation during archive, declares no restore inverse, and may initiate a non-authoritative post-commit cleanup attempt whose failure does not change the archive result.

The archive transaction immediately makes every binding to the archived session terminal, ends active Channel Work, removes never-projected pending context, fences invocation and Channel Action against the archived session, and commits one progress-cleanup delivery intent when a projected progress message exists. These External Channel mutations and the AgentSession archive transition share one locked transaction so an archived session cannot retain an actionable binding.

Provider network cleanup runs only after the archive transaction commits and is attempted once under `slack-260721/ADR-D8`. A failed, unknown, or not-attempted progress deletion remains visible but never rolls back or delays the successful archive. Crash recovery records the transparent delivery outcome without executing an automatic retry.

Restoring the AgentSession changes only the session lifecycle. It does not reactivate a terminal binding, recreate removed pending context, resume ended Channel Work, or repeat provider cleanup. A later eligible provider invocation may create a new binding and new Channel Work under the normal linking rules.

Agent decommission uses the same archive-triggered External Channel lifecycle before retention purge and final Agent deletion. Workspace-owned provider connections remain independent from Agent deletion; Agent routes and their bindings are fenced and finalized explicitly rather than through foreign-key cascade.

This decision satisfies `slack-260721/REQ-10`, `slack-260721/REQ-12`, and `slack-260721/REQ-13`.

Rejected alternatives:

- Blocking session archive until every external binding was explicitly disconnected was rejected because external-channel activity is non-critical and should not prevent session removal.
- Suspending bindings for automatic reactivation on restore was rejected because disconnect is terminal and external context or provider state may have changed while the session was archived.
- Calling Slack before committing the archive or rolling back archive after cleanup failure was rejected because provider availability must not control canonical Session lifecycle.
- Encoding terminal disconnect as an ordinary asymmetric `mutate`/`preserve` pair was rejected because the registry should continue rejecting accidental missing restore behavior for reversible participants.

## Related Historical Documents

- `docs/azents/adr/0026-slack-byoa.md`
- `docs/azents/design/slack-byoa.md`
- `docs/azents/design/nointern-slack-integration.md`
- `docs/azents/adr/0034-chat-input-buffer.md`
- `docs/azents/adr/0047-chat-history-live-event-protocol.md`
- `docs/azents/adr/0058-session-todo-toolkit-state-ui.md`
- `docs/azents/adr/0062-goal-continuation-idle-hook.md`
- `docs/azents/adr/0137-linearize-input-buffer-boundaries-on-session-row-lock.md`
- `docs/azents/adr/0138-separate-input-acceptance-and-processing-idempotency.md`
- `docs/azents/requirements/session-260721-lifecycle-extensibility.md`
- `docs/azents/adr/session-260721-lifecycle-extensibility.md`
- `docs/azents/design/session-260721-lifecycle-extensibility.md`
