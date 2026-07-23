---
title: "External Channel"
created: 2026-07-22
tags: [backend, frontend, external-channel, slack, security]
spec_type: domain
domain: external-channel
owner: "@Hardtack"
code_paths:
  - python/apps/azents/db-schemas/rdb/migrations/versions/*external_channel*.py
  - python/apps/azents/src/azents/core/external_channel.py
  - python/apps/azents/src/azents/core/enums.py
  - python/apps/azents/src/azents/rdb/models/external_channel.py
  - python/apps/azents/src/azents/repos/external_channel/**
  - python/apps/azents/src/azents/services/external_channel/**
  - python/apps/azents/src/azents/api/public/external_channel/**
  - python/apps/azents/specs/public/openapi.json
  - python/libs/azents-public-client/src/azentspublicclient/api/external_channel_v1_api.py
  - python/libs/azents-public-client/src/azentspublicclient/models/external_channel_*.py
  - python/libs/azents-public-client/src/azentspublicclient/models/managed_*.py
  - typescript/apps/azents-web/src/features/external-channel-approval/**
  - typescript/apps/azents-web/src/features/external-channel-management/**
  - typescript/apps/azents-web/src/features/session-channels/**
  - typescript/apps/azents-web/src/trpc/routers/externalChannel.ts
api_routes:
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/manifest
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/slack
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/slack
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channel-access
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/external-channels
  - /external-channel/v1/approval-requests/{access_request_id}
last_verified_at: 2026-07-22
spec_version: 3
---

# External Channel

## Overview

External Channels connect provider conversations to Azents Agents without treating provider credentials, conversations, participants, or delivery state as AgentSession-owned chat data. Workspace owns connection credentials and provider identity. An Agent route selects the Agent for a connection. A resource represents one provider conversation, and an active binding links that resource to one AgentSession.

Slack is the first provider. Each connection uses a manually configured dedicated Slack App and selects either signed HTTP callbacks or Socket Mode. One Agent may own multiple connections, and one AgentSession may contain multiple independent bindings.

## Ownership and Security Boundaries

- Connection and route records are Workspace/Agent administration state.
- Provider resources, canonical events, principals, messages, and immutable revisions are retained independently from AgentSession history.
- Bindings, invocation batches, Channel Work, channel actions, and delivery attempts are Session lifecycle resources.
- Credentials are encrypted at rest and decrypted only inside provider adapters. Public APIs, generated clients, prompts, events, logs, UI state, and test evidence expose only redacted credential status.
- Provider message content remains external input even after approval. It retains provider, resource, sender, author type, authorization, message identity, and revision attribution.
- Foreign keys are restrictive across lifecycle roots. AgentSession deletion cannot cascade away provider or audit roots before lifecycle cleanup and verification complete.

## Core Records

| Record | Current contract |
| --- | --- |
| Connection | Workspace-owned provider app identity, selected transport, encrypted credentials, capability/health snapshot, terminal disconnect state, and Socket lease/gap state. |
| Agent route | Binds one connection to an Agent. Current Slack management creates a dedicated active route. |
| Resource | One Slack thread with provider labels, availability, hydration cursor/high-watermark, reconciliation boundary, and latest activity. |
| Event | Durable provider envelope admission keyed by connection and provider event identity. Processing is at-least-once and domain writes are idempotent. |
| Principal | Provider tenant/user identity and author category. It is not an Azents User or WorkspaceUser. |
| Message and revision | Canonical provider message plus immutable original/edit/delete revisions. `original_url` is nullable and is set only from a successful provider permalink lookup. |
| Pending context | Unprojected same-route/resource revisions retained for at most 7 days, 100 messages, and 256 KiB. Oldest content is expired or trimmed first. |
| Binding | Active or disconnected link from one route/resource to one AgentSession. Initial activation waits for hydration reconciliation. |
| Invocation batch | Immutable ordered revision membership released through one authorized trigger and referenced by a batch InputBuffer. |
| Access request/grant/block | Opaque approval request, Session- or Agent-scoped grant, and Agent-scoped block for one external principal. |
| Channel Work/action/delivery | Binding-scoped durable tasks, one atomic explicit action, and persisted provider intents/outcomes. |

## State Invariants

- Active connections may be `configuring`, `active`, `degraded`, or `reconnect_required`; disconnect is terminal and does not silently fall back to another transport.
- Provider health transitions do not deactivate Agent routes. Explicit manager disconnect and Agent decommission remain the route lifecycle boundaries.
- A resource is `active`, `unavailable`, or `deleted`; hydration is `pending`, `running`, `complete`, `bounded`, or `incomplete`.
- A binding is either active or disconnected. Activation moves from `waiting_hydration` to `active` only after the admitted-event reconciliation boundary is clear.
- Message revisions never rewrite an already projected revision. Later edits or deletes remain distinct corrections.
- A Session- or Agent-scoped grant authorizes invocation only for the same Agent, principal, active route, and active resource. Blocks take precedence.
- Restore never reactivates a disconnected binding, ended work item, removed pending context, route, or connection.

## Management Surface

Agent administrators can retrieve a complete copy-ready Slack App Manifest, follow
equivalent manual Slack UI instructions, create a connection and route, validate a
connection, replace its App ID, transport, and complete credential set, disconnect
it terminally, and manage grants and blocks. Saving setup or replacement values
immediately validates them together. Secret fields remain blank and required when an
existing connection is edited.

Slack validation first uses `auth.test` to resolve Team and Bot identity, then uses
`bots.info` to verify that the Bot Token's actual App ID equals the configured App
ID. An App ID copied from a different Slack App is rejected as a recoverable
configuration error rather than being marked active. Validation also checks the
provider-reported OAuth scope header when present and requires the message,
conversation-history, conversation-metadata, posting, and user identity scopes used
by the adapter.

Disconnect has no lifecycle-status admission guard. It disables inbound routing,
clears credentials, terminalizes owned live state, and commits the terminal
connection before attempting provider cleanup. Repeating disconnect is safe.
Disconnected rows remain as retained history roots but are omitted from the active
Agent connection list.

Session Channels shows bindings, work state, truncation, delivery outcomes, grants,
and terminal disconnect state. Approval links contain only an opaque access-request
ID and require an authenticated Agent administrator; unauthorized and missing
requests are returned as not found.

Connection responses expose provider identity, capabilities, health, route, and redacted credential state. They never return ciphertext or decrypted secret values.

## Changelog

- **2026-07-22** (spec_version 3) — Separated provider health from Agent route lifecycle, fenced stale validation results, and required Slack conversation metadata scopes.
- **2026-07-22** (spec_version 2) — Added copy-ready Slack App setup guidance, App/Token ownership validation, complete connection replacement, unconditional idempotent disconnect, and active-list filtering for disconnected connections.
- **2026-07-22** (spec_version 1) — Promoted the External Channel ownership model, persistence graph, management API, security boundaries, Slack-first provider scope, and Session binding contract.
