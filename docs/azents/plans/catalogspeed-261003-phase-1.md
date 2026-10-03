---
title: "Current Model Catalog Phase 1 Execution"
created: 2026-10-03
tags: [model-catalog, pricing, implementation]
---

# Phase 1: Current Data and Embedded Pricing

- Branch/base: `refactor/catalog-latest-pricing-261003` -> `main`.
- PR boundary: complete atomic schema/data/runtime/API feature; one PR.
- Inputs: confirmed `catalogspeed-261003/REQ`, accepted `catalogspeed-261003/ADR-D1` through `/ADR-D4`, approved Design revision 2 and authority set M1-M9.
- Deliverables: latest-only catalogs/source models and sync status, normalized catalog/selected prices, zero whole-source price/hash dispatch work, narrow optional context reads, safe data conversion, coherent contracts and deterministic validation.
- Non-goals: changes to intended waiting/Toolkit/model behavior, stronger conversation selection, new price-history/cache/mode/fallback, live migration/deployment/merge.
- Interfaces: fixed common pricing field/definition; current-data source/catalog repository contracts; purpose-specific selection/admission; current API metadata; exact missing-field migration and historical read contracts.
- Approved Design mechanisms: M1-M9.
- Authority references: Requirements REQ1-REQ6, ADR D1-D4 with D1 purpose scope clarification, unchanged selection/context/estimator/integration authority Specs.
- Design delta: `None`.
- Removal obligations: source/catalog snapshots/pointers/candidates/history/hashes/fingerprints, append-only catalog attempts, whole-source execution pricing/context reads, obsolete guards/FKs/indexes/API/CLI/generated/UI fields.
- Absence verification: active-schema and caller searches; exact source/price capture counters; API/client schema checks; deterministic current-data/race/migration tests; historical artifacts and executed migrations deliberately excluded from removal.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Pricing/execution | `/root/pricing-selection-evidence` | `core/agent.py`, `core/model_pricing.py`, `core/catalog_price_rules.py` as needed; shared selection tests/factory; `engine/events/engine_adapter.py`, usage/pricing/types/output; `engine/run/resolve.py`; `worker/run/executor.py`; `engine/tools/subagent.py`; exact context consumers; `services/model_metadata.py` and read repo coordinated with storage | Shared current source query interface | Typed persisted price, cheap capture, actual-candidate propagation and context narrowing | Focused price/rule/selection/output/context tests, lint/type evidence |
| Persistence | `/root/catalog-state-evidence` | source/catalog RDB models; source/catalog repository DTOs and low-level/completed operations; current status and exact model query repositories, associated repository tests | Shared typed pricing definition | Current rows, publication locking/ownership/value comparison and coherent reads | Focused repository/race tests, schema and obsolete-symbol evidence |
| Services/contracts | `/root/catalog-service-implementation` | source collector/source/system projection/catalog/image services; integration invalidation repo where needed; public/admin catalog DTOs/routes, CLI/scheduler catalog registration and associated service/API tests | Storage DTOs/ops and pricing definition | Current-only orchestration, exact selection copy, credential/image protections and new status contracts | Focused source/service/API/image/selection tests and lint/type evidence |
| Integration/migration/client/QA | `/root` | linear migration and revision; remaining adapters/wiring; OpenAPI/generated clients; TS UI/TRPC; required fixtures/E2E; Specs and snapshot dates; plans | Complete backend contracts | Coherent feature and validated release diff | Complete root-owned backend/client/TS/E2E/migration/absence/docs validation |
| Independent review | `/root/catalog-design-owner` | Whole stable phase diff, read-only | Root integration and validation complete | Requirements/authority/security/data-loss/interface findings | Root-owned correction and any targeted re-review |

Owners do not edit each other's paths without root reassignment. Storage defines current source DTO/query signatures and informs pricing/services before their dependent edits. Pricing defines the compact typed price contract first. Root resolves imports/wiring and migration-only dependencies, not new design authority.

## Integration Order

