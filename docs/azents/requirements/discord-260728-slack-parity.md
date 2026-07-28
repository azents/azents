---
title: "Discord External Channel Slack Parity Requirements"
created: 2026-07-28
tags: [discord, slack, external-channel, parity]
document_role: primary
document_type: requirements
snapshot_id: discord-260728
---

# Discord External Channel Slack Parity Requirements

- Snapshot: `discord-260728`
- Document reference: `discord-260728/REQ`
- Prior snapshot: [Discord Agent App Routing Requirements](discord-260726-agent-app-routing.md) (`discord-260726/REQ`)

## Problem

Discord External Channel infrastructure admits Gateway messages, validates signed
interactions, and can deliver basic Discord messages and files. However, it does not
complete the same participant and administrator journeys available through Slack.
Discord participants cannot reliably start a conversation from a selected message,
select an Agent, receive thread-scoped approval and Session feedback, or observe
Channel Work progress. Workspace administrators also cannot manage Discord Multi Apps
through the complete route, default, lifecycle, and impact surfaces available for Slack.

## Primary Actor

A Discord Guild participant who wants to start or continue an Agent conversation from a
Guild message, subject to the same route-selection and access-approval rules as a Slack
participant.

## Primary Scenario

A participant invokes an Azents Discord App from a Guild message. Azents retains that
message and its eligible conversation context, resolves or lets the participant select
an available Agent, creates or reuses the conversation thread, requests approval when
required, and, after approval, starts the bound Session. The participant receives the
same thread-scoped Session link, Agent replies, Channel Work progress, files, completion
cleanup, and recovery behavior available in Slack.

## Supporting Scenarios

- A Workspace administrator creates, validates, updates, routes, defaults, inspects,
  and disconnects a Discord Multi App through the same management capabilities as a
  Slack Multi App.
- A participant invokes an already-bound Discord conversation and continues the same
  immutable Agent binding.
- Discord history arriving before, during, or after the initiating event converges into
  the same bounded context behavior as Slack.
- Deleted or unavailable Discord progress messages recover or remain visibly failed
  under the same durable delivery rules as Slack.
- A Discord App connection is inactive, lacks a required capability, is rate-limited,
  or is disconnected without weakening access, binding, or delivery guarantees.

## Goals

- Make every current Slack External Channel user-visible capability available through
  Discord unless the provider lacks an equivalent primitive.
- Use Discord-native commands, components, threads, messages, and files without
  changing canonical authorization, binding, Session, Channel Work, or lifecycle
  semantics.
- Preserve PostgreSQL-canonical state, generation fencing, durable delivery outcomes,
  secret redaction, and no-replay behavior.
- Provide Discord Multi App management API, generated-client, and Workspace UI parity.
- Prove the full Discord journey through deterministic unit, integration, and E2E
  evidence.

## Non-Goals

- Changing Slack behavior, Slack contracts, or Slack management surfaces.
- Creating Discord-specific access policies, Session types, route-selection rules, or
  Agent binding semantics.
- Mapping Discord principals to Azents Users.
- Replaying ambiguous provider writes or persisting Discord interaction tokens, raw
  signatures, raw provider payloads, attachment URLs, or credentials.
- Adding unrelated Discord social features such as reactions, arbitrary slash-command
  workflows, or direct-message support.

## Requirements

### REQ-1. Equivalent invocation and message-shortcut entry points

A participant must be able to start a Discord Agent conversation from an eligible Guild
message through the same mention and selected-message capabilities available in Slack.

**Acceptance criteria**

- An eligible Discord mention and a selected-message command retain the initiating
  message, supported attachments, and bounded conversation context before execution.
- A selected-message command does not require the participant to copy or rewrite the
  source message.
- Existing bound conversations continue their immutable Agent binding.
- Duplicate, delayed, or repeated provider deliveries do not create another binding,
  invocation batch, or Session wake.

### REQ-2. Equivalent Multi App Agent selection

A participant must be able to select an available Agent when a Discord Multi App has no
effective channel default, with the same access-state and immutable-selection semantics
as Slack.

**Acceptance criteria**

- The selector lists only active Agents associated with the Discord Multi App.
- The selector distinguishes immediate access from approval-required access.
- Search and pagination preserve the complete route catalog rather than silently
  truncating it.
- A participant can select a pending conversation at most once.
- Selecting an approval-required Agent begins the existing approval path; selecting an
  immediately authorized Agent starts the same bound Session path as Slack.

### REQ-3. Thread-scoped conversation delivery

Every Discord External Channel conversation must use one deterministic Discord thread
or already-threaded conversation as its provider-visible boundary.

**Acceptance criteria**

- A root-message invocation creates or reuses the thread rooted at that source message
  after route resolution.
