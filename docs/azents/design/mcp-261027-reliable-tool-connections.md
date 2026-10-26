---
title: "Reliable MCP Tool Connections Design"
created: 2026-10-27
implemented: 2026-10-27
document_role: primary
document_type: design
snapshot_id: mcp-261027
tags: [mcp, engine, reliability]
---

# Reliable MCP Tool Connections Design

References: [Requirements](../requirements/mcp-261027-reliable-tool-connections.md),
[ADR](../adr/mcp-261027-reliable-tool-connections.md).

## Current Behavior and Gaps

core/mcp_transport creates an HTTP client, transport, and ClientSession for each
operation. SDK output-schema validation can request another listing after a tool
has executed. Background metadata refresh coalesces only currently running tasks.
SessionToolkitLifecycle already reuses and disposes Toolkit instances by binding
identity and source revision, but currently owns no retained MCP transport.

## Architecture and Ownership

A Toolkit-owned connection manager retains one current connection per target.
Connection identity includes URL, selected transport, proxy, immutable header
values and a provider-supplied auth identity. Identity values remain memory-only,
redacted from representations and logs. Credential replacement retires the prior
connection rather than mutating it. A dedicated asyncio task enters and exits
SDK contexts, publishes readiness after initialize and full paginated list_tools,
and owns child operation tasks and bounded shutdown. Consumers await readiness
and execute SDK calls with single-flight preparation and bounded parallelism.

Generic MCP, Notion, Sentry and concrete GitHub MCP bindings share this manager.
Lazy GitHub snapshot handlers first prepare their exact installation binding and
then use its manager. AWS and GCP own managers with their existing Toolkit objects;
AWS selects by immutable SigV4 credential identity, GCP by bearer/project headers.
Setup probes retain their explicit short-lived lifecycle.

## Authorization and Interfaces

Each wrapper resolves current headers/auth and retains existing effect admission.
A request-local auth context travels through the SDK transport's contextual streams
into HTTP auth; shared defaults are never rewritten for different callers.
Current admission is rechecked at actual external dispatch after readiness/capacity
waits. Per-call observers stay request-local. A retained connection grants no
permission. Same-principal credential rotation starts a fresh connection; old
operations are drained without authorizing new calls under the retired key.
The public HTTP-client send boundary contains local admission rejection: it
performs no provider I/O, returns a typed correlated non-success MCP response to
the SDK, and hands the original exception back only to that operation. Legacy SSE
requires a local 202 acknowledgment to preserve its POST writer, so its exact
operation task is cancelled and rethrows the recorded local denial instead of
waiting for a nonexistent provider response. This never reports success to a
tool caller. Raising the denial inside the SDK's shared transport task group
would abort siblings.

## Discovery and Availability

Initial preparation lists all pages before tools/call, warming SDK schemas and
publishing the same complete metadata shape used today. Metadata publication stays
background and authority-fenced. Recent completed discovery is reused for 300
seconds (lazy freshness, no periodic actor). A list-change notification marks it
stale. Refresh and initial preload share one listing lock; parallel calls cannot
race cold schema loading. A failed listing retains the last successful catalog.
The 300-second internal policy is the bounded freshness candidate included in the
accepted recommendation, not a new user-facing configuration surface.

## Failure, Concurrency, and Cleanup

Initialization/discovery retry remains read-only and bounded by current retry
limits. Tool operations are never automatically replayed on arbitrary MCP/network
errors. Failed connections are retired for later calls; error information reaches
the existing tool error boundary. Each connection permits at most 16 active
operations. Capacity/readiness waits are bounded by the caller's configured
timeout. Call cancellation cancels only its request; it does not terminate the
connection. Transport-wide failure invalidates that connection and fails its
pending operations. Toolkit exit stops new admission, cancels/drains operations,
and asks the owning task to close SDK contexts, including DELETE. Cleanup has a
10-second upper bound before owner-task cancellation. Unexpected shutdown errors
remain visible; cancellation is propagated separately.

## Persistence, Rollout, and Observability

No schema migration, API/client regeneration, feature flag, or new deployment
configuration is required. Only serializable metadata is persisted. Release uses
the normal application deployment; rollback restores the previous application
image. No live-session recovery across Worker restart is attempted. Structured
connection lifecycle/operation counts exclude URLs with secrets, headers, tokens,
session IDs and provider payloads. Initialization/list counts and reuse tests are
the acceptance evidence; throughput improvement is not presumed.

## Test Strategy

The product-visible tool availability contract stays unchanged; preserve existing
minimal MCP/Toolkit product E2E journeys instead of adding a combinatorial UI
suite. The primary new acceptance boundary is a deterministic integration test
using the real pinned ClientSession and Streamable HTTP transport with mock HTTP
responses: sequential/parallel calls, complete-list preload, credential rotation,
per-call authentication, cancellation, failure recovery without replay, and DELETE.
Exercise Toolkit ownership, lazy GitHub bindings, AWS/GCP signing/token paths and
snapshot freshness with lower-level tests. Legacy SSE context lifetime uses the
same owner and receives a focused transport fixture test. No external credentials
or new testenv seed/fixture are needed. Live provider tests are optional and cannot
substitute for deterministic acceptance. Run Ruff, whole-backend ty, focused and
relevant broader pytest, documentation catalog, existing CI/E2E gates; report any
unavailable external prerequisites or unrelated failures without claiming success.

## Feasibility and Risks

Feasible: the pinned SDK supports retained ClientSession, public paginated listings,
per-message contextual transport streams and parallel request IDs. Offline probes
confirmed reuse and cold-list coalescing benefit. Conditional edge: late-response
and shutdown races require bounded draining and specific regression tests; do not
suppress unexpected grouped exceptions. Exact provider idle behavior and real
latency require later live measurement. Authentication changes are covered by
per-call admission and credential-key replacement, not a global URL cache.

## Design Authority

- Design revision: `1`

| ID | Material mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Toolkit-owned per-target retained SDK sessions and dedicated owner task | ADR-D1; REQ-1,3,5 | decided |
| M2 | Credential isolation and dispatch-time per-call authorization | ADR-D2; REQ-2 | decided |
| M3 | Preload/coalesced lazy fresh listings and unchanged snapshot exposure | ADR-D3; REQ-1,5 | decided |
| M4 | Bounded independent calls, retirement and replay-safe recovery | ADR-D1,D2; REQ-3,4,5 | derived |
| M5 | Existing HTTP/SSE, provider identity and snapshot persistence contracts | current toolkit Spec; REQ-2,5 | existing |

Local helper names, dataclasses, file arrangement and deterministic fixture layout
are agent-owned details, not new authority.

## Removal and Replacement

| Existing behavior | Removal authority | Replacement | Boundary | Absence evidence |
| --- | --- | --- | --- | --- |
| Runtime tool wrapper's per-call session initialization | ADR-D1 | binding manager execution | all runtime MCP provider wrappers | call-site search plus repeated-call tests |
| Every-context successful discovery refresh | ADR-D3 | coalesced lazy freshness | generic MCP, AWS/GCP wrappers | freshness tests |
| Runtime tool retry across ambiguous execution failures | ADR-D2 | invalidate connection for later calls | retained call operation | failed-write counter test |

No persisted fields, public schemas, old data or externally visible transport modes
are removed. Setup probes keep bounded short-lived connections.

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: `2026-10-27`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5`
- Approved scope: the preceding research recommendation explicitly accepted by the
  request to design and implement it; binding-owned reuse, coalesced preparation,
  current per-call authority, bounded independent execution and safe cleanup.
  No new product scope or infrastructure action is authorized.
