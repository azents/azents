---
title: "External Channel Session and Discord Thread Automatic Titles"
created: 2026-08-03
tags: [external-channel, session, discord, slack, title, architecture]
document_role: primary
document_type: adr
snapshot_id: title-260802
---

# External Channel Session and Discord Thread Automatic Titles

- Snapshot: `title-260802`
- Document reference: `title-260802/ADR`
- Requirements: [`title-260802/REQ`](../requirements/title-260802-external-channel-automatic-title.md)
- Mode: Collaborative
- Decision owner: requester

## Context

Direct Sessions already derive an immediate `auto_initial` title from the first user
message and later make a best-effort lightweight-model call that may replace it with
`auto_generated`. External Channel transcripts retain the exact human message that
authorized execution, but the current title helper accepts only `user_message` Events.

Discord root-message conversations create a thread with a provisional Agent-derived
name and retain the resulting delivery channel on the existing External Channel
Resource. Existing provider threads are reused without rename.

The required Discord update is deliberately one-shot best effort. It does not survive
failure, cancellation, process interruption, an unavailable thread, or provider
unavailability. The design therefore must not add a projection aggregate, retry
schedule, reconciliation scan, attempt history, new queue, or execution gate.

## Fixed Outcomes

- Only the first authorized human External Channel invocation for a newly created
  Session may enter the existing automatic Session-title lifecycle.
- Context-only messages, Bots, Agent output, tool results, provider identifiers,
  secrets, and attachment contents are excluded. Safe attachment names and media
  types may supplement the authorized body.
- Session creation, admission, wake, AgentRun creation, Agent output, and ordinary
  provider delivery never wait for title generation or Discord rename.
- Slack receives only the Session title behavior.
- A pre-existing Discord thread is never renamed.
- An Azents-created Discord thread is renamed only when its current name still equals
  the exact provisional name retained at creation.
- The provider read and update form one adjacent best-effort operation. Any failure or
  interruption ends the operation without retry, recovery, backfill, or attempt state.
- Later manual or automatic Session-title changes and later Discord title changes are
  independent.
- Delivery is one focused PR. No new deployment unit, runtime mode, configuration,
  Redis dependency, public API, or frontend workflow is introduced.

## Decision Backlog

- [x] D1. Minimal creation-boundary authority for the exact External Channel title
  source.
- [x] D2. Minimal evidence that a Discord thread was created by Azents with one exact
  provisional name.
- [x] D3. One-shot trigger and concurrency boundary when the final automatic title
  becomes available.

## Accepted Decisions

### title-260802/ADR-D1 — The creating mailbox carries one-time title eligibility

Only an admission transaction that creates the root Session and Binding marks its
existing canonical mailbox payload as eligible for initial automatic title
generation. The payload already owns the creating Binding and exact trigger
provider-message key.

During promotion, only the matching human `authorized_invocation` Event may enter the
existing automatic-title lifecycle. Promotion and mailbox deletion consume the
creation-boundary eligibility naturally. Duplicate delivery reuses the same mailbox;
later invocations, later Bindings, and pre-existing Sessions receive no eligibility.
The access-approved Session-creation path applies the same marker to its canonical
mailbox.

This decision adds no table, model column, lifecycle state, retry state, or cleanup
path.

Rejected alternatives:

- A Binding column would require a migration and explicit consumed/cleanup lifecycle
  for information already scoped to the existing one-time mailbox.
- Inferring eligibility from an empty Session title would allow a later External
  Channel invocation to title a pre-existing Session.

Affected requirements: `title-260802/REQ-1`, `title-260802/REQ-2`.

### title-260802/ADR-D2 — Direct thread creation stores minimal Resource-label evidence

The existing Discord thread-creation result distinguishes a direct successful POST
from an existing thread read. Only a direct successful create may add the exact
normalized provisional name to the existing External Channel Resource labels beside
the retained `delivery_channel_id`.

An existing thread and a thread observed only after an ambiguous create outcome retain
their normal delivery identity but receive no initial-title eligibility. Absence of
the provisional-name label means the thread is not eligible for automatic rename.
Later Agent names, Resource presentation labels, and name equality alone never create
eligibility.

This decision adds no table, model column, migration, attempt record, or lifecycle
state.

Rejected alternatives:

- Typed Resource columns would add a migration and wider model surface for optional
  best-effort metadata.
- Inferring ownership from the current Agent name could rename a pre-existing thread
  that happens to use the same name.

Affected requirements: `title-260802/REQ-3`, `title-260802/REQ-4`,
`title-260802/REQ-5`.

### title-260802/ADR-D3 — The winning automatic-title commit triggers one provider attempt

Only the successful `auto_initial` to `auto_generated` replacement for the exact
generation Event may initiate Discord title projection. After that Session-title
transaction commits, the service performs one best-effort provider operation for an
eligible External Channel Event.

The operation revalidates the exact Binding, Resource, Session, route, Agent,
connection, credentials, and Discord target. It reads the current thread once. If the
thread identity is valid and its current name equals the Resource's retained
provisional name, it immediately sends one name-only PATCH. An already matching final
title succeeds without PATCH. Every other name preserves provider ownership and ends
without mutation.

A missing or not-yet-created thread, missing eligibility metadata, lifecycle change,
provider rejection, rate limit, timeout, cancellation, transport ambiguity, or process
interruption ends the operation. There is no retry, reconciliation, backfill,
secondary trigger, attempt record, or terminal projection state. The committed
Session title and normal Agent execution remain unchanged.

Rejected alternatives:

- Triggering from both title completion and thread creation would create two
  competing paths and require duplicate-attempt coordination.
- A queue, Worker scan, or outbox would reintroduce durable projection and recovery
  semantics explicitly excluded by the Requirements.

Affected requirements: `title-260802/REQ-4`, `title-260802/REQ-5`,
`title-260802/REQ-6`, `title-260802/REQ-7`.
