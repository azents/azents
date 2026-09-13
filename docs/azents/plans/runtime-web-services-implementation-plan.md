---
title: "Temporary Runtime Web Services Implementation Plan"
created: 2026-09-12
tags: [runtime, web, implementation, planning]
---

# Temporary Runtime Web Services Implementation Plan

- Snapshot authority: [web-260912/REQ](../requirements/web-260912-runtime-web-services.md), [web-260912/ADR](../adr/web-260912-runtime-web-services.md), [web-260912/DESIGN](../design/web-260912-runtime-web-services.md) revision 2
- Approved mechanism IDs: `M1`–`M14`
- Design delta: `None`
- Independent reviewer: `gateway-independent-reviewer`

## Stack

1. **Authority foundation** — durable endpoint/request/cycle/config records, shared Session authority, Public API, Runtime-independent Agent tools, generated clients and design snapshot. Base: `origin/main`.
2. **Runtime transport** — typed protobufs, owner-routed Control relay, Runner HTTP client, transport leases and focused integration tests. Base: phase 1.
3. **Gateway and deployment** — Gateway process, both browser identity establishment modes, HTTP/CORS/security enforcement, quotas, Helm topology/configuration. Base: phase 2.
4. **Main Web experience** — production cookie hardening, trusted confirmation/broker continuation, Chat request card, Services panel and localization/stories. Base: phase 3.
5. **E2E, Specs and cleanup** — real Runtime/browser/cross-replica matrix, security/streaming evidence, Living Spec promotion, implemented markers, and removal of all feature plans. Base: phase 4.

Every branch is opened as a stacked PR before work starts on its successor. Later phases consume only committed interfaces from earlier phases. Any material change returns to the approved Design before implementation.

## Integration Boundaries

- Phase 1 defines durable typed domain and generated API/tool contracts; no live proxy.
- Phase 2 defines trusted Gateway/Runner transport contracts without public browser admission.
- Phase 3 exposes the data plane only behind validated feature configuration.
- Phase 4 consumes generated clients and trusted control routes; it does not create a second approval authority.
- Phase 5 is the only spec-promotion and plan-cleanup boundary.

## Removal Obligations

- Production Main Web legacy cookie names: phase 4.
- OAuth approval reuse absence and strict Runtime Web Chat adapter: phase 4.
- Visibility/extend/generation-invalidates-approval/response-cap/query-ticket proposal absence: phases 1–4, verified in phase 5.
- Existing Terminal/File Transfer behavior remains and receives regression coverage.

## Validation

Each phase runs focused format/lint/type/test and one read-only review. Phase 5 runs generated-contract checks, required backend/TypeScript suites, actual prepared Session environment, real Docker Runtime, two auth modes, cross-replica relay, TLS/browser security probes and spec review. CI is monitored after all stacked PRs exist. No PR is merged without the requester's explicit approval.
