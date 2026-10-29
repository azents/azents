---
title: "Agent-Scoped Model Backend Implementation Plan"
created: 2026-10-28
tags: [engine, inference, security]
---

# Agent-Scoped Model Backend Implementation Plan

- Requirements: [relay-261028/REQ](../requirements/relay-261028-model-inference.md)
- ADR: [relay-261028/ADR](../adr/relay-261028-model-inference.md)
- Design: [relay-261028/DESIGN](../design/relay-261028-model-inference.md), approved revision 1, exact mechanisms M1–M16.
- Design delta: None.
- Implementation/integration/validation owner: primary agent.
- Exact independent reviewer: `/root/relay-reviewer`, read-only on stable integrated phase diffs; primary applies findings.

## Delivery phases

| Phase | PR scope | Dependency | Mechanisms |
| --- | --- | --- | --- |
| 1 | Shared target identity and typed authority contracts, approval snapshot and contract CI | None | M2, M3, M6, M7, M9, M16 |
| 2 | PostgreSQL system-token lifecycle, Admin development and private resolve/list APIs, Agent deletion integration | Phase 1 | M2–M7, M10, M15, M16 |
| 3 | Actual MIT Proxy extension, packaging and chart, no Worker routing changes | Phase 2 | M1, M6–M13, M16 |
| 4 | Representative real-Proxy verification, security/privacy/provider contract coverage, Spec promotion and plan cleanup | Phase 3 | M14 and integrated M1–M16 |

Phase count is a review decomposition, not authorization for additional product behavior. Each phase PR opens before starting its dependent phase; merge remains requester-controlled. PR titles use `LLM backend [n/4]: ...`.

## Interfaces

A small shared library owns pure target-ID computation and closed DTOs for protected list/resolve calls, including typed provider credentials. Azents application owns durable token and OAuth authority. The Proxy package depends on the shared library, never imports the Azents app, and uses official custom auth/hook registration. Existing Agent settings are the only model/account map. Existing Worker remains unchanged.

## Validation and external prerequisites

Primary runs format/lint/typecheck/tests, repository token/concurrency tests, generated-client checks, chart render checks, and a minimal real-Proxy journey. Existing upstream research is seam evidence only. Track source revision, no-Enterprise packaging, sentinel absence and physical request counts. Run authorized live provider checks only after explicit credentials/usage approval; unavailable live checks remain unverified.

Known provider fidelity conditions (ChatGPT prompt cache key and generated-image history) must be resolved with a bounded supported mechanism before backend readiness. No permanent fork, new canonical adapter, optional second backend or relaxed parity is authorized. Continue independent foundation work while investigating; escalate only a genuinely new material mechanism.

## Removal and specifications

Worker adapters, usage persistence, Agent settings and provider secret stores remain. Exclude Enterprise from the new Proxy artifact, not from unrelated installations. New Agent-owned token state must join the deletion registry. Update owning Specs with schema/API behavior in the implementing phase; run full spec review once against the integrated feature before final QA. Remove temporary plans after verified implementation/spec promotion, never before evidence is complete.

## Rollout and checkpoints

No production deployment, merge, real login, or billable inference is authorized by the implementation request. Initial replicas=1 is configuration, not a scale restriction. Record each phase's behavior, interface changes, validation, review, PR/CI, remaining paths and blockers here. Do not mark Requirements/Design implemented before all verification is complete.

### Current checkpoint

Implementation is starting. Design approval has been recorded; no product code changed yet. Phase 1 owns a standalone shared contract and its CI; server state follows in Phase 2. Reviewer assigned and reading authority documents.
