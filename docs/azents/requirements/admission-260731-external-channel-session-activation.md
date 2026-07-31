---
title: "External Channel Session Activation Requirements"
created: 2026-07-31
updated: 2026-07-31
tags: [external-channel, session, admission, delivery, recovery]
document_role: primary
document_type: requirements
snapshot_id: admission-260731
---

# External Channel Session Activation Requirements

- Snapshot: `admission-260731`
- Document reference: `admission-260731/REQ`

## Problem

An External Channel input can currently create and deliver a Session link before the triggering input becomes an executable Azents Session. If provider initialization or final admission then fails, the participant sees a link that returns 404 or a Session that is absent from the Agent's Session list, while no mailbox input exists to continue execution. The system has exposed progress even though admission failed.

## Primary Actor

A participant who invokes an Agent from a connected Slack or Discord conversation and follows the provider-visible link to the resulting Azents Session.

## Primary Scenario

1. An eligible Slack or Discord message invokes a routed Agent.
2. Azents durably creates and binds exactly one non-executing Session for that conversation.
3. Azents durably retains exactly one canonical non-executing mailbox input in the bound Session.
4. Azents delivers a link to that exact Session.
5. Azents delivers the initial progress projection.
6. Only after those steps succeed does Azents activate the Session and wake the Agent exactly once.

## Supporting Scenarios

- A crash or retry at any boundary resumes the same Session, input, and provider delivery intents.
- A provider initialization failure leaves the retained Session non-executing and never wakes the Agent.
- A duplicate provider callback cannot create another Session, input, provider mutation, or wake.
- A later message cannot overtake an earlier invocation whose Session activation is incomplete.
- Direct Slack HTTP, Slack Socket Mode, Discord HTTP interaction, and Discord Gateway ingress share the same activation semantics.

## Goals

- Eliminate provider links to absent or unqueryable Sessions.
- Prevent failed admission from starting or waking Agent execution.
- Preserve the triggering input durably across provider initialization and process crashes.
- Make activation retry-safe and ordered for every supported External Channel ingress profile.

## Non-Goals

- Automatically retry an ambiguous or terminal provider mutation.
- Reintroduce binding active/inactive status as a connectedness authority.
- Add compatibility fallbacks for the incorrect Session URL shape.
- Change the existing Agent Session page layout or External Channel presentation beyond the activation state needed for correctness.

## Requirements

### REQ-1. Durable non-executing Session binding

Azents must create and bind one durable Session before required provider initialization without starting or waking the Agent.

**Acceptance criteria**

- A crash after binding retains the same Session and binding.
- The Session remains non-running and no wake is dispatched before activation.
- Reprocessing the same invocation reuses the retained Session and binding.

### REQ-2. Real Session link

Every delivered provider Session link must resolve to the exact durable Session retained for the invocation.

**Acceptance criteria**

- The URL uses `/w/{workspace}/agents/{agent}/sessions/{session}`.
- Opening the link does not return 404 while the binding remains connected and the Session is retained.
- The same Session is present in the routed Agent's Session list.
- No legacy URL fallback is accepted.

### REQ-3. Ordered provider initialization after durable retention

The canonical mailbox input must be durably retained before the Session link and initial progress projection are delivered in order.

**Acceptance criteria**

- No provider initialization starts until the exact canonical mailbox input is durable.
- Each step begins only after the preceding step has a durable successful outcome.
- Failed, unknown, missing, incomplete, or deadline-expired initialization retains the mailbox input but never promotes it, marks the Session running, or dispatches a wake.
- A Session link delivered before a later initialization failure still points to the retained non-executing Session and input.

### REQ-4. Durable non-executing mailbox admission

Before required provider initialization, Azents must retain one canonical mailbox input without making it executable.

**Acceptance criteria**

- A crash before, during, or after provider initialization does not lose the triggering input.
- Reprocessing the same invocation reuses the retained mailbox input.
- The retained input cannot be promoted by another Session wake while activation is `initializing` or `blocked`.
- The Session is marked running and woken only after provider initialization durably succeeds for that retained mailbox input.

### REQ-5. Exactly-once activation

Successful recovery or retry must activate and wake the retained Session at most once.

**Acceptance criteria**

- Duplicate callbacks reuse the same Session, input, delivery attempts, and activation identity.
- A crash before or after activation commit cannot create duplicate input or duplicate execution.
- Wake recovery uses the same canonical mailbox identity.

### REQ-6. Conversation ordering

A later provider message must not execute before an earlier retained invocation completes activation.

**Acceptance criteria**

- Conversation position and activation state prevent overtaking across retries and replicas.
- Recovery of the earlier invocation occurs before later input is admitted for execution.
- The ordering rule does not depend on Redis persistence or availability.

### REQ-7. Shared ingress behavior

Slack HTTP, Slack Socket Mode, Discord HTTP interactions, and Discord Gateway messages must use the same durable activation protocol.

**Acceptance criteria**

- Transport acknowledgement remains contingent on a non-retryable durable outcome.
- Retryable activation or initialization outcomes remain recoverable through the provider's retry path.
- No transport-specific path creates a Session link or wake outside the shared protocol.

## Fixed Constraints

- Provider payloads, credentials, private URLs, and raw content must not be added to diagnostics or durable activation metadata.
- Provider delivery retains the existing one-attempt and ambiguous-outcome safety rules.
- `disconnected_at` remains the only binding connectedness authority.
- Outbound REST authorization remains independent of transient Gateway and Socket health.
- Redis remains optional and cannot be required for correctness.

## Open Assumptions

- A retained but non-executing Session may be displayed through the existing Session UI without introducing a new page layout.
- Existing mailbox and delivery identities can be extended or linked to represent activation recovery without retaining provider content.

## Confirmation

Confirmed by the requester on 2026-07-31 after observing a delivered Session link for an invocation that had not completed durable executable admission. The requester required an end-to-end correction rather than a URL-only or timeout-only patch.
