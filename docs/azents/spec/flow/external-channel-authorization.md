---
title: "External Channel Authorization"
created: 2026-07-22
tags: [backend, frontend, external-channel, authorization, security]
spec_type: flow
owner: "@Hardtack"
touches_domains: [external-channel, agent, conversation]
code_paths:
  - python/apps/azents/src/azents/services/external_channel/access.py
  - python/apps/azents/src/azents/services/external_channel/event_processor.py
  - python/apps/azents/src/azents/services/external_channel/management.py
  - python/apps/azents/src/azents/repos/external_channel/repository.py
  - python/apps/azents/src/azents/repos/external_channel/management.py
  - python/apps/azents/src/azents/api/public/external_channel/v1/management_route.py
  - python/apps/azents/src/azents/services/input_buffer.py
  - typescript/apps/azents-web/src/app/(app)/external-channel/access/**
  - typescript/apps/azents-web/src/features/external-channel-approval/**
api_routes:
  - /external-channel/v1/approval-requests/{access_request_id}
  - /external-channel/v1/approval-requests/{access_request_id}/decision
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channel-access
last_verified_at: 2026-07-23
spec_version: 2
---

# External Channel Authorization

## Principal Boundary

A Slack participant is an `ExternalChannelPrincipal`, not an Azents User or WorkspaceUser. Provider identity is scoped by provider tenant and user ID. Human, bot, app, and system authors are retained separately; only eligible human invocation messages enter the access decision flow.

## Unknown Participant Flow

An unknown human may contribute bounded same-route/resource pending context but cannot create an AgentSession, binding invocation, or Agent wake-up.

When the participant invokes the Agent:

1. The event processor creates one idempotent access request for the route and source message.
2. The request snapshots truncation counters, expires after seven days, and contains an opaque ID.
3. One ordinary Slack control-message intent is persisted and attempted once with an authenticated Azents approval URL.
4. The approval page requires an authenticated user who is an administrator of the routed Agent. Unauthorized, cross-Agent, missing, and expired requests do not disclose the request and appear not found or unavailable.

## Decisions

Supported decisions are `allow_session`, `allow_agent`, `deny`, and `block`.

- **Allow Session** creates or reuses the resource binding and grants the principal only for that AgentSession.
- **Allow Agent** creates or reuses the binding and grants the principal across active bindings for that Agent.
- **Deny** resolves only the current request.
- **Block** resolves the request and creates an Agent-scoped block that takes precedence over grants.

The decision transaction locks the route connection, active binding, resource, and request in that order, verifies an `active` or `degraded` connection plus the route relationship, active resource, and Agent lifecycle state, creates the External Channel AgentSession only when no active binding exists, and writes the binding, grant, and decision atomically. Repeating the same compatible Allow decision returns the existing binding and grant. Conflicting or stale decisions return a conflict instead of creating parallel state.

## Activation and Context Release

A new binding starts in `waiting_hydration`. It becomes active only after provider-history reconciliation and correlated-event completion. Authorized release selects unexpired pending revisions from the same binding route/resource through the trigger provider position, records immutable batch membership, and deletes only the released pending rows.

The resulting InputBuffer is `batch` scheduling with reference-only metadata containing the invocation batch ID. The buffer does not duplicate provider text. At promotion, the batch becomes contiguous `external_channel_message` events with the trigger identity and authorization state, and then wakes the bound AgentSession.

Later authorized original messages on an active binding create another immutable batch and wake the same Session. Edits and deletes update canonical provider state but do not independently invoke the Agent or rewrite prior projected history.

## Revocation

Agent administrators can revoke active grants or remove blocks. Grant revocation prevents future invocations but does not delete canonical messages, projected Session history, or unrelated grants. Binding and connection disconnect remain separate lifecycle operations.

## Changelog

- **2026-07-23** (spec_version 2) — Removed route lifecycle state from authorization admission; route identity remains while Agent lifecycle and resource state determine eligibility.
- **2026-07-22** (spec_version 1) — Promoted external-principal isolation, opaque approval, idempotent decisions, scoped grants/blocks, hydration-fenced activation, and same-binding pending-context release.
