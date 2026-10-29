---
title: "Agent Inference Proxy"
created: 2026-10-29
tags: [engine, inference, security, infra]
spec_type: domain
domain: inference-proxy
code_paths:
  - python/apps/azents-llm-proxy/src/azents_llm_proxy/**
  - python/apps/azents-llm-proxy/Dockerfile
  - python/apps/azents-llm-proxy/pyproject.toml
  - infra/charts/azents/templates/llm-proxy/**
last_verified_at: 2026-10-29
spec_version: 1
---

# Agent Inference Proxy

This independently packaged service runs the original LiteLLM Proxy application,
configuration loader, lifespan, provider SDK dispatch and Responses streaming.
Azents supplies only Agent authority, current candidate settings and request-local
upstream credentials. The Worker still uses its existing inference path. See
[Agent Inference Authority](inference-authority.md) for token state and server APIs.

## Trust and ingress

The Agent-facing surface is exactly `POST /v1/responses` and `GET /v1/models`.
Credential-free `GET /health/liveliness` is the original process health probe;
it does not certify authority reachability, provider entitlement or live readiness.
Other methods, aliases, query strings and management/resource endpoints are denied.
No background retrieval, previous-response lookup, standalone image endpoint,
provider passthrough or target-list extension is exposed.

An invocation supplies its actual configured public model and
`metadata.azents_target_id`. The latter is the lowercase SHA256 of compact UTF-8
JSON `[stored label, integration ID, stored model identifier]`, with no additional
normalization. The selector grants no authority. Listing is optional and does not
supply credentials or authorize a later invocation.

The custom-auth callback requires exactly one ordinary Authorization bearer and
rejects alternate key/account/routing header aliases. The private authority client
sends only Agent identity and selectors, not inference content, over verified HTTPS
with the dedicated resolver key. Authority denial never falls back to normal
LiteLLM key authentication, a global provider account, cached Agent authorization
or a different target. An empty allowed listing stays empty.

The regular Proxy runs on its direct-dispatch path without a Router deployment
registry or Prisma credential database. Its boot master key is an undisclosed
fresh process-local nonce, not a caller credential or an authorization fallback.
Each new call resolves current authority online; already-admitted calls retain
their fixed selected binding.

## Request and configuration boundary

The outer ASGI ingress bounds content to 32 MiB and coalesces fragmented request
frames into one bounded buffer. Disconnect and pre-auth oversize cases release
resources without keeping one object per frame.

The decoder uses the pinned OpenAI Responses protocol schema with closed named
protocol objects. Caller function parameter schemas and argument JSON remain
opaque user data. All SDK protocol Iterable fields are eagerly validated and
materialized at ingress, including nested reasoning summaries, annotations and
multimodal tool outputs, so repeated authorization/serialization cannot exhaust
them or fail while cloning a lazy validator.

Inline bounded text/images/PDF history is admitted; remote URLs, file/resource
handles, stored conversations, background/store operations, arbitrary headers,
endpoints, keys, callbacks, routers, fallbacks, clients and testing controls are
not request configuration. The reserved target metadata is consumed, and caller
identity metadata is not trusted for accounting.

Current Agent candidate settings remain the only preference/capability authority:

- Saved non-null sampling defaults apply on omission; explicit values are checked
  against current feature support and conditional constraints.
- The saved candidate output cap bounds caller output; a smaller caller cap wins,
  and a known hard maximum clamps it. Unknown limits do not invent a new cap.
- Reasoning omission, explicit clear and supported effort/summary are distinct;
  known defaults constrain compatibility without becoming a new preference.
- Function tools stay client-executed. Native hosted tools preserve selected
  configuration/restrictions; the Proxy does not execute arbitrary client tools.
- Prompt-cache controls, structured declarations and Fast/Priority representations
  use bounded supported provider corrections, not a second canonical backend.
- Explicit native reasoning/encrypted continuation and client tool call/output
  identifiers remain on the actual provider wire where applicable. The generic
  image-history bridge projects completed generated image bytes with provider-tool
  provenance into inline user media, following the existing Worker semantics.

Unsupported or unavailable fidelity fails explicitly instead of silently dropping
an enabled required control or selecting another account. Provider transformation,
protocol serialization, reasoning dialect and streaming otherwise remain LiteLLM's.

## Credentials and physical dispatch

The private typed binding contains only credentials needed for the approved call.
Subscription refresh/management tokens and issuer credentials never enter Proxy.
Auth/request data are private attributes, excluded from normal serialization and
released during outer request cleanup. No Python secure-erasure claim is made.

- API-key routes receive their exact request key and fixed trusted provider origin.
- ChatGPT receives its request access token and matching account header; its token
  shape is checked only to select the supported request-credential path, not as a
  substitute for server authority or provider signature validation. No local login
  or account-file fallback is permitted.
- xAI/Grok subscription receives its exact access token. Current model capability
  facts, not the old `grok-4` model, determine native streaming support.
- Kimi uses the official OpenAI SDK's HTTPX2 client with exact access/device headers,
  `max_retries=0` and request-owned client cleanup.
- Bedrock role configurations receive the server-prepared STS access/secret/session
  tuple and expiry. Role selection is not forwarded to LiteLLM. Expired material is
  rejected before dispatch. Direct static-key configurations retain explicit-key
  signing rather than an unnecessary STS requirement.
- Vertex receives a closed Google service-account call document and explicit
  project/location. Exact-credential/project SDK token caching is not Agent
  admission; warm cached credentials cannot override a new authority denial.

The final deployment callback rechecks model/account/control invariants. The actual
HTTP transport checks POST, HTTPS origin/port and admitted provider path after SDK
transformation. Redirects, cookies and environment proxy inheritance are disabled.
The HTTPX wrapper reclassifies the specific errors that trigger the SDK handler's
hard-coded resend; it does not reconstruct provider HTTP or replay a request.
Both that path and Kimi's distinct HTTPX2 branch have physical request-count and
failure/cancellation coverage. Candidate choice, retry and fallback belong to callers.

## Lifetime, errors and observability

Disconnect, timeout and stream failure close owned transports/clients. Expiry,
revocation or settings changes block new admissions without a distributed active-call
cancel mechanism. A process/Pod failure does not transfer or resume an existing stream.
The CLI uses Uvicorn's bounded 120-second graceful shutdown; the default chart gives
the Pod 150 seconds. This is ordinary draining, not durable execution or billing undo.

Public failures use LiteLLM's standard error envelope with fixed safe messages and
authority-versus-provider classification. Native failures after stream start retain
standard `response.failed` semantics and attempted model identity, not false completion
or substitution. Caller/provider raw errors, exception values, bodies and headers
are not operational diagnostics.

Vendor diagnostics retain only origin, severity and exception class. The original
Proxy's typed response/deployment callbacks and outer ASGI lifetime project one
allowlisted JSON operation event with
fresh request correlation, server-verified Agent/Workspace/integration/model,
outcome, latency, failure classification and available input/output/total counts.
Nested provider-bridge calls do not emit duplicate logical operations. Actual
terminal status and downstream delivery distinguish success, failure, incomplete,
disconnected and cancelled calls; SDK partial-spend success is not stream completion.
Failures before physical dispatch are preparation failures, not upstream failures.
Responses and Chat usage field names map to the same input/output/total projection;
missing usage stays unknown. Callback cleanup retains no credential/body projection.

Responses preserve available SDK usage subsets (cache, reasoning, modality and tier)
without counting subset tokens twice. SDK-calculated `cost`, when present, is an
estimate, not a provider invoice; subscription counts/cost estimates do not establish
subscription billing or entitlement. There is no duplicate Worker usage ledger,
custom distributed budget/rate system, restoration protocol or external exporter.
No built-in limit is represented as a cluster-wide guarantee without shared coordination.

## Packaging and deployment

The exact published PyPI wheel is `litellm==1.109.0.dev1`, locked with registry
artifact hashes. This is the requester's one-time exception for upstream ChatGPT
forwarding PR41522. The dependency comment records replacing it with a stable that
contains the fix after equivalent auth/isolation/stream tests. It is not permission
to use arbitrary future prereleases, Git source builds or a maintained vendor patch.

The MIT-covered core is installed without the Enterprise-pulling `proxy` extra.
The runtime audit checks exact release identity, original MIT notice, absent
Enterprise files/imports and disabled premium configuration without changing license
gates. The image preserves original distribution notices and installed dependency
inventory. Third-party components keep their own licenses. The nonroot runtime image
contains no upstream Git checkout or Rust compiler/toolchain.

`llmProxy.enabled` is false by default. When enabled the chart creates an independent
Deployment/Service and optional exact-route TLS ingress. Replicas default to one,
but more than one render without sticky authorization or a local authority store.
Configuration includes image identity, port, verified private authority URL/timeout,
a resolver-only existing Secret and optional CA Secret. No whole-server `envFrom`,
issuer secret or provider environment is mounted. Ingress disables buffering and
next-upstream replay and bounds body size. Private network routing remains an operator
deployment obligation, not a fact proved by Helm rendering.

The environment accepts only the dedicated `AZ_LLM_PROXY_*` deployment inputs and
rejects ambient provider, general Proxy, database and exporter credentials/settings.
The optional private CA augments trust rather than disabling TLS verification.

## Verification boundary

Focused tests exercise actual Proxy configuration/ASGI/SDK transformations with
controlled physical provider transports. The representative required E2E joins real
Admin issuance, public settings APIs, private authority HTTP with verified TLS and
the built Proxy process for two Workspaces/accounts. Its disposable fixture changes
only the final provider network and is never enabled by the product entrypoint.
No E2E writes product database state directly.

Deterministic fixtures, package/image/Helm checks and real-provider entitlement are
separate evidence. No real account login, paid inference, production deployment,
Worker/Runtime migration or live hosted-tool entitlement follows from these tests.
