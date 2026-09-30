---
title: "Provider Replacement Phase 1: Retained Source Ingestion"
created: 2026-09-30
tags: [inference, implementation, model-catalog]
---

# Provider Replacement Phase 1: Retained Source Ingestion

## Phase Execution Plan

- Phase: 1, retained-source ingestion.
- Branch/base: `feat/inference-260930-source` -> `main` at `fd0093423a3b7ecf714a67603eabb339e1962bef`.
- PR boundary: package-free catalog metadata ingestion and historical source provenance preservation, together with approved snapshot/implementation plans.
- Inputs: confirmed [Requirements](../requirements/inference-260930-provider-replacement.md), accepted [ADR](../adr/inference-260930-provider-replacement.md), approved [Design](../design/inference-260930-provider-replacement.md) revision 1 and [implementation plan](provider-replacement-implementation-plan.md).
- Deliverables: catalog source/projection consumes an Azents-owned typed source schema and configured URL without package imports; failed source records no bundled fallback; new collection records no installed version; same-hash refresh preserves historical version and stable IDs.
- Non-goals: new metadata feed or capability behavior, runtime adapter or context/pricing implementation, dependency removal from the entire app, active catalog schema/API descriptor migration, production deployment.
- Interfaces: retain source JSON vocabulary, exact aliases/provider/cloud identifiers, snapshot/hash/current/latest/attempt contracts, existing status/failure/fencing and conservative capability precedence. Source URL uses the current environment variable/default semantics. Schema definition includes only consumed fields, tolerates unconsumed extra fields and retains raw payload for snapshots.
- Approved Design mechanisms: M7, M12, M13 (partial implementation); no claim of full REQ-1 until phase 3.
- Authority references: `inference-260930/REQ-1`, REQ-6, REQ-7, REQ-8; ADR-D1, ADR-D5; Model Catalog Spec and immutable historical data constraints.
- Design delta: `None`.
- Removal obligations: installed metadata schema, source URL/version lookup and bundled fallback access in the catalog service. Historical source naming and version values remain.
- Absence verification: no executable package import/map/version/resources access in ingestion/projection module; focused source/projection tests pass with package access blocked; import graph/source search; same-hash provenance regression.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Typed retained source and package-free collection | `/root/source-ingestion-implementation` | `python/apps/azents/src/azents/services/llm_catalog/__init__.py`; new source-schema module under that package; source/projection test modules under the same package; `repos/llm_catalog/__init__.py` provenance method and focused repository tests | Approved baseline | Owned source schema, explicit configured URL, no package fallback or fake installed version, preserved projection behavior and same-hash provenance | Focused lint/type/tests; report exact commands and remaining prerequisites |
| Shared SDK client configuration extraction | `/root` | `core/openai_client_config.py` and its tests; direct config imports in `services/model_listing/providers.py`, `engine/events/openai_responses.py`, `engine/events/engine_adapter.py`, native adapter tests and OpenAI image tool/tests | Package-blocked source import finding | Unchanged SDK endpoint/header/config construction independent of inference pricing imports | Package-blocked catalog import plus native adapter, image and model-listing regression tests |
| Integration, documentation, root-owned validation and review/PR | `/root` | Snapshot approval/plan records, `docs/azents/spec/domain/model-catalog.md` phase-specific reachable source behavior, test environment and cross-workstream corrections only after implementer handoff | Source workstream and client-config extraction | Integrated stable diff, tests and evidence, phase PR | Root runs Ruff/ty/pytest plus docs validation, then requests the exact reviewer |

- Integration order: baseline approval and phase plan, source implementation and focused tests, root integration/validation, freeze diff, independent review, corrective work and affected rechecks, checkpoint/commit/PR.
- Independent review: `/root/provider-replacement-reviewer`; root requests review only after source work is complete and the integrated diff is stable. No separate decision owner or additional reviewer.
- Final validation: root-owned `uv run ruff check`, `uv run ruff format --check`, `uv run ty check --error-on-warning`, focused catalog source/projection tests, existing local/DB tests where prerequisites available, source import/package-access checks, documentation validator and diff checks. Full deterministic E2E remains the final feature gate; phase-specific checks cannot be reported as completed end-to-end replacement.
- Scope-drift check: no new source authority, runtime mode, fallback publication, capability policy or price estimate. Preserve provider visibility, last-good catalogs, IDs, historical provenance and image shared catalogs. Type/schema deviations from historical package fields must preserve current consumers rather than implicitly broaden support.
- Local discovery: package-blocked catalog import exposed a model-listing import of an OpenAI client configuration helper from the inference module, which also imports the old cost calculator. Extract the unchanged helper/data type into its defining core module and update all direct callers. This removes incidental transitive coupling under M7/REQ-1, changes no SDK configuration or execution contract, and introduces no material Design delta.
- Context checkpoint: source workstream and root client-config extraction integrated. Root's focused/integration test command across catalog, model listing, shared configuration, native OpenAI, images and engine assembly passed 193 tests (11.90 seconds, isolated PostgreSQL); whole-backend `ty check --error-on-warning` and focused Ruff passed. Required package-blocked source subprocess regression passed without deselection. No live-provider or complete cutover claim. Root freezes this diff for independent review and records the PR before phase 2 begins.
