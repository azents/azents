---
title: "Runtime-Aligned Model Metadata Phase 2: Authority Cutover and Reprojection"
created: 2026-10-01
tags: [model-catalog, implementation, backend, engine, migration]
---

# Runtime-Aligned Model Metadata Phase 2: Authority Cutover and Reprojection

## Phase Execution Plan

- Phase: `2, authority cutover and bounded reprojection`.
- Branch/base: `feat/catalog-261001-runtime-metadata-2-cutover` → `feat/catalog-261001-runtime-metadata-1-foundation` / PR #2018.
- PR boundary: switch runtime context and pricing capture, system catalog publication, and integration projection to the generic source/runtime resolver; pin exact pre-cutover catalog snapshots; and add bounded network-free integration reprojection without deleting legacy storage required for coordinated rollback.
- Inputs: reviewer-cleared Phase 1 interfaces and commit `ea201bfa5`; confirmed [Requirements](../requirements/catalog-261001-runtime-aligned-model-metadata.md), accepted [ADR](../adr/catalog-261001-runtime-aligned-model-metadata.md), approved [Design](../design/catalog-261001-runtime-aligned-model-metadata.md) revision 2, and [implementation plan](catalog-261001-runtime-metadata-implementation-plan.md).
- Deliverables: captured generic source lookup and isolated genai-prices evaluation; replacement source/runtime authority with no legacy read fallback; atomic candidate publication with one rollback pin; replacement scheduler/Admin system refresh; replacement integration projection; idempotent bounded reprojection from stored provider-visible entries; coordinated rollback primitives retained for the pre-cleanup window; unchanged public responses and saved selections.
- Non-goals: dropping legacy LiteLLM tables/code/config/tests, clearing rollback pins, changing public/Admin schemas, provider listing behavior, saved model selections, or performing any live database/Kubernetes cutover.
- Interfaces: `ModelMetadataService` captures `ModelMetadataSourceSnapshot`; source matching reconstructs an isolated typed view without global mutation; catalog cutover verifies candidate provenance and pins the exact current snapshot once; ordinary publication preserves a pin; integration reprojection fences current snapshot and configuration generation and performs no provider I/O; normal reads remain stored-only.
- Approved Design mechanisms: `M5`, `M7`, `M8`, `M9`, `M11`, `M12`, integrated with Phase 1 `M1` through `M6`.
- Authority references: `catalog-261001/REQ-1` through `REQ-6`, `REQ-8`; `catalog-261001/ADR-D1` through `ADR-D4`; current Model Catalog stored-read, integration visibility, synchronization, and saved-selection Specs.
- Design delta: `None`.
- Removal obligations: remove active runtime/context/pricing, system publication, integration projection, and optional xAI enrichment reads from the legacy source; retain legacy storage and coordinated rollback evidence until Phase 3 cleanup.
- Absence verification: runtime and active projection paths contain no `LiteLLMSourceSnapshot` or `litellm_model_cost` read/publication authority; normal reads and dispatch perform no remote metadata fetch; no automatic legacy fallback is introduced.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Captured source context and pricing | `/root` | `core/model_metadata_source.py`, `core/model_pricing.py` or replacement source-pricing module, `services/model_metadata.py`, engine context/pricing tests | Phase 1 canonical source | Generic snapshot lookup, context fallback, isolated pricing evidence/provenance, nullable unsupported outcomes | Typed-source parity fixtures, context capture, pricing and provider-charge precedence tests |
| Atomic system cutover and rollback pin | `/root` | `repos/llm_catalog/`, `services/model_metadata_projection.py`, system projection service and scheduler/Admin tests | Candidate provenance and rollback schema | Readiness validation, candidate publication, exact one-time rollback pin, failure atomicity, coordinated rollback primitive | PostgreSQL repository race/failure tests, system cutover service tests, pointer invariants |
| Integration replacement projection | `/root` | `services/llm_catalog/`, `services/model_listing/`, integration projection tests | Shared resolver and generic source lookup | Provider-visible entries reproject through replacement source/profile policy, including optional xAI enrichment without visibility gating | Provider matrix parity, unmatched/malformed source, generation fencing, no-network tests |
| Bounded reprojection coordinator | `/root` | scheduler registry, new coordinator service/repository seams and tests | Replacement integration projection and publication fencing | Idempotent bounded batches from stored current entries, backlog/failure summaries, concurrent normal sync wins | Batch/idempotency/fencing tests and scheduler registration tests |
| Integration, docs, validation, review, PR | `/root` | phase plan, reachable Specs, cross-workstream corrections | All Phase 2 workstreams | Stable stacked Phase 2 diff and evidence without Phase 3 cleanup | Ruff, format, ty, focused/full pytest, lock/diff, pre-commit, independent review |

- Integration order: record and commit this plan; implement generic captured source matching/pricing; add atomic publication/rollback primitives; replace system refresh authority; replace integration projection; add bounded reprojection; update reachable Specs; run integrated validation; freeze diff; request `/root/catalog-metadata-reviewer`; correct and revalidate; commit and open the Phase 2 PR before Phase 3.
- Independent review: `/root/catalog-metadata-reviewer`; root requests review only after every workstream is integrated and the Phase 2 diff is stable.
- Final validation: focused Ruff and format; `uv run ty check --error-on-warning`; source/context/pricing parity tests; catalog repository/migration/system/integration/scheduler tests; full backend pytest; both affected lock checks; Alembic single-head check; tracked absence searches; documentation validation and pre-commit on changed files.
- Scope-drift check: Phase 2 must activate only approved replacement authority and rollback/reprojection behavior. It must not remove rollback evidence, preserve an automatic legacy fallback, change public responses, contact providers during bounded reprojection, rewrite saved selections, or introduce a new source of truth.
- Context checkpoint: Phase 1 PR #2018 contains canonical source persistence, shared runtime resolver, shadow candidates, provenance, rollback schema, and reviewer-cleared failure/race coverage. Phase 2 starts from commit `ea201bfa5`; current production authority remains legacy until this phase's code is deployed and its explicit publication path runs. Phase 3 still owns destructive LiteLLM cleanup, final absence gates, E2E validation, spec promotion, and plan removal.