1. Freeze shared pricing/source/current-status interfaces.
2. Implement current schema and repositories alongside pure price definition/selection/runtime changes.
3. Integrate source/provider services, credential invalidation, API/CLI and exact selectors.
4. Implement the generated linear migration and missing-price inventory; reconcile all executable saved fields and historical decoding.
5. Regenerate OpenAPI/clients; update TS consumers/fixtures/E2E; run complete integrated checks.
6. Freeze diff; request the sole review; correct findings and rerun invalidated checks.
7. Promote current Specs, mark verified snapshot implementation date, remove temporary plans, commit/create PR and own CI to completion.

## Final Validation

Root verifies catalogue/schema/current-data parity, source shrink and failure policy, work-token ABA and exact-value changes, credential races, image versus conversation predicates, coherent selection, lossless Decimal/rule persistence, unchanged estimator and provider-zero precedence, actual fallback/lightweight/subagent/compaction pricing, zero price-source restore/hash work, narrow context precedence, current-only migration and old-work quiescence, historical records/readability, generated API clients, UI consumers and required E2E.

Use explicit barriers/current state for races, isolated prerequisites and masked credentials. No live DB/cluster action. No speedup is claimed before equivalent-condition measurement; provider generation time is separate.

## Scope and Context Checkpoints

CI correction scope: preserve expected provider-local projection failures within
the existing one-transaction source/system publication and truthful per-provider
summaries; update the actually used testenv seed/setup to canonical exact model
options. Global validation/shrink/unexpected failures retain the old preservation
boundary. These are M1/M2/M9 behavior-preservation and M8 contract corrections,
not new authority. Design delta: None. Root owns source publication and integrated
validation; `/root/catalog-service-implementation` owns the bounded seed/setup
correction; `/root/catalog-design-owner` remains the sole reviewer.

The subsequent CI decoder correction aligns the normalized Decimal-string
schema with actual scientific-notation JSON (M3/M8) without changing arithmetic,
raw-source validation, or wire values. Root regenerated clients and validated the
full backend (9,142 passed/3 skipped), actual SDK round trips, testenv (148
passed)/E2E support (555 passed), and fresh frontend matrix. The same sole reviewer
accepted the targeted correction and independently reran the six SDK and twelve
core schema cases.

- Scope-drift check at each integration boundary: every approved behavior/removal covered; no new authority/history/hash/cache/fallback/mode, no conversation predicate strengthening.
- Latest-base checkpoint: `359bc0ff9`, with existing model transition adaptation retained; approved design delta none.
- Shared contract checkpoint: current source/model/status DTOs, embedded normalized price definitions, purpose-specific image usability, exact context batches, and generated clients integrated.
- Integrated behavior/interface/removal evidence: root post-review full backend 9,127 passed/3 skipped; separate migration matrix 20 passed including metadata/DDL alignment; affected catalog/migration/service rerun 151 passed and final current-data regression 22 passed; corrected E2E support 555 passed; fresh cache-bypassed TypeScript types/lint/format and both app builds passed, main-web unit tests 347 passed. Active-path scans include required E2E/support and confirm obsolete catalog graph/hash/candidate contracts and full-source dispatch reads removed. See the supporting validation report.
- Stable independent review target and final root QA: implementation owner writes complete; current Specs updated; sole read-only review by `/root/catalog-design-owner` found R1-R3, root corrections and invalidated checks passed, and targeted re-review accepted all three with no remaining grounded findings. Local assembled-product QA is unverified because the pinned MinIO client image cannot be pulled during source environment preparation; no stale source fallback was used.
- PR/CI and cleanup: PR #2090, initial commit `aa7a87c84`; initial CI identified a scoped provider failure and root testenv seed-contract/readiness gaps. Root backend 9,130 passed/3 skipped, root testenv 142 passed, E2E support 555 passed, and sole targeted review/re-review accepted all corrections. Required product E2E, implementation date promotion and plan cleanup remain pending the next normal push and CI.
