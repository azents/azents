---
title: "Model Support Phase 2: Single-Source Connection"
created: 2026-10-02
tags: [model-catalog, backend, engine, implementation]
document_role: supporting
document_type: phase-plan
snapshot_id: capability-261002
---

# Phase Execution Plan

- Phase: 2 of 3, single-source projection/runtime/pricing connection.
- Branch/base: `feat/catalog-261002-2-connection` -> `design/catalog-data-only-261002` at `46ddab434` (PR #2059).
- PR boundary: replace active Azents source/price consumers together; fieldwise projection and saved runtime contract integration. Entire stack requires phase-3 DB fencing before deployment.
- Inputs: phase-1 reviewer-clear foundation, 272 integrated tests and whole-backend ty pass; approved Design revision 2 M1–M13 and D1–D3.
- Deliverables: new-source durable collection/read, exact scoped enrichment, v2 capability projection, rich/sparse provider listing evidence, saved contract consumers/UI, Azents estimator and direct genai authority removal.
- Non-goals: migration/DB fence activation, production rollout, live provider probes, new source/default/compatibility mode or reinterpreting old selections.
- Approved mechanisms: M1–M10/M13; M11/M12 final DB and deployment gates are phase 3. Authorities: REQ-1–8, ADR-D1–D3 and unchanged catalog lifecycle.
- Design delta: None.
- Removal obligations: direct genai imports/source/evaluator/config/direct dependency; native Pydantic capability ceiling, sparse-default intersections, response/strict conflation, price-derived native support. Retain stock Pydantic execution formatting, transitive usage extraction, historical selection semantics and inert DB history.
- Absence verification: direct import/dependency/fetch/calc scans; exact source lookup; poisoned old pricing/updater and native model-profile APIs; price and provider mock-wire tests; descriptor-absent old JSON unchanged.

## Interfaces

`ModelMetadataSourceSnapshot` remains the generic repository DTO but its active payload is now `CatalogSourcePayload`. Restore canonical DB JSON through strict `model_validate_json`, not permissive Python dict coercion. Active source key/kind are defined at `core/model_catalog_source.py` and imported from that defining module (not re-exported through legacy modules). No genai payload alias or decoder remains in active readers.

`ModelMetadataService.lookup(snapshot, provider, model_identifier)` returns a scope-checked `CatalogSourceModel | None`. Use literal source key/provider mappings owned by the new source identity adapter; no name/family or publisher-path stripping, cross-host inheritance, or genai regex fallback. Exact sourced model facts and listing facts feed one producer of `ModelCapabilityContract`, then derive validated `ModelCapabilities` effective views.

Pricing normalization accepts the captured source snapshot/hash, exact `CatalogSourceModel | None`, provider/model execution identity and aware request time. `CapturedModelPricing` freezes typed interpreted rules or an explicit unavailable outcome. Remove the genai-specific normalizer name rather than preserve a legacy alias. `ModelPricingUsage`, `ModelPricingBilling` and valid native-charge precedence remain current semantic boundaries.

Typed provider evidence preserves actual presence across candidate replay. An absent evidence envelope on historical fixtures is unknown, not explicit false. Production listing adapters must supply their audited evidence. User selection inputs remain exact integration/model identifiers and never author capability facts.

## Ownership

Paths below are backend-relative under `python/apps/azents/src/azents`, except explicit frontend/generated entries. Agents do not edit other owners' paths.

| Workstream | Owner | Owned paths | Output and dependency |
| --- | --- | --- | --- |
| Source sync/read/persistence and orchestration | `/root` | `services/model_metadata_source.py`, `services/model_metadata.py`, `repos/model_metadata_source{,_data}.py`, old `core/model_metadata_source{,_test}.py` removal/references, `services/llm_catalog/__init__.py`, provenance DTO/RDB nullable history, app dependency/lock and related tests | New collector integration, source absence semantics, atomic existing lifecycle and core activation; coordinates child interfaces |
| Projection and transport bounds | `/root/openclaw-metadata-research` | new `core/model_capability_projection{,_test}.py`, `services/model_metadata_projection{,_test}.py`, `engine/providers/model_profiles{,_test}.py`, `engine/providers/model_factory.py` | Presence-aware v2 producer and actual native/Pydantic contract; no native model-profile lookup, no price inference; consumes source DTO/new listing evidence |
| Listing evidence | `/root/catalog-capability-parity-audit` | `services/model_listing/data.py`, `providers{,_test}.py`, new typed evidence module/test | All ten provider paths preserve omitted/false/null/empty; consume xAI metadata; no authentication change; coordinate candidate evidence schema with projection owner |
| Typed estimator | `/root/hermes-metadata-research` | new price-rule module/tests, `core/model_pricing{,_test}.py`, `engine/events/model_usage_pricing{,_test}.py` | Bounded source rule parser and complete-total arithmetic; source absence/old calls explicit; no genai import or blanket missing-rate fallback |
| Saved runtime contract | `/root/capability-runtime-implementation` | new semantic contract evaluator/tests, `core/builtin_tools{,_test}.py` configuration-versus-dispatch admission, `engine/run/builtin_tools{,_test}.py`, `engine/events/engine_adapter{,_test}.py` built-in admission/actual-context guard only, `engine/events/openai_responses{,_test}.py`, `events/responses_lowering{,_test}.py`, `engine/events/pydantic_ai_adapter{,_test}.py`, `engine/run/resolve{,_test}.py`, `services/session_title{,_test}.py`, profile/candidate compatibility consumer helpers only when assigned by root | Dispatch from saved conditions without source lookup/clamp; strict/structured split, native max/xhigh wire tests, historical absence preserves behavior |
| Frontend consumers | `/root/capability-ui-implementation` | TypeScript agent/composer model capability helpers/options editor and focused tests; no backend edits | New descriptor conditions drive controls conservatively; existing layout/integration-first workflow preserved; generated types consumed, no new source/UI mode |
| Generated interfaces/integration validation | `/root` | specs and client regeneration, exact remaining caller fixes after owners finish | Complete source-to-selection-to-request/cost integration and root-owned checks |

The exact single reviewer remains `/root/catalog-metadata-reviewer`; only root requests frozen-diff review or re-review. New runtime/UI implementation agents are bounded and receive approved paths and authorities.

## Integration and Validation

CI boundary correction: the deterministic source proxy, new source URL environment wiring and Docker-free support fixture are included in this connection phase. Leaving the retired URL variable until phase 3 caused phase-2 CI to fetch live public rates and invalidated the fixed-premium-unavailable test premise. The already reviewed final fixture is moved earlier without changing the complete-stack product tree, price logic or approved authority. Phase 3 retains representative saved-contract E2E and DB fencing.

1. Freeze source read and pricing capture interfaces and share them with projection/estimator owners.
2. Listing evidence and pure projection/parser/evaluator can be implemented independently; do not activate a second authority or source toggle.
3. Root rewires source/repository/services and caller capture; integrate owners' patches in place, regenerate APIs/clients and resolve all type/test failures.
4. Run source/schema/restore, ten-provider evidence/visibility, saved semantics, SDK mock-wire, title output and comprehensive estimator tests. Whole-backend ty, Ruff/format, TypeScript checks, no-genai authority scans, generated-client and docs checks.
5. Freeze integrated diff, request exact reviewer, fix all findings and rerun affected checks before commit/PR. Do not start phase-3 migration implementation before this PR exists.

- Scope-drift check: no extra model catalog, name patch, request-time lookup, saved migration, automatic effort/price fallback, OAuth or new batch/tool feature.
- Context checkpoint: phase SHA/PR, interfaces, actual tests, retired direct genai evidence, remaining migration/E2E/spec gates. Existing source and old catalog authority in production are untouched by this development task.
- Phase-3 deployment prerequisite remains mandatory: this branch alone is not safe for production without old-writer fencing and producer drain; no intermediate release is authorized.