- An invocation already inside a Discord thread uses that existing thread.
- Approval controls, Session links, replies, progress pages, files, and cleanup target
  the same conversation thread.
- A root-channel approval control is never posted outside its relevant conversation
  thread.
- Concurrent or retried thread provisioning converges on one canonical resource and
  does not create another Session binding.

### REQ-4. Equivalent context hydration and authorization release

Discord must retain, reconcile, authorize, and release conversation context with the
same bounded and ordered behavior as Slack.

**Acceptance criteria**

- The service reconciles eligible Discord thread or source-channel history through
  bounded pages before activating a new binding.
- Out-of-order Gateway events and history pages converge without dropping eligible
  context or duplicating projected input.
- Access grants, session-scoped grants, blocks, denials, expiry, and revocation follow
  the current provider-neutral access model.
- Allow releases the retained invocation exactly once and wakes the bound Session after
  commit; deny and block never release new input.

### REQ-5. Equivalent Session, work, reply, file, and recovery lifecycle

After a Discord conversation becomes authorized, participants must receive the same
observable Session and Channel Work lifecycle as Slack.

**Acceptance criteria**

- Initial activation creates one Session link and one checking progress projection.
- Canonical Channel Work changes create, update, delete, and recover ordered Discord
  progress pages through the durable delivery ledger.
- Replies, continuations, completion, files, and Agent identity presentation are
  delivered in the conversation thread with the same one-attempt outcome semantics.
- A successfully delivered final reply enables progress cleanup; failed or ambiguous
  delivery does not falsely report cleanup success.
- A confirmed deleted or missing active progress page is recovered when canonical work
  remains active.

### REQ-6. Equivalent Discord Multi App administration

Workspace administrators must be able to manage a Discord Multi App through the same
operational capabilities available for a Slack Multi App.

**Acceptance criteria**

- Administrators can list, inspect, validate, update, impact-preview, and disconnect
  Discord Multi Apps.
- Administrators can list, add, remove, re-enable, impact-preview, and inspect routes.
- Administrators can list, replace, and clear Discord channel defaults.
- Every destructive operation preserves current permission checks and generation fences.
- Public API, generated clients, tRPC, and Workspace UI expose provider-correct Discord
  operations instead of requiring Slack-named calls.

### REQ-7. Equivalent lifecycle, security, and operational behavior

Discord parity must preserve the same durability, security, lifecycle, and diagnostic
contracts as Slack.

**Acceptance criteria**

- Connection activation validates and reports required Discord capabilities without
  exposing credentials or raw provider data.
- Interaction tokens, signatures, raw payloads, and attachment URLs remain transient or
  redacted according to the existing External Channel boundary.
- Gateway reconnect, credential failure, permission failure, disconnect, Session
  archive, Agent decommission, and cleanup keep current lease and generation fences.
- Provider-specific logs and operator evidence identify Discord correctly.

### REQ-8. Equivalent deterministic evidence

Discord parity is complete only when the same end-to-end behavior is demonstrated rather
than inferred from isolated adapter tests.

**Acceptance criteria**

- Deterministic tests cover interaction admission, shortcut source retention, selector
  navigation and selection, thread provisioning, history reconciliation, approval,
  binding activation, progress recovery, file delivery, and lifecycle cleanup.
- E2E covers invocation or selected-message command through approval, allow, Session
  wake, threaded reply, progress update, file output, completion cleanup, and retry or
  recovery boundaries.
- E2E covers Discord Multi App management and the Workspace management surface.
- Evidence excludes credentials, tokens, signatures, raw provider payloads, attachment
  URLs, and message content.

## Fixed Constraints

- Slack is the semantic source of truth for External Channel product behavior.
- Provider-native Discord mechanics may differ only where Discord does not expose the
  same primitive; they must preserve the same user-visible outcome and canonical state
  transitions.
- PostgreSQL remains canonical. Provider callbacks, Gateway sessions, interaction
  tokens, and Web UI state are not sources of truth.
- Existing lock order, configuration generation, app-claim generation, lease fencing,
  immutable binding, access approval, delivery ledger, and file authority guarantees
  remain mandatory.
- Discord interaction tokens and raw signed requests are request-local and are never
  persisted or replayed.
- No backward-compatibility fallback is introduced unless it is explicitly required by
  the current Slack contract.

## Open Assumptions

- Existing Discord provider credentials can be granted the required Guild permissions
  and application capabilities for message commands, thread delivery, history access,
  and interaction responses.
- Discord provider-native presentation may use bounded Markdown pages and components
  where Slack uses Block Kit, provided the required behavior and accessibility outcome
  are preserved.

## Confirmation

Confirmed by the requester on 2026-07-28: implement the complete P0 through P2 Discord
Slack parity scope and bring forward only decisions that are genuinely necessary. The
requester fixed Slack equivalence as the governing product rule.
