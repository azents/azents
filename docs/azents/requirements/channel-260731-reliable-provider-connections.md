---
title: "Reliable External Channel Provider Connections Requirements"
created: 2026-07-31
updated: 2026-07-31
implemented: 2026-07-31
tags: [external-channel, slack, discord, reliability]
document_role: primary
document_type: requirements
snapshot_id: channel-260731
---

# Reliable External Channel Provider Connections Requirements

- Snapshot: `channel-260731`
- Document reference: `channel-260731/REQ`

## Problem

Slack and Discord connections can report or retain an unhealthy transport state when provider connection lifecycle behavior is duplicated outside the provider-supported client boundary. This increases the risk that valid External Channel Apps stop receiving callbacks until an operator intervenes, while the configured connection and Agent routes still appear usable.

## Primary Actor

A Workspace or Agent administrator who has configured a valid Slack or Discord External Channel App and expects it to keep receiving supported provider conversations.

## Primary Scenario

A configured Slack or Discord connection is active, encounters a recoverable provider or network lifecycle transition, and continues receiving supported provider callbacks after recovery. Each callback is durably admitted before the provider receives its acknowledgement, and management health accurately reflects whether the connection needs operator action.

## Supporting Scenarios

- A worker shuts down, loses ownership, or is replaced while another replica is eligible to take over the connection without stale mutation.
- Slack delivers the same supported callback through signed HTTP or Socket Mode and receives an acknowledgement only after the durable outcome is safe.
- Discord reconnects or resumes a Gateway session without Azents persisting or interpreting provider protocol session state.
- Invalid credentials, disallowed intents, or another non-recoverable provider outcome become a sanitized reconnect-required health state.

## Goals

- Keep supported Slack and Discord transports available across recoverable connection lifecycle events.
- Preserve durable admission, authorization, routing, provider-history, and acknowledgement-ordering guarantees.
- Limit Azents-owned transport behavior to responsibilities that cannot safely be delegated because they enforce durable state, security, ownership, or replica fencing.
- Make connection health and diagnostics reflect the real transport outcome without exposing provider content or credentials.
- Verify the complete behavior with regression coverage before release.

## Non-Goals

- Adding a provider or transport.
- Removing Slack HTTP, Slack Socket Mode, Discord signed interactions, or Discord Gateway support.
- Changing App mode, Agent routing, access policy, provider-history sourcing, binding, Session, Channel Work, delivery, or file-transfer behavior.
- Restoring provider edit/delete correction, external bot invocation, pending-context state, hydration activation, or the retired Event Processor.
- Persisting provider WebSocket session, sequence, resume, callback payload, or transient endpoint authority.
- Changing provider-visible message or interaction presentation.

## Requirements

### REQ-1. Recoverable connection continuity

A valid Slack or Discord connection must recover from provider-declared or network-recoverable lifecycle transitions without operator intervention or loss of its configured Agent routes.

**Acceptance criteria**

- A recoverable Slack Socket Mode disconnect establishes a healthy replacement connection and continues admitting supported callbacks.
- A recoverable Discord Gateway disconnect reconnects or resumes through the provider-supported client lifecycle and continues admitting supported callbacks.
- Recovery does not create concurrent authoritative owners for one configured connection.

### REQ-2. Explicit non-recoverable health

A connection that cannot safely recover with its current configuration must stop automatic admission and expose a stable, sanitized reconnect-required reason.

**Acceptance criteria**

- Invalid credentials, revoked authority, and required-intent failures do not enter an unbounded reconnect loop.
- The retained reason contains no credential, endpoint, provider payload, message content, or arbitrary provider error text.
- Existing route, binding, and historical state remains intact unless the existing lifecycle contract explicitly terminalizes it.

### REQ-3. Durable admission before acknowledgement

Slack callbacks must be acknowledged only after the corresponding admission or interaction outcome has crossed its required durable boundary.

**Acceptance criteria**

- Retryable ingestion remains unacknowledged so Slack can redeliver it.
- Duplicate delivery converges on the existing durable outcome rather than creating a second invocation.
- Socket Mode lifecycle recovery never implicitly acknowledges an envelope that did not complete admission.

### REQ-4. Fenced multi-replica ownership

Connection ownership and all connection-scoped durable mutations must remain fenced across worker replacement, shutdown, lease expiry, and concurrent replicas.

**Acceptance criteria**

- A stale Slack or Discord owner cannot renew, admit, record health, acknowledge provider work, or release a newer owner's authority.
- Shutdown stops new admission before releasing current ownership.
- Provider-supported in-process reconnect behavior cannot outlive Azents lease authority.

### REQ-5. Provider-conformant transport ownership

Azents must not independently own provider protocol mechanics that the maintained provider client already supplies unless retaining that behavior is necessary to satisfy REQ-2, REQ-3, or REQ-4.

**Acceptance criteria**

- Connection discovery, heartbeat or Ping/Pong, frame receipt, standard envelope construction, reconnect, Resume, and equivalent provider mechanics use the provider-supported client behavior where available.
- Every retained Azents transport or lifecycle responsibility has a documented durability, security, acknowledgement-ordering, or replica-fencing justification.
- Production behavior does not depend on mutating private provider-client transport state.

### REQ-6. Truthful, content-free operational evidence

Operators and automated checks must be able to distinguish a running worker, an owned healthy provider connection, a recoverable transition, and a configuration that requires intervention.

**Acceptance criteria**

- Connection health changes follow actual provider-client lifecycle outcomes rather than task existence alone.
- Worker readiness does not report ready after its supervised connection manager has failed or entered shutdown.
- Logs, metrics, test evidence, and health responses use bounded reason codes and counts without provider IDs, callback bodies, message content, endpoints, credentials, or secrets.

### REQ-7. Regression safety

The corrected ownership boundary must preserve the supported end-to-end External Channel contract for both providers.

**Acceptance criteria**

- Automated coverage proves Slack signed HTTP admission, Slack Socket Mode durable acknowledgement and recovery, Discord signed interaction admission, Discord Gateway message admission and recovery, replica fencing, and non-recoverable health transitions.
- Existing External Channel unit, integration, generated-contract, documentation, and repository quality checks pass.
- The implementation is delivered in one reviewable pull request whose latest head passes required CI.

## Fixed Constraints

- Redis-backed coordination remains fail-closed where the current External Channel contract requires cross-replica coordination; there is no implicit in-memory fallback in that path.
- Provider callback content is not canonical message authority; supported provider history remains the canonical source for admitted conversation context.
- Credentials, provider endpoints, payloads, message content, and transient interaction authority must not enter logs, health responses, tracked evidence, or durable transport state.
- Public provider APIs and maintained provider-supported clients are the compatibility boundary. Private client state may be used only inside deterministic test infrastructure when no public injection boundary exists, and must not alter production endpoint or lifecycle selection.
- API contract changes require regenerated OpenAPI and generated clients. Testenv verification must use product APIs and fixtures rather than direct product-database writes.
- The work is delivered as one additive PR and is not merged without explicit requester approval.

## Open Assumptions

- Slack Socket Mode remains a supported selectable transport even though a currently observed deployment uses Slack HTTP.
- Existing provider-supported client versions can satisfy the required lifecycle behavior without a product-visible configuration migration.
- Deterministic fake-provider tests may retain an isolated test-only endpoint seam when the provider client exposes no public equivalent.

## Confirmation

Confirmed by the requester on 2026-07-31 through the explicit directive to correct both Discord and Slack transports, create one pull request, and reach passing CI.
