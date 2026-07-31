---
title: "Direct Provider Conversation Continuity Design"
created: 2026-07-31
updated: 2026-07-31
implemented: 2026-07-31
tags: [external-channel, slack, discord, mailbox, backend, migration]
document_role: primary
document_type: design
snapshot_id: provider-260731
---

# Direct Provider Conversation Continuity Design

- Snapshot: `provider-260731`
- Document reference: `provider-260731/DESIGN`
- Requirements:
  [provider-260731/REQ](../requirements/provider-260731-direct-conversation-continuity.md)
- ADR: [provider-260731/ADR](../adr/provider-260731-direct-conversation-continuity.md)
- Mode: Collaborative

## Traceability

| Requirement | ADR | Design mechanism |
| --- | --- | --- |
| `provider-260731/REQ-1` | D1 | Shared synchronous ingestion service accepts provider history into one mailbox item and triggers the Session before success acknowledgement. |
| `provider-260731/REQ-2` | D1 | Deterministic mailbox idempotency key, atomic position advancement, pending-item wake recovery. |
| `provider-260731/REQ-3` | D2 | Selector interaction projection and access-request replay boundary. |
| `provider-260731/REQ-4` | D3 | Guarded Alembic backfill and contraction, retired runtime/model/repository removal. |
| `provider-260731/REQ-5` | D4 | Replaced file locator containing direct provider request coordinates. |

## Architecture

### Synchronous ingestion boundary

Slack HTTP, Slack Socket Mode, Discord HTTP, Discord Gateway, selector continuation, and
access Allow call the same conversation-ingestion service. The service performs:

1. ingress authority and trigger-locator validation;
2. conversation-position and provider resource resolution;
3. route, selector, access, binding, and Session resolution;
4. bounded provider-history retrieval;
5. one transactional mailbox enqueue and position advancement; and
6. post-commit Session wake dispatch using the mailbox item identity.

The inbound callback payload identifies the trigger but is not the message-content
source.

### Canonical mailbox admission

`ExternalChannelMailboxIngestionStore` constructs ordered immutable projection items
directly from the provider-history result. `MailboxService` serializes those items into
one `EXTERNAL_CHANNEL_INVOCATION` mailbox payload. Promotion appends the canonical
External Channel Session events; no intermediate message, revision, or batch row is
created.

The idempotency key is a digest of connection ID, conversation-position ID, trigger
provider message key, and trigger position. Duplicate preparation can find the existing
pending mailbox item and recover its wake.

### Selector and approval replay

An unbound Multi App invocation creates or reuses an `ExternalChannelInteraction` whose
`agent_selector` projection contains the typed replay boundary. Route selection replaces
that projection with the selected route and replay invokes the shared ingestion service.

An access request stores `trigger_provider_message_key` together with connection,
resource, principal, conversation position, range start, trigger position, and route.
Allow reloads those owners and invokes the same replay path. Neither owner stores provider
message content.

### File locator

The existing `external-file:v1` value is replaced in place with these components:

```text
external-file:v1:<provider>:<binding>:<channel>:<message>:<file>
```

Slack leaves channel and message empty because its API resolves a file from the provider
file ID. Discord requires numeric channel, message, and attachment IDs and calls the
provider directly with those values. Active binding, provider capability, credentials,
and provider responses remain the download checks. Session-event attachment lookup is
removed.

## Persistence and Migration

The migration performs these operations in order:

1. reject in-flight resource provisioning and pending or claimed legacy wake dispatch;
2. reject ambiguous or invalid open selector rows and provider-key collisions;
3. add and backfill `external_channel_access_requests.trigger_provider_message_key`;
4. migrate open selector admissions into typed interaction projections;
5. drop access-request references to legacy messages;
6. drop the six retired tables; and
7. drop the seven retired PostgreSQL enums.

Downgrade recreates only an empty structural shape and is blocked while retained access
requests exist. Removed provider content is never reconstructed.

## Failure and Recovery

- Provider-history, persistence, or mailbox failure leaves the prior conversation
  position unchanged.
- A position compare-and-set mismatch restarts from the new durable position.
- A provider redelivery reuses the mailbox idempotency key.
- A broker failure leaves the pending mailbox item available for wake recovery.
- Selector and access replay reject missing or cross-connection owners.
- Migration blockers expose aggregate counts only.

## Removal and Replacement

| Removed unit | Replacement or remaining authority | Absence verification |
| --- | --- | --- |
| `external_channel_messages`, `external_channel_message_revisions` | Provider history before acceptance; Session events after mailbox promotion | ORM metadata, installed schema, production symbol search |
| `external_channel_invocation_batches`, `external_channel_invocation_batch_items` | Canonical mailbox item and embedded ordered payload | Repository/service deletion and focused ingestion tests |
| `external_channel_conversation_admissions` | Selector interaction projection; access request for approval | Selector, interaction, replay, lifecycle tests |
| `external_channel_resource_provisionings` | Synchronous provider conversation resolution; no independent durable owner | Migration blocker and schema tests |
| Invocation wake-dispatch state | Pending mailbox item plus Session broker dispatch | Duplicate and wake-recovery tests |
| Session-event file-source lookup | Direct provider coordinates in the replaced file key | Locator and provider-file transfer tests |
| Legacy DTOs, enums, repository methods, fixtures, and lifecycle paths | Typed retained owners above | Ruff, Pyright, grep, backend tests |

No generated public API client change is required because the removed units were internal
persistence and service contracts. The compatibility-facing Session event payload remains
readable for existing chat and model-lowering consumers.

## Security and Privacy

- Provider credentials are loaded only after active binding and capability validation.
- Provider authentication and permissions determine file access; the file key is an
  address, not an authorization token.
- Logs, migration errors, and test evidence exclude message bodies, attachment URLs,
  credentials, and provider identifiers.
- Replay validates connection ownership before provider history retrieval.

## Test Strategy

### Primary verification

Deterministic provider fakes and focused service tests verify the end-to-end application
boundary for Slack HTTP, Slack Socket Mode, Discord HTTP, Discord Gateway, selection,
approval, mailbox acceptance, duplicate recovery, and file download.

### PostgreSQL verification

Migration tests run against PostgreSQL and verify access-request backfill, selector
projection migration, retired table and enum removal, in-flight cutover blockers,
data-bearing downgrade rejection, and empty structural downgrade.

Repository and installed-schema tests verify retained foreign keys and the absence of
retired owners.

### CI policy

- Ruff, formatting, and Pyright must pass without warnings or errors.
- The complete backend pytest suite must pass.
- Relevant deterministic External Channel E2E must pass when its local provider fakes are
  available; missing required fixtures fail rather than silently skip.
- CI evidence records only test names, counts, and aggregate failures.

## Feasibility

| Requirement | Result | Evidence |
| --- | --- | --- |
| REQ-1 | Feasible | Existing shared ingestion boundary and transport-focused tests |
| REQ-2 | Feasible | Mailbox idempotency and wake dispatcher implementation |
| REQ-3 | Feasible | Typed selector and access replay tests |
| REQ-4 | Feasible | PostgreSQL migration and installed-schema tests |
| REQ-5 | Feasible | Provider locator and Slack/Discord transfer tests |

No unresolved design blocker remains. Verification completion determines the snapshot's
`implemented` date.
