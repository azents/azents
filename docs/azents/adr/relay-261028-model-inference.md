---
title: "Agent-Scoped Model Inference Backend Decisions"
created: 2026-10-28
updated: 2026-10-28
tags: [engine, inference, security, architecture]
document_role: primary
document_type: adr
snapshot_id: relay-261028
---

# Agent-Scoped Model Inference Backend Decisions

- Snapshot: `relay-261028`
- Document reference: `relay-261028/ADR`
- Requirements: [relay-261028/REQ](../requirements/relay-261028-model-inference.md)
- Mode: Collaborative; decision owner: requester.

This record consolidates choices explicitly accepted during the design discussion.
The complete Requirements snapshot was confirmed before this formal ADR was
created. It does not claim that an earlier repository ADR or Design existed, and
does not grant implementation or deployment approval. The numbered decisions
below are accepted choices, not new defaults inferred from technical feasibility.

## Decision Map

| Decision | Owner | State |
| --- | --- | --- |
| D1 Proxy backend and phase boundary | Requester | Accepted |
| D2 Existing configuration authority | Requester | Accepted |
| D3 Exact target identity and metadata | Requester | Accepted |
| D4 System-managed opaque credentials | Requester | Accepted |
| D5 Token timing and supply-target rotation | Requester | Accepted |
| D6 Online credential authority | Requester | Accepted |
| D7 Issuer/resolver trust separation | Requester | Accepted |
| D8 Agent-facing endpoint scope | Requester | Accepted |
| D9 Caller-owned retries and connection lifecycle | Requester | Accepted |
| D10 Usage and operational privacy | Requester | Accepted |
| D11 Built-in operational limits only | Requester | Accepted |
| D12 Deployment and licensing boundary | Requester | Accepted |
| D13 Independent readiness verification | Requester | Accepted |

Local names, module layout, serialization helpers, and fixture composition are
agent-owned details. New product behavior, a durable secondary authority, a
license-gate bypass, or an upstream fork policy is not authorized by this map.

## D1. Use the actual LiteLLM Proxy as the inference backend

**Authority:** relay-261028/REQ-1, relay-261028/REQ-6, Fixed Constraints.

Use LiteLLM Proxy and its unified Responses contract as the canonical inference
surface. Add Azents authentication and credential-supply extensions inside that
Proxy. First build and verify the independent backend; replace Worker call sites
and move the harness into Runtime in subsequent work.

**Alternatives:** Retain PydanticAI and build an inference server; replace only the
library with LiteLLM; preserve a custom Azents canonical HTTP adapter in front.
The requester chose Proxy reuse, not a library replacement or a new canonical server.

**Consequences:** Existing Worker adapters remain untouched in this snapshot.
Upstream semantics and extension compatibility require pinned-version evidence.

## D2. Derive authorization from existing Agent settings

**Authority:** relay-261028/REQ-2, relay-261028/REQ-3.

Existing Agent selectable model options and Workspace integrations are the sole
configuration authority. Agents within one Workspace may select different accounts
for the same public model. Authenticate the Agent before resolving its targets.
Read current configuration on new admission; retain the selected target within an
admitted call.

**Rejected:** Separate Proxy model-mapping storage or configuration API; a globally
shared account selected by model name alone; a Workspace-only mapping that erases
Agent distinctions; an automatic configuration-sync authority.

**Consequences:** Removing a target affects subsequent calls. An already-running
call is not retargeted by a concurrent configuration change.

## D3. Identify the caller-selected target explicitly

**Authority:** relay-261028/REQ-2, relay-261028/REQ-7; D2.

Keep the public model name in `model`. Carry `azents_target_id` in request metadata.
Derive the identifier deterministically from label, integration ID, and actual
model identifier. It is a selection identifier, not a credential. Match it only
against the authenticated Agent's current configuration and validate model agreement.

Use a canonical serialization and cryptographic hash, not list position or a
persisted target registry. Label distinguishes settings for the same physical
selection. Reordering and credential refresh preserve the ID; changing label,
integration, or model changes it. Settings-only edits apply at new admission.

**Rejected:** `candidate` as the wire name for an already selected destination;
implicit first-candidate selection; candidate-specific public model names; a
settings-version protocol; extending model discovery with a target list.

**Consequences:** Callers derive the target from existing settings. Strip the routing
metadata before provider dispatch. The Proxy never executes a label's fallback chain.

## D4. Issue system-owned opaque Agent tokens

**Authority:** relay-261028/REQ-3, relay-261028/REQ-4.

Issue high-entropy opaque bearer tokens; store verification hashes rather than
recoverable original tokens. Tokens identify an Agent but do not contain provider
secrets or a frozen permission list. Current permission resolution remains server-side.

Production issuance/delivery is server-to-server or server-to-Runtime. This phase
provides privileged system Admin/Internal verification access, not a Workspace
Owner/AgentAdmin API-key product.

**Rejected:** JWT as a default, user-managed tokens, inference-token self-renewal,
returning upstream credentials to the harness, and exposing stored original tokens.

**Consequences:** Authority availability is required for new admissions. Leaked
bearer tokens remain usable within their actual scope until expiry or revocation.

## D5. Rotate per supply target with bounded overlap

**Authority:** relay-261028/REQ-4; D4.

Use one-hour lifetimes, begin replacement five minutes before expiry, and allow at
most five minutes of old/new overlap without extending original expiry. Separate
token lifecycle by supply target while retaining common current Agent permissions.
Development revocation does not revoke operational credentials for that Agent.

