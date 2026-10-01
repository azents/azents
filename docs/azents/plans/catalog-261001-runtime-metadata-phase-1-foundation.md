---
title: "Runtime-Aligned Model Metadata Phase 1: Source and Profile Foundation"
created: 2026-10-01
tags: [model-catalog, implementation, backend, engine, migration]
---

# Runtime-Aligned Model Metadata Phase 1: Source and Profile Foundation

## Phase Execution Plan

- Phase: `1, source and profile foundation`.
- Branch/base: `feat/catalog-261001-runtime-metadata-1-foundation` → `origin/main` `aff07a204de44bf72ff3adb11e4d5bedd61459d2`.
- PR boundary: introduce and validate the replacement source/profile/persistence foundation and shadow candidates without changing current catalog pointers, runtime metadata readers, public APIs, or active LiteLLM authority.
- Inputs: confirmed [Requirements](../requirements/catalog-261001-runtime-aligned-model-metadata.md), accepted [ADR](../adr/catalog-261001-runtime-aligned-model-metadata.md), approved [Design](../design/catalog-261001-runtime-aligned-model-metadata.md) revision 2, and [implementation plan](catalog-261001-runtime-metadata-implementation-plan.md).
- Deliverables: direct genai-prices dependency; JSON-safe canonical source schema and public fetch adapter; generic source authority/snapshot persistence; candidate snapshot provenance and rollback-pin schema; shared credential-free runtime profile resolver consumed by existing runtime construction; shadow source collection and candidate system projections; deterministic focused fixtures and diagnostics.
- Non-goals: changing current source readers, current system catalog pointers, integration catalog projection, runtime context/pricing authority, public API/client shapes, provider listing behavior, or removing the legacy source path.
- Interfaces: public `UpdatePrices.fetch()` is the only remote library operation; generic source schema is versioned and JSON-safe; resolver inputs/outputs match Design M1; current runtime behavior remains byte/semantic equivalent after inline profile extraction; candidate publication cannot change `current_snapshot_id`; `rollback_snapshot_id` remains null in phase 1.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M6`, `M12`, and phase-1 foundation for `M9`.
- Authority references: `catalog-261001/REQ-1` through `REQ-3`, `REQ-7`, `REQ-8`; `catalog-261001/ADR-D1` through `ADR-D4`; current Model Catalog Spec stored-read and scheduler behavior.
- Design delta: `None`.
- Removal obligations: remove duplicated inline provider profile composition only after the shared resolver owns identical runtime construction; no legacy source/schema/config removal in this phase.
- Absence verification: no second process-global metadata authority; resolver rules are not duplicated between factory and projection; no candidate becomes current; no rollback pin is set; no private genai-prices parser/import is used.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Dependency and canonical source adapter | `/root` | `python/apps/azents/pyproject.toml`, lockfile, new source schema/adapter modules and focused tests | Approved D2/D3 | Exact direct dependency, public fetch boundary, canonical matching/context/lifecycle/pricing encoding, safe validation | uv lock check, Ruff, ty, adapter golden/parity/error tests |
| Generic source and candidate persistence | `/root` | `rdb/models/llm_catalog.py`, `repos/llm_catalog/`, data types/tests, one generated Alembic revision and migration tests | Canonical schema | Source authority/snapshots, provenance fields, rollback pin, candidate create/query/publish primitives that preserve pins | Isolated PostgreSQL repository and fresh/upgrade migration tests |
| Shared runtime profile resolver | `/root` | new defining module under `engine/providers/`, `model_factory.py`, native OpenAI policy inputs as required, catalog capability projection seams and focused tests | Existing runtime construction | One pure resolver and unchanged provider model construction/profile behavior | Provider-family parity, protocol/profile/native-tool tests, full affected engine tests |
| Shadow orchestration and candidates | `/root` | `services/llm_catalog/`, scheduler registry, focused service/scheduler tests, deterministic fixtures | Adapter, persistence, resolver | Scheduler/Admin orchestration collects generic source and builds non-current system candidates while old publication remains current | Source failure/reduction/supersession tests, candidate completeness, pointer/pin invariants |
| Integration, docs, validation, review, PR | `/root` | plans, phase-reachable Spec corrections only if behavior is reachable, cross-workstream fixes | All workstreams | Stable integrated phase diff, evidence, reviewer clearance, phase PR | Root-owned focused and integrated checks, docs validation, pre-commit, independent review |

- Integration order: approve and commit plans; add exact dependency and source domain schema; generate persistence migration and repositories; extract shared resolver and prove runtime parity; add shadow service/candidate orchestration; integrate and run root validation; freeze diff; request exact reviewer; correct and revalidate; commit and open phase 1 PR.
- Independent review: `/root/catalog-metadata-reviewer`; root requests review only after all phase workstreams are complete and the integrated diff is stable.
- Final validation: `uv lock --check`; focused `uv run ruff check` and `ruff format --check`; `uv run ty check --error-on-warning`; source adapter, repository, migration, resolver, model factory, catalog service, scheduler, and existing provider contract pytest; package/global-state/private-API absence searches; docs snapshot validation; pre-commit on changed files.
- Scope-drift check: current catalog/runtime authority and public behavior must remain unchanged; no active source cutover, integration reprojection, fallback, new public mode, user setting, source API, or destructive cleanup. Every new persisted field is authorized by M2/M3/M6/M9 and remains inert until phase 2.
- Context checkpoint: revision 2 is approved and reviewer-cleared, current main is integrated, implementation has not started, and this plan is the exact phase contract.
