---
title: "Current Model Catalog Implementation Plan"
created: 2026-10-03
tags: [model-catalog, pricing, performance, implementation]
---

# Current Model Catalog Implementation Plan

- Authority: [Requirements](../requirements/catalogspeed-261003-current-model-data.md), [ADR](../adr/catalogspeed-261003-current-model-data.md), [approved Design revision 2](../design/catalogspeed-261003-current-model-data.md).
- Approved mechanisms: `M1` through `M9`.
- Requester implementation authorization: 2026-10-03, after final Design delivery.
- Design delta: `None`.
- Delivery shape: one atomic feature PR, not an artificial stack. Destructive schema and runtime authority changes must ship together.
- Branch/base: `refactor/catalog-latest-pricing-261003` -> `main`.
- Implementation base: `359bc0ff9`; later main fixes adapt model reasoning/options and absolute file publication without changing this catalog design authority. Preserve those fixes.
- Exact independent reviewer: `/root/catalog-design-owner`, read-only; root requests review only after complete stable integration.
- Root owns integration, shared interfaces, migration, generated clients, QA, review corrections, Specs, PR and CI.

## Execution Decomposition

| Workstream | Owner | Scope | Approved authority |
| --- | --- | --- | --- |
| Typed pricing, selected models and execution/context | `/root/pricing-selection-evidence` | Normalized definition, lossless rules, selection field, cheap call capture, historical decoding, exact context read consumers and focused tests | M3-M6, M9; D2/D3 |
| Latest-only persistence and atomic repositories | `/root/catalog-state-evidence` | RDB current source/catalog models, repository DTOs/current status, exact source reads, atomic publication and invariants/tests | M1/M2/M8; D1/D4 |
| Source/catalog orchestration and contracts | `/root/catalog-service-implementation` | Collector, source/system/integration/image services, exact selection copying, API/CLI/status, stale credential publication, current image invalidation and focused tests | M1-M4/M7-M9; D1-D4 |
| Integrated data/client/UI/verification | `/root` | New linear migration, authoritative data initialization, generated clients, TS consumers, required fixtures/E2E, Specs, complete checks and shipping | M5/M7-M9; D3/D4 |
| Complete independent review | `/root/catalog-design-owner` | Complete root-integrated diff, authority and absence review; no edits | Entire approved Design |

There is one tracked [phase execution plan](catalogspeed-261003-phase-1.md). Implementation owners may research their assigned paths only and must coordinate contracts before changing shared imports. They do not create PRs/commits, start later phases, change Requirements/ADR/Design, or mutate live infrastructure.

## Shared Contracts

- Common typed embedded price field: `AgentModelSelection.pricing`; definition type `ModelPricingDefinition` in the existing pricing core. Historical absence decodes read-only to absent; new server selection explicitly sets a typed definition.
- Definition contains existing lossless `CatalogPriceRules` or unavailable reason, descriptive source/model key and aware collection time. No dataset ID, source hash, fingerprint, raw source payload or call timestamp is persisted in it.
- Source storage represents current normalized per-model facts and pricing. Maintenance can obtain a detached complete current source view, but runtime optional context reads only requested exact keys and pricing capture reads no DB.
- Catalog rows and entries use stable owner/model identities; current synchronization is one status record with work ownership only. Image usability preserves image generation-current behavior; conversation selectors never acquire a stronger usability/config-generation predicate.
- Repository transactions own all SQL; collectors and service I/O remain outside them. Common lock order is integration -> source -> sorted catalogs -> entries. Source values/presence, not active tokens, validate prepared data freshness.
- Services/API outputs contain current data/time/status/counts and image usability. Snapshot/hash/generation/candidate output and commands are removed. Mutation price authority stays server-owned.

## Validation and Removal

Apply the complete Design E2E/race/migration matrix. Root executes integrated quality/type/unit/repository/E2E and TypeScript/client checks; owners provide focused evidence. All obsolete source/catalog snapshot/candidate/history/hash/attempt/guard/API/CLI references must be removed from active paths in the same coherent release. Executed migrations, inert historical diagnostics and immutable old event JSON are not rewritten.

One new linear migration must replace installed database guards, carry current data and missing selected prices, initialize image usability correctly, then remove obsolete state. Quiescence includes queued/claimed old work. No legacy runtime source fallback, cache, dual writer, new operating mode, automatic model reselect, historical cost rewrite or live rollout is authorized.

Run source-generated OpenAPI/client workflows after backend contract stabilization. Update current Specs and matching implemented dates only after verified behavior, then remove these temporary plan files before final commit/PR. The independent reviewer reviews the complete stable integrated feature with these phase checkpoints preserved in the root Session report.

## Checkpoints

1. Approved authority and latest-base drift: complete; material delta none.
2. Shared contract and current-data repository alignment: pending.
3. Integrated schema/services/execution/API/data/client/UI: pending.
4. Root validation, absence evidence, single-reviewer corrections: pending.
5. Spec promotion, plan cleanup, PR and required CI: pending.

No live database, cluster rollout, or PR merge is part of execution.