Security revocation has no handover grace. Expiry/revocation affects new admissions,
not running calls. Failed delivery does not extend validity. Automatic Worker and
Runtime supply integration remains subsequent work.

**Rejected:** Indefinite fixed keys, revocation-driven stream cancellation, and one
shared token lifecycle for all consumers of an Agent.

**Risks:** Concurrent rotation and a lost issuance response require explicit conflict
handling; they must not create an unbounded collection of valid old tokens.

## D6. Resolve provider credentials online through Azents

**Authority:** relay-261028/REQ-2, relay-261028/REQ-5.

At admission the Proxy calls an internal Azents authority to validate Agent scope,
resolve the exact target, and obtain necessary provider call credentials. Azents
owns encrypted integration storage and OAuth refresh. Listing models does not
retrieve provider credentials or refresh OAuth. Inference content does not travel
through this authority API.

**Rejected:** A separately managed Proxy copy of provider secrets and refresh tokens,
global mutable account credentials, and cached authorization fallback when authority
resolution is unavailable.

**Consequences:** A bounded internal round trip precedes inference. Reuse existing
OAuth persistence fences; do not claim those fences guarantee single provider refresh.

## D7. Separate Proxy resolver identity from token issuer privileges

**Authority:** relay-261028/REQ-3, relay-261028/REQ-4, relay-261028/REQ-5; D4, D6.

Protect internal calls with a dedicated Proxy service credential, TLS, and private
network access. Resolve calls require both service and Agent authentication. The
Proxy service credential cannot issue, rotate, or revoke Agent tokens, and cannot
read an arbitrary integration by ID without an authorized target. Retain OAuth
refresh tokens in Azents.

**Rejected:** Cluster-location-only trust, unrestricted service-secret lookup, and
using a Proxy service token as an Agent-token issuer credential.

**Risks:** A compromised Proxy can observe credentials for calls it legitimately
handles; least privilege does not eliminate this process compromise boundary.

## D8. Expose a narrow Agent API

**Authority:** relay-261028/REQ-3, Fixed Constraints; D1, D3.

Expose Responses invocation and standard permission-filtered model discovery.
Do not initially expose Chat Completions, standalone image generation, management,
generic passthrough, or durable background/retrieval jobs to Agent credentials.
Use the existing listing format and filtering facilities without target-list
extensions, a separate discovery API, or a mandatory list-before-invoke round trip.

**Rejected:** Broad gateway API access and a custom model-list response adapter.

## D9. Leave retry and fallback with the caller

**Authority:** relay-261028/REQ-7.

Disable general Proxy retry and candidate fallback using existing settings. Do not
replay uncertain calls. Treat SDK/transport recovery separately and test physical
request counts. Execution is connection-bound; normal disconnect/timeouts clean
up resources. No distributed active-call revocation service or reconnect job store.

**Consequences:** Callers receive failure and decide what to do next. Cancellation
cannot guarantee provider billing rollback. Pod loss can interrupt a stream.

## D10. Preserve usage without a second ledger or body logs

**Authority:** relay-261028/REQ-8.

Return observed provider usage and use built-in Proxy observability. Attribute
records to authenticated identities and the actual integration. Do not add an
Azents Proxy usage ledger or retransmission queue; Worker persistence integration
is later. Keep token subset semantics and distinguish observed values from estimates.

Operational logs contain safe metadata, timing, outcome, usage, and sanitized
failure classification, not prompts, responses, tool content, media, credentials,
or unsafe provider errors. Use synthetic data for detailed diagnostics.

**Rejected:** Operational body-logging features and treating subscription token math
as actual API billing.

## D11. Use only suitable built-in operational limits

**Authority:** relay-261028/REQ-9.

Reuse MIT-covered LiteLLM limits where they fit the custom-auth integration. Do not
build custom rate counters, distributed reservations, budget logic, or associated
UI. Document unsupported aggregation semantics rather than silently promising them.

**Consequences:** Per-process limits are not global limits. Multiple replicas may
require built-in shared coordination for global enforcement; no new dependency on
Redis for credential authorization is created.

## D12. Independent, Enterprise-free deployment without a replica cap

**Authority:** relay-261028/REQ-1, relay-261028/REQ-9, relay-261028/REQ-10, Fixed Constraints.

Start in a separate Pod with replicas set to one as configuration. Do not reject
larger replica counts or depend on sticky sessions for authorization. Package the
MIT-covered Proxy and Azents extensions without Enterprise source/package use or
license-gate bypass. Standard upstream images/extras require composition review
because the inspected revision includes Enterprise components.

**Rejected:** A single-replica correctness constraint and assuming default image
contents are all MIT merely because the root license has an MIT section.

**Consequences:** Production image reproducibility, notices, private TLS networking,
and operations endpoints require implementation evidence before rollout.

## D13. Verify the assembled boundary before Worker migration

**Authority:** relay-261028/REQ-1, relay-261028/REQ-6, relay-261028/REQ-10.

Use system Admin/Internal development access and existing Agent configuration to
exercise the real Proxy flow. Verify representative authorization/lifecycle journeys
end-to-end; use lower-level tests for provider permutations. Separate upstream mock
results from real account entitlement and preserve known functional gaps.

**Rejected:** Claiming subscription/hosted-tool readiness solely from mocked tests,
expanding this stage into Worker migration, and invoking real accounts without authorization.
