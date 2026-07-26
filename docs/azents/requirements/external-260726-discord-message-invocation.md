---
title: "Discord Message Invocation Requirements"
created: 2026-07-26
updated: 2026-07-26
tags: [discord, external-channel, agent]
document_role: primary
document_type: requirements
snapshot_id: external-260726
---

# Discord Message Invocation Requirements

- Snapshot: `external-260726`
- Document reference: `external-260726/REQ`

## Problem

A Discord mention can be admitted and recorded by the Gateway without creating an authorization request, Agent invocation, or provider-visible response. Participants receive no actionable outcome, while the system records the event as processed.

## Primary Actor

A Discord participant who mentions a configured Azents App in an eligible Guild conversation.

## Primary Scenario

A participant mentions the configured Discord App. If the participant already has valid access, the linked Agent receives the retained message exactly once and publishes its response to the same Discord conversation. If access is not yet granted, the participant receives an actionable approval request; after an authorized Workspace member approves it, the original retained message is delivered to the Agent and the Agent can respond in the same conversation.

## Supporting Scenarios

- A later human message in an already authorized and active Discord conversation wakes the existing Agent Session exactly once.
- An approver denies or blocks the request without creating an Agent invocation.
- A provider delivery failure remains visible as a durable terminal delivery outcome and does not silently grant access or duplicate an invocation.

## Goals

- Complete the safe Discord message-to-Agent and Agent-to-Discord response path.
- Preserve explicit authorization before an external provider principal can trigger Agent execution.
- Give a participant an observable outcome for an ungranted mention.

## Non-Goals

- Automatically map a Discord principal to an Azents User.
- Automatically grant external participants access.
- Change existing Slack authorization, invocation, or delivery behavior.
- Add Discord direct-message or group-DM support.
- Deploy directly to the production environment as part of this change.

## Requirements

### REQ-1. Actionable Discord mention outcome

An eligible Discord App mention must not be terminally recorded as processed without either releasing an authorized Agent invocation or creating a durable, provider-visible authorization outcome.

**Acceptance criteria**

- An already authorized mention creates one ordered invocation for the retained message and wakes the linked Agent Session.
- An ungranted mention creates one durable access request and one Discord-visible approval prompt when the Web approval URL is configured.
- A missing approval URL leaves a durable, inspectable non-delivery outcome rather than falsely reporting a response.

### REQ-2. Explicit authorization boundary

Discord provider identity remains provenance and admission authority only; it must not become an Azents execution User or receive implicit access.

**Acceptance criteria**

- No code path derives an Azents User identity or grant solely from a Discord user ID.
- Only an existing active grant or an authenticated approval decision can release an Agent invocation.
- Blocks and revoked grants prevent release of new Discord invocations.

### REQ-3. Approval-to-invocation completion

An authorized approval for a Discord access request must release the retained triggering message through the same durable Agent input boundary used by other External Channel providers.

**Acceptance criteria**

- Approval creates or reuses one resource binding and one Agent Session according to the chosen grant scope.
- The retained message is included in exactly one ordered invocation batch with a wake-producing mailbox item.
- Repeating the approval decision or retrying delivery does not create a second Agent Session or duplicate invocation.

### REQ-4. Same-conversation Discord response

After a released Discord invocation, the Agent can publish Channel Action responses to the resource's Discord conversation.

**Acceptance criteria**

- A valid Agent Channel Action response is delivered to the Discord thread or prospective root conversation associated with the binding.
- Provider delivery uses the existing durable delivery ledger and at-most-once behavior.
- Discord delivery failures are persisted with sanitized, actionable state and do not retry ambiguous provider writes automatically.

### REQ-5. Provider parity without Slack regression

The new Discord path must integrate with existing External Channel lifecycle and observability boundaries without changing established Slack behavior.

**Acceptance criteria**

- Existing Slack event-processor and access-decision tests remain green.
- Discord lifecycle state preserves route/resource/binding ownership and current generation/lease fencing.
- The current External Channel living specs describe the completed Discord behavior.

## Fixed Constraints

- PostgreSQL remains the canonical source of truth for resources, access requests, grants, bindings, invocations, work, and delivery attempts.
- Durable state must not retain credentials, raw provider bodies, interaction tokens, attachment URLs, or attachment bytes.
- Existing Discord Gateway owner/configuration/App-claim/lease generation fencing remains intact.
- Generated clients and OpenAPI artifacts are regenerated rather than hand-edited when affected.
- Local fake-container, multiprocess E2E, and migration-matrix checks are user-skipped rather than represented as passed when unavailable.

## Open Assumptions

- The configured Azents Web URL is the approval surface for the initial Discord release.
- Discord approval prompts may use a provider-native text link because Discord does not provide the Slack Block Kit URL-button surface used by the existing Slack prompt.

## Confirmation

Confirmed by the requester on 2026-07-26 before ADR and design decisions began.
