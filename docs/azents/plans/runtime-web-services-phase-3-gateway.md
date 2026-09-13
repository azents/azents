---
title: "Temporary Runtime Web Services Phase 3 — Gateway and Deployment"
created: 2026-09-12
tags: [runtime, web, implementation, planning, backend, security, helm]
---

# Phase Execution Plan

- Phase: `3/5 — Gateway and deployment`
- Branch/base: `feat/runtime-web-gateway-3-gateway` → `feat/runtime-web-gateway-2-transport`
- PR boundary: Feature-disabled-by-default public Runtime Web Gateway, browser identity establishment, semantic HTTP/CORS/security enforcement, shared admission quotas, and deployable Helm topology.
- Inputs: Approved `web-260912` Requirements, ADR D1–D3 and D7–D10, Design revision 2, and committed Phase 1–2 authority and trusted owner-routed transport interfaces.
- Deliverables: Separate `aiohttp.web` Gateway entrypoint; validated installation settings and monotonic auth configuration; shared-cookie and separate-domain broker identity state machines; admitted Chromium/Fetch Metadata enforcement; Host, Origin, CORS, Service Worker, cookie, redirect and response-security policy; trusted Control stream adapter; PostgreSQL admission quotas; Helm Deployment, Service, Ingress, TLS, trusted-Control connectivity, resources, HPA/PDB and disabled-by-default values.
- Non-goals: Main Web login cookie rename and confirmation pages, Chat request card, Services panel, broad browser compatibility beyond the approved Chromium profile, Runtime process management, spec promotion and product E2E.
- Interfaces: Gateway resolves immutable endpoint host keys, consumes current Runtime Web projections and identity/config authority, opens only the Phase 2 trusted transport stream, emits bounded ADR-D3 HTTP errors, and exposes broker routes only on the exact configured broker host.
- Approved Design mechanisms: `M3, M6, M7, M8, M9, M11, M12, M13, M14`.
- Authority references: `web-260912/REQ-5`, `REQ-7`–`REQ-11`, `REQ-13`; ADR-D1, ADR-D2, ADR-D3, ADR-D6, ADR-D7, ADR-D8, ADR-D9, ADR-D10; approved Design revision 2.
- Design delta: `None`.
- Removal obligations: Reject Service Worker script/update traffic before proxying; replace upstream cache/CORS/security authority at the Gateway; strip platform credentials and reserved cookies; provide no unsafe host-derived origin fallback, query/fragment ticket, `__Secure-` identity fallback, automatic redirect following, response-size total cap, or legacy authentication/protocol fallback.
- Absence verification: Focused policy tests and searches prove no platform credential reaches Runtime, no broker secret enters URL components, no upstream Access-Control/Set-Cookie/cache field broadens policy, no Service Worker request reaches transport, no public listener is enabled without valid configuration, and application bytes remain only in bounded process-memory streams.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Gateway configuration and composition | root | `python/apps/azents/src/azents/core/**`, Gateway entrypoint/composition files, scripts | Phase 1 auth configuration and Phase 2 transport | Validated disabled-by-default settings, independent process lifecycle and readiness | config/composition unit tests, Ruff, type check |
| Browser identity and broker authority | root | `python/apps/azents/src/azents/repos/runtime_web/**`, `services/runtime_web/**`, Gateway auth handlers | Phase 1 identity/binding/ticket tables | Opaque hashed identity, epoch/session validation, atomic binding/ticket settlement and revocation | repository/service concurrency and replay tests |
| HTTP/CORS/security Gateway | root | new `python/apps/azents/src/azents/runtime_web_gateway/**` | Identity, current projection and Phase 2 stream | Host/origin/browser-profile policy, local preflight, bounded errors, HTTP/SSE/WebSocket streaming and header normalization | policy/parser/stream tests including negative attacks |
| Admission and deadlines | root | `repos/runtime_web/transport_repository.py`, Gateway admission/deadline modules | Phase 2 leases | Shared connection quotas, local byte budgets, direct expiry/revocation closure | quota recovery, deadline and replacement tests |
| Helm topology | root | `infra/charts/azents/**` | Stable Gateway settings and ports | Conditional Deployment/Service/Ingress/TLS, trusted-Control network path, resources/HPA/PDB and schema validation | Helm render/schema tests |

- Integration order: phase plan and settings contract → auth repository/service → pure browser/Host/Origin/header policies → Gateway composition and trusted transport adapter → admission/deadline enforcement → Helm topology → focused integrated validation.
- Direct implementation: root agent owns all implementation and integration. Delegation is limited to final read-only review.
- Independent review: `gateway-independent-reviewer` reviews the complete Phase 3 diff against Requirements, accepted ADR, Design authority and this plan, focusing on credential isolation, browser identity injection resistance, exact origin/host handling, Service Worker/no-store enforcement, bounded streaming, quota/deadline correctness, feature-disabled rollout and Helm trust boundaries.
- Final validation: focused Gateway/repository/service pytest; backend Ruff and type check on affected modules; Helm render/schema tests; pre-commit; stacked PR creation with Phase 2 base. Full CI is intentionally deferred until Phase 3–5 PRs all exist.
- Scope-drift check: Every changed behavior must trace to M3/M6–M9/M11–M14; reject Main Web UI/cookie migration, Chat/Services UI, unsupported browser modes, new approval authority, unsafe compatibility fallback, durable application bytes or changes to Terminal/File Transfer behavior.
- Context checkpoint: Phase completes when valid configured Chromium traffic can authenticate through either approved identity establishment mode, pass exact Session/cycle/CORS/admission checks, and stream HTTP/SSE/WebSocket over the Phase 2 trusted Control transport, while invalid configuration and browser/security attacks fail before Runtime traffic and Helm remains disabled by default.
