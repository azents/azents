---
title: "Agent-Scoped Model Backend Implementation Plan"
created: 2026-10-28
updated: 2026-10-29
tags: [engine, inference, security]
---

# Agent-Scoped Model Backend Implementation Plan

- Requirements: [relay-261028/REQ](../requirements/relay-261028-model-inference.md).
- ADR: [relay-261028/ADR](../adr/relay-261028-model-inference.md).
- Design: [relay-261028/DESIGN](../design/relay-261028-model-inference.md), approved r1 M1–M16.
- Design delta: None. The requester-approved one-time published-dev dependency exception is recorded in Requirements; no provider scope, credential authority or backend mode changes.
- Primary agent owns implementation, integration, validation and review corrections.
- Exact independent reviewer: `/root/relay-reviewer`, read-only on the root-integrated completed diff.

## Delivery shape

| Phase | PR scope | Dependency | Mechanisms |
| --- | --- | --- | --- |
| 1 | Pure target identity and typed authority contracts, approved snapshot | None | M2, M3, M6, M7, M9, M16 |
| 2 | PostgreSQL token lifecycle, Admin/private APIs, refresh/revalidation, deletion | Phase 1 | M2–M7, M10, M12, M15, M16 |
| 3 | Original Proxy extension, published package/image/chart, representative E2E, Spec promotion and plan cleanup | Phase 2 | M1, M6–M14, M16, integrated M1–M16 |

The original fourth validation/Spec phase is consolidated into the existing final Proxy PR so the requester receives a complete reviewable backend rather than an extra validation-only stack layer. This changes execution decomposition only. Existing PRs #2523/#2524 remain the foundations; Draft #2529 remains based on `feat/relay-authority`. No merge/deployment is authorized.

## Interfaces, ownership and removal

The shared library owns target hashing and closed private DTOs. The server owns current Agent/integration settings, token state, refresh and AWS role-session preparation. The real LiteLLM Proxy owns provider serialization, streaming and the unified wire protocol. The Proxy gets no issuer secret, refresh store, model table or Worker usage ledger. Worker/Runtime relocation and automatic operational token delivery remain out of scope.

Use published `litellm==1.109.0.dev1` only for the explicitly approved ChatGPT forwarding exception. Keep its stable-transition condition beside the pin. Remove the old Git source, source-provenance assumptions and Rust build prerequisites. Retain original notices and verify Enterprise absence without bypassing license checks. Existing Worker adapters, integration storage and usage persistence are retained.

## Completion matrix

1. Published wheel/lock/image: exact registry identity, no source fallback, MIT core audit, isolated nonroot startup/shutdown and no ambient provider environment.
2. Authority: current online admission, issuer/resolver separation, prepare/external I/O/final validation, bounded token lifecycle and races, Agent deletion.
3. Cloud/subscription: server-issued Bedrock role tuple and expiry, static-key identity, warm-cache Vertex A/B/A and denial, ChatGPT account/token pairing and no file fallback, current Grok native incremental streaming.
4. Fidelity: current settings/caps/tools/reasoning/cache/tier, provider usage subsets, native continuation and cross-provider client tool/result and image history.
5. Privacy/lifetime: no alternate controls, no hidden replay on actual HTTPX and Kimi HTTPX2 branches, late errors/disconnect/close, verified safe operational fields with no body/secret diagnostics.
6. One required E2E: reuse existing public/Admin/auth/configuration fixtures; add only the original Proxy image. Test two Workspaces/accounts for one model, actual Admin issuance, settings mutation, forbidden call, revocation and survival of a first-delta-admitted stream. Use real authority HTTP over a verified test TLS facade; control only final provider network. No DB mutation or mocked binding/authorization.
7. Current Specs and documentation: promote Proxy ingress/settings/provider/error/lifetime/deployment behavior and server STS contract, update stale current README/notices/checkpoints. Keep unavailable live-provider checks explicitly unverified.
8. Root-owned format/lint/typecheck/tests/image/Helm/support/E2E, same-reviewer integrated clearance, existing PR update and successful new-SHA CI. Only then mark Requirements/Design implemented and remove temporary plans.

## Evidence checkpoint

Predecessor Phase 1 PR #2523 had 41 passing checks. Phase 2 PR #2524 head `eb4337252` had 37 passing/intentionally skipped checks. Previous Draft #2529 Git-source CI40782231789 passed but is historical, not published-wheel acceptance.

Current published-dev implementation: Proxy267 tests pass (Ruff/ty pass), contract53 pass, server role-preparation/safety tests pass with official SDK Stubber and cancellation/expiry/failure cases. Actual published-wheel image built without Rust/upstream source and nonroot/network-none smoke passed health200, unauthenticated401, management403 and bounded SIGTERM. Final image must be refreshed after the composition-root test dependency injection change.

An independent gap audit identified useful safe observability, reasoning/tool history wires, Kimi lifetime coverage, assembled APIs and owning Specs. The first three code/test lanes are now implemented: allowlisted original Proxy callbacks, a genuine lazy SDK reasoning-summary bug fixed at ingress, cross-provider tool pairing, and counted Kimi HTTPX2 failure/disconnect cases. The actual two-workspace E2E and final Spec/review/CI work remain incomplete. These interim counts are not whole-feature clearance.

The old blanket Vertex-cache blocker was withdrawn after requirement/authority rechecking and real JWT/warm-cache A/B/A/denial evidence. Bedrock STS is an implemented server preparation path, not an unresolved architecture choice. Current Grok4.7 supports native streaming. No live-provider use, entitlement claim, merge or deployment has occurred.
