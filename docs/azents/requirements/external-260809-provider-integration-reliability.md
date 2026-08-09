---
title: "External Channel Provider Integration Reliability Requirements"
created: 2026-08-09
updated: 2026-08-09
implemented: 2026-08-09
tags: [external-channel, slack, discord, sdk, reliability]
document_role: primary
document_type: requirements
snapshot_id: external-260809
---

# External Channel Provider Integration Reliability Requirements

- Snapshot: `external-260809`
- Document reference: `external-260809/REQ`

## Problem

Azents still performs some Slack and Discord provider operations through hand-written HTTP or protocol calls even when an established provider SDK exposes the required public capability. This duplicates provider contracts inside Azents, allows SDK-supported behavior to drift, and has already caused a Discord Application endpoint registration failure.

## Primary Actor

A Workspace administrator who connects and operates a customer-owned Slack or Discord App through External Channels.

## Primary Scenario

The administrator configures a Slack or Discord connection and participants use the connected provider normally. Setup, ingress, history, commands, messages, threads, files, and lifecycle operations continue to behave as specified, while supported provider operations are owned by established SDK public APIs rather than Azents-authored provider routes or protocol implementations.

## Supporting Scenarios

- A provider SDK changes an upstream route or protocol detail without requiring Azents to maintain a duplicate provider contract.
- A provider operation fails or has an ambiguous outcome and Azents preserves its existing safe classification and recovery behavior.
- A required provider operation has no usable SDK public capability and is surfaced as an explicit, reviewable exception rather than retained silently.

## Goals

- Make established SDK public APIs the authoritative provider-call boundary for Slack and Discord.
- Preserve all current External Channel product behavior, security fences, lifecycle ownership, and delivery guarantees.
- Remove obsolete direct provider transports, duplicated route contracts, and tests that encode them.
- Make any unavoidable non-SDK provider transport narrow, evidenced, and explicitly approved.

## Non-Goals

- Changing External Channel setup UX, routing, access, conversation, Session, or Channel Work behavior.
- Changing the supported Slack or Discord App modes, callback ingress contracts, or provider-visible command/message semantics.
- Using SDK private or internal APIs to avoid a missing public capability.
- Adding compatibility fallbacks that retain both SDK and direct provider-call paths.

## Requirements

### REQ-1. SDK-owned provider operations

Every Slack and Discord external-service operation that is supported by an established public SDK API for the service's implementation language and runtime must execute through that SDK boundary.

**Acceptance criteria**

- Runtime code contains no hand-written Slack or Discord API route, WebSocket, or provider-protocol call for an operation supported by an adopted SDK public API.
- Tests verify behavior through SDK-facing collaborators or deterministic SDK-compatible provider boundaries rather than fixing Azents-authored provider route contracts.
- SDK private or internal APIs are not used.

### REQ-2. Current product behavior remains stable

The migration must preserve the current observable Slack and Discord setup, ingress, routing, history, command, message, thread, file, and lifecycle behavior.

**Acceptance criteria**

- Existing Single and Multi App setup and validation outcomes remain unchanged.
- Unrelated customer-owned Discord commands remain preserved.
- Existing Slack and Discord message, thread, interaction, history, and file journeys continue to pass their deterministic E2E coverage.
- No new user configuration or manual callback step is introduced.

### REQ-3. Delivery safety remains stable

SDK ownership must not weaken provider effect ordering, duplicate prevention, or failed-versus-unknown outcome classification.

**Acceptance criteria**

- Discord Create Message retains its live-operation duplicate fence.
- Confirmed provider rejection remains `failed`; transport, timeout, server, or malformed-success ambiguity remains `unknown` where the current contract requires it.
- Unknown writes are not automatically replayed.
- Canonical External Channel state continues to commit before provider effects and no provider I/O occurs inside an open database transaction.

### REQ-4. Bounded file transfer remains stable

Inbound downloads and outbound uploads must retain the current bounded streaming and retention guarantees after SDK migration.

**Acceptance criteria**

- File size and chunk limits are enforced before and during transfer.
- Provider file bytes are not retained in canonical External Channel state or duplicated into unrelated storage.
- Runtime and Exchange file authority checks remain unchanged.
- Migration does not require loading an entire provider file into memory solely to satisfy an SDK call.

### REQ-5. Explicit SDK-gap exceptions

A non-SDK provider transport may remain only when no adopted SDK exposes a usable public capability that can satisfy the current product contract.

**Acceptance criteria**

- Each exception identifies the exact provider operation, evaluated SDK public APIs, unmet product constraint, security and operational consequences, and removal condition.
- Each exception receives explicit requester approval before implementation.
- Exceptions are isolated from SDK-supported operations and do not create a general raw provider client or fallback mode.

### REQ-6. Deterministic verification

The completed migration must remain verifiable without live Slack or Discord credentials.

**Acceptance criteria**

- Unit and deterministic E2E tests cover setup, callback registration, commands, message/thread delivery, history, and file paths affected by the migration.
- Provider fixtures expose only bounded safe evidence and do not persist credentials, callback selectors, interaction tokens, private file URLs, or raw provider bodies.
- Live-provider tests remain optional validation rather than required CI authority.

### REQ-7. Authoritative removal

Direct provider-call implementations and duplicated contracts replaced by SDK support must be removed completely.

**Acceptance criteria**

- Obsolete HTTP clients, provider route builders, payload parsing owned by the SDK, retry logic owned by the SDK, dependency wiring, test doubles, and fixture routes are deleted.
- Static repository checks fail when a new unapproved Slack or Discord direct provider call is introduced.
- Living Specs describe the final SDK-owned boundaries and any approved exceptions.

## Fixed Constraints

- PostgreSQL External Channel records remain the canonical connection, routing, authorization, conversation, work, and delivery state.
- Existing security, credential, generation, ownership, and lifecycle fences remain authoritative.
- The migration uses SDK public APIs only and introduces no direct-call compatibility fallback.
- Each provider service uses established SDKs native to its existing implementation language and runtime; the migration does not add a cross-language SDK sidecar or IPC boundary solely to replace a provider call.
- Current provider behavior is preserved unless the requester explicitly changes these Requirements.
- The repository-wide supported external-service SDK convention applies to the implementation.

## Open Assumptions

- Slack operations use the currently adopted `slack-sdk`, and Discord operations use the currently adopted `discord.py`; this migration does not add a second Discord SDK.
- CDN or provider-issued upload/download URLs may remain narrow direct transports when the adopted SDK has no public streaming API that preserves the bounded transfer contract.

## Confirmation

Confirmed by the requester on 2026-08-09 before ADR and design decisions began.
