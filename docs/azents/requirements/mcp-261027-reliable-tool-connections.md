---
title: "Reliable MCP Tool Connections Requirements"
created: 2026-10-27
implemented: 2026-10-27
document_role: primary
document_type: requirements
snapshot_id: mcp-261027
tags: [mcp, engine, reliability]
---

# Reliable MCP Tool Connections Requirements

- Snapshot: `mcp-261027`
- Document reference: `mcp-261027/REQ`

## Problem

Repeated MCP tool execution recreates transport and protocol state. Initialization,
discovery, and result-schema loading amplify provider traffic even when tools and
credentials have not changed. Persistent connections must not extend authorization
or create duplicate external effects during recovery.

## Primary System Outcome

Repeated and parallel MCP operations for the same active execution binding avoid
redundant connection preparation while retaining isolation, current authorization,
non-blocking tool availability, and deterministic resource cleanup.

## Supporting Effects

- Reduce avoidable initialization/discovery throttling.
- Preserve parallel execution and meaningful cancellation.

## Goals and Non-Goals

Deliver reliable reuse across the existing generic MCP, GitHub, AWS, and GCP
paths. Do not add a global connection service, persisted live sessions, new public
APIs, configuration modes, a dependency upgrade, or production infrastructure
changes. Actual throughput gains are measured separately, not guaranteed here.

## Requirements

### REQ-1. Avoid redundant preparation

For unchanged active bindings, sequential and concurrent calls share preparation.
A cold concurrent batch performs one initialization and initial complete tool
listing per target, rather than one preparation per call. Later context updates
must not cause immediate redundant discovery after a recent successful listing.

### REQ-2. Preserve authorization and isolation

Different Sessions, Toolkits, endpoints, installation targets, and credentials do
not share authority. Each execution rechecks current admission and credentials;
revoked or replaced credentials cannot authorize a new operation through a retained
connection. Per-request authentication failure reporting remains exact.

### REQ-3. Preserve parallelism and cancellation

A cancelled or failed caller does not cancel unrelated callers. Concurrent calls
retain correct response routing. Initial preparation is single-flight and bounded;
a request cannot wait forever for unavailable capacity or a failed connection.

### REQ-4. Recover without duplicate effects

Discard failed connections so subsequent operations can prepare a new connection.
Do not replay an external tool execution whose dispatch/result is uncertain.
Read-only preparation retries remain bounded and honor supported retry delays.

### REQ-5. Preserve availability and cleanup

Previously successful tool metadata remains immediately available while refresh
runs in the background. Failed refresh preserves that metadata. Toolkit removal,
replacement, and runner shutdown terminate owned connections with bounded cleanup.
No live transport or credential is persisted in metadata snapshots.

## Fixed Constraints

Use the supported MCP SDK APIs and existing Session Toolkit lifecycle. Preserve
HTTP/SSE negotiation, per-provider auth contracts, existing tool schemas, ownership
fencing, and result validation. Keep product E2E coverage minimal; exercise transport
combinations deterministically below the product UI layer.

## Open Assumptions

Actual providers may impose their own idle lifetime and connection limits; failure
must remain observable without automatic replay of ambiguous writes.

## Confirmation

The requester explicitly requested design and implementation of the previously
presented connection-reuse recommendation on 2026-10-27 KST. REQ-1 through REQ-5
record those accepted outcomes and constraints, without adding new product scope.
