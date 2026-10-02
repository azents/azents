---
title: "Model Support Phase 1: Source and Evidence Foundation"
created: 2026-10-02
tags: [model-catalog, backend, implementation]
document_role: supporting
document_type: phase-plan
snapshot_id: capability-261002
---

# Phase Execution Plan

- Phase: 1 of 3, source/evidence foundation (later consumer/pricing phases consolidated under the shared snapshot contract).
- Branch/base: `design/catalog-data-only-261002` -> current main baseline `602b1720e`.
- PR boundary: pure data-only source ingestion and additive saved support contract; no active catalog/estimator switch or production shadow mode.
- Inputs: confirmed Requirements, accepted D1–D3, approved Design revision 2 (M1–M13), historical/current/upstream evidence reports.
- Deliverables: versioned source decoder, exact-scoped lookup and hashes, effort presence/derivation semantics, additive capability support descriptor, bounded injectable HTTP collector and deterministic tests.
- Non-goals: source authority activation, pricing evaluator, DB migration, projection rewiring, UI consumer changes or deployment. Regenerate ignored API artifacts as a compatibility check because the additive descriptor changes the API schema; phase 2 still owns behavioral consumer integration.
- Approved mechanisms: M1–M4/M6 foundation. Authorities: REQ-1–3/REQ-5/REQ-7, ADR-D1/D2; next phases own activation/removal.
- Design delta: None.
- Removal obligations: None active in this additive foundation. Remove temporary superseded design brief (already consolidated); preserve legacy runtime behavior until activation phase. No old LiteLLM tables, import or execution helper may be added.
- Absence verification: new module imports and tests prove no LiteLLM/genai executable authority or source-regex/name fallback; no production callsites activate collector.

| Workstream | Owner | Owned paths relative to backend src/azents | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Source records/decoder | `/root/hermes-metadata-research` | `core/model_catalog_source.py`, matching tests | Existing enum only; support descriptor provided by separate owner | Typed exact source records, presence, effort flags/defaults, hash, lookup and descriptive JSON evidence | Focused pytest, Ruff, ty |
| Saved support contract | `/root/openclaw-metadata-research` | `core/model_capability_contract.py`, its tests, `core/llm_catalog.py` and isolated additive tests | Existing capability types | Version2 semantic support descriptor and legacy absence decode, no new producer behavior | Focused pytest, Ruff, ty |
| Bounded collection/integration | `/root` | `services/catalog_source_collection.py`, its tests, plans and approved docs | Source decoder | Injected HTTP-only collector with source identity, byte/time/URL validation and hashes | Mock HTTP fixture suite and integrated module checks |

- Interfaces: source decoder must expose `CatalogSourcePayload` plus `decode_catalog_source(raw_bytes)` and exact provider/model lookup without regex/name heuristics. Collector metadata wraps raw/canonical digest, source URL/schema/interpreter revision and counts. Capability descriptor uses required nullable evidence fields and known/unknown/conditional state, valid effort subsets with completeness and separate structured-response semantics. Owner-specific helper names may vary but root must freeze exported integration names before consumers use them.
- Source pricing representation is ingestion evidence only here; full price-rule parser/evaluator belongs to phase 3. Unsupported price dimensions must remain detectable rather than silently be lost.
- Integration order: descriptor/source modules independently, root collector after source interface, integrated root validation, frozen whole-diff reviewer.
- Independent review: exactly `/root/catalog-metadata-reviewer`, requested by root only after stable diff and integrated checks.
- Final validation: configured Ruff/format/ty plus new pytest suites and existing core capability consumers; docs validator. Record actual environment and commands in Session. No database or provider network required for this phase.
- Scope-drift: no hidden alternate pricing authority, new runtime lookup, global library updater, source-mode toggle or activation. Additive contract fields are new producer semantics only once later projection wires them.
- Context checkpoint: after review record code/test interfaces, hashes/decoder revision, unknown behavior, environment evidence and phase PR before starting phase 2.
