---
title: "Reliable MCP Tool Connections Decisions"
created: 2026-10-27
document_role: primary
document_type: adr
snapshot_id: mcp-261027
tags: [mcp, engine, architecture]
---

# Reliable MCP Tool Connections Decisions

Authority: [mcp-261027/REQ](../requirements/mcp-261027-reliable-tool-connections.md).
The requester accepted the preceding research recommendation and requested design
and implementation on 2026-10-27 KST. The following decisions instantiate that
accepted scope; they do not delegate unrelated product choices.

## ADR-D1. Binding-owned reusable SDK sessions

Accepted: retain SDK sessions within each active Toolkit binding, separated by
endpoint, transport, proxy, and credential identity. A dedicated task owns SDK
context entry and exit. One shared preparation performs initialization and public
SDK tool listing before executing tools. Calls remain independently cancellable
and bounded in parallelism. Existing SessionToolkitLifecycle owns final cleanup.

Rejected: HTTP-client-only reuse (does not remove MCP/schema cold starts), URL-only
Worker-global pooling (crosses authority/lifetime boundaries), and replacing the
Azents catalog with ClientSessionGroup aggregation (changes snapshot exposure).

Applies to REQ-1, REQ-2, REQ-3, REQ-5. Risks: retained sessions require explicit
failure detection and task-owned cleanup; provider idle expiry still occurs.

## ADR-D2. Current per-call authority and replay-safe recovery

Accepted: resolve and recheck authorization for every external execution, including
after connection/capacity waits. Request-local auth state is propagated with each
SDK message rather than mutating a shared HTTP client's defaults. Credential
changes select a new connection; old in-flight requests retain their admitted
identity while retiring sessions drain. Failures invalidate reuse for subsequent
requests; connection recovery does not blindly replay tools/call. Existing
explicit provider authentication refresh remains a distinct boundary.

Rejected: trusting initial authorization for a connection's entire lifetime,
sharing mutable 401 observers, and reconnect-and-replay for all failures.

Applies to REQ-2, REQ-3, REQ-4. SDK/schema validation failures can occur after the
provider has executed a tool; such failures must not trigger execution replay.

## ADR-D3. Single-flight cached discovery

Accepted: preserve existing durable metadata snapshots and non-blocking exposure.
Retained SDK sessions preload complete listings using public pagination APIs.
Refresh is coalesced and lazily bounded by freshness, or marked stale by supported
tool-list-change notifications. No polling service or durable live connection is
introduced. Setup/connection-test operations remain short-lived and close normally.

Rejected: refreshing at every context update, disabling SDK output validation,
and injecting metadata into private SDK caches.

Applies to REQ-1, REQ-5. Freshness is bounded rather than instantaneous for servers
that do not emit list-change notifications; errors preserve previous metadata.
