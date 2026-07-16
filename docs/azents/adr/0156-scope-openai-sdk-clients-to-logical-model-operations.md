---
title: "ADR-0156: Scope OpenAI SDK Clients to Logical Model Operations"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, lifecycle]
---

# ADR-0156: Scope OpenAI SDK Clients to Logical Model Operations

## Status

Accepted. Implementation has not started.

## Context

The official `AsyncOpenAI` client owns an HTTP connection pool, base URL, authentication configuration, SDK retry behavior, and transport resources that require explicit closure. Creating a new client for every physical Responses request would discard connection reuse across the multi-turn sampling loop. Sharing clients process-wide would instead require long-lived cache keys and invalidation rules for integration credentials, ChatGPT OAuth access tokens, custom base URLs, and event-loop ownership.

Azents already has logical operation boundaries with stable resolved credentials. Primary sampling runs inside one `AgentRunExecution`; continuation state is also scoped to that execution. Compaction and automatic Session title generation are separate bounded model operations.

## Decision

OpenAI SDK client lifetime follows the logical model operation that owns the calls.

- Primary sampling creates one client for an `AgentRunExecution`, reuses it across all model turns in that execution, and closes it when the execution ends.
- A compaction invocation creates one client for that invocation and closes it when the invocation ends.
- An automatic Session title invocation creates one client for that invocation and closes it when the invocation ends.

Clients are not shared across Agent Runs, compaction invocations, title invocations, resolved credential snapshots, or event loops. Azents does not maintain a process-wide OpenAI client cache.

The client is constructed from transport configuration and the operation's resolved credentials outside the logical `OpenAIResponsesRequest`. The model adapter receives the client as an injected collaborator. Tests may inject a client or client factory without replacing the logical request type.

The operation owner closes an active stream before closing the client. Final operation cleanup closes the client in all success, failure, timeout, and cancellation paths. A process-owned watchdog cleanup task may still settle a non-cooperative stream; closing the operation-owned client is part of terminating that transport rather than extending the client's lifetime beyond the operation.

The client uses the official SDK retry default established by ADR-0155. Continuation state remains separate adapter state but has the same `AgentRunExecution` lifetime as the sampling client.

## Consequences

- Multi-turn sampling reuses HTTP connections without sharing mutable credential state between Runs.
- OpenAI continuation state and its underlying client have aligned lifetimes.
- Compaction and title generation cannot retain stale clients or credentials after their bounded operation completes.
- Explicit async client closure becomes part of every model-operation finalization path.
- The generic model adapter lifecycle must expose or otherwise guarantee async cleanup in the execution owner.
- A new Agent Run after retry or worker recovery creates a new client and reconstructs state from durable history.
- There is no global client-cache eviction, credential rotation, or cross-event-loop synchronization policy.

## Alternatives Considered

### Create a client for every physical Responses request

Rejected because it discards connection pooling between turns of the same logical operation and separates client lifetime from continuation state.

### Share clients through a process-wide pool

Rejected because credential and base-URL isolation, OAuth token rotation, cache invalidation, shutdown, and event-loop ownership would become global infrastructure concerns without a demonstrated need.
