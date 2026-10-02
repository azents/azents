---
title: "Evidence-Backed Model Support Implementation Plan"
created: 2026-10-02
tags: [model-catalog, backend, engine, implementation]
document_role: supporting
document_type: implementation-plan
snapshot_id: capability-261002
---

# Implementation Plan

## Approved Baseline

- [Requirements](../requirements/capability-261002-evidence-backed-model-support.md).
- [ADR-D1–D3](../adr/capability-261002-evidence-backed-model-support.md).
- [Design revision 2](../design/capability-261002-evidence-backed-model-support.md), requester-approved on 2026-10-02 with exact authority IDs M1–M13; implementation explicitly requested.
- Design delta: None.
- Root owns integration, shared interfaces, validation and PR creation. The single independent reviewer for every integrated phase is `/root/catalog-metadata-reviewer`.
- Worktree: current session `azents-4`; first branch `design/catalog-data-only-261002`, based on `602b1720e4cc707d4326113273fa7349b7bbbd0b`.

## Delivery Shape

A sequential three-PR stack provides reviewable boundaries. The initial four-phase decomposition combined projection and pricing into one connection phase after confirming they share the same snapshot contract; no temporary dual-source adapter is added to split that dependency. Intermediate branches are implementation scaffolding, not separately deployable production shadow modes. Ship the complete stack as one replacement release after required validation. Do not merge or apply production resources from this task.

1. **Foundation:** pure versioned JSON source/evidence decoder, strict source collection and additive saved-capability semantics with deterministic tests. M1–M4/M6 foundation; no active source reader switch.
2. **Single-source connection:** fieldwise provider/source projection, listing-presence handling, native/Pydantic boundary alignment, save/API/UI consumers, typed Azents estimator, durable source/context/price capture, direct genai source/estimator/dependency removal and generated artifacts. M1–M10/M13; depends on phase 1.
3. **Cutover/verification:** SQL-only DB fence/migration, pointer/deletion integrity, one-release drain/recovery instructions, full E2E/QA/spec promotion and plan cleanup. M5/M9/M11–M13; depends on phase 2.

Every phase has a tracked execution plan before code work. Root freezes and validates each integrated diff, then requests the exact reviewer. Open each phase PR before the next phase begins. Create all stack PRs before waiting on CI. Changes discovered inside approved mechanisms remain local implementation details; new material behavior returns to design.

## Interfaces and Ownership

Phase-1 new pure source contract lives in `core/model_catalog_source.py`, with explicit source/provider/model keys, presence-aware descriptive facts, exact-source lookup, nonmodel exclusion, canonical hash and independent raw-document hash. It does not mutate installed library metadata or execute source regexes.

A versioned support descriptor in `core/model_capability_contract.py` and additive field on `core/llm_catalog.py` separates unknown/conditional/exact-derived facts from legacy effective boolean/list views. Missing descriptor means historical snapshot semantics, not an old source fallback. Source decoder and later projection translate into this descriptor; source-native execution fields never flow to model construction.

Source collection uses `services/catalog_source_collection.py` with injected HTTP client and new-source URL/config validation, but active publication switches only in phase 2 together with its source consumers and estimator. Pricing rules/estimator have an explicit typed boundary; no source provider-name heuristics or genai calculator use remains after phase 2. Phase-3 migration fences complete the final release writer contract, not a public runtime toggle.

Ownership for each phase is recorded in its execution plan. Agents never edit each other's assigned files concurrently. Source owner and descriptor owner coordinate through root before changing shared interfaces.

## Removal Obligations

- Phase 2: replace native Pydantic capability derivation, lossy provider-array intersections, sparse-default denial and strict/structured conflation; preserve actual Pydantic encoding profiles where used operationally.
- Phase 2 also removes direct genai dependency/import/fetch/match/evaluate/config/source selection; retain transitive counter extraction and inert historical provenance.
- Phase 3: retire old DB current authority without deleting catalogs or saved selections; reject old publishers/source writes and unsafe rollback; replace current Spec and obsolete authoritative test assumptions.
- Final cleanup: remove phase plans only after full QA/spec promotion; approved Requirements/ADR/Design remain. Do not change historical implemented snapshots or executed migrations.

Absence verification combines targeted repository/import/dependency scans, captured-source/price replay, native profile/updater poison tests and old-SQL-shape migration tests. Do not claim a zero-genai transitive dependency graph.

## Validation Matrix

Foundation: duplicate-key/shape/numeric validation, exact identity, source conflicts, absent/null/false/empty, noflags unknown, opt-in/out gate, complete arrays and contract-derived provenance, bounded HTTP response behavior, historical capability roundtrip.

Projection: ten-provider sparse/rich evidence cases and preserved pending-parity intent, full xhigh/max roundtrip, tools/schema/media/parameters distinct, saved selection nonmutation, generated OpenAPI clients/UI consumer checks.

Pricing: per-token units; explicit zero; inclusive cache/reasoning; TTL; threshold/tier/offpeak; missing specialized prices; valid native-charge precedence; immutable capture; transitive usage parser allowed while old price/updater entry points poisoned.

Cutover: seeded old-only DB/no-network upgrade, source absent allowed, old candidate reuse rejection, unchanged current pointer allowed, current-source/projection owner/schema guards, deferred FK deletion/cascade, attempts/generation races and old producer drain documented. E2E stored picker/save/controls/mock inference/cost, refresh-after-save nonmutation and stale/error states.

Root owns integrated Ruff/format/ty/pytest and relevant E2E evidence. Live provider credentials are optional supplemental testing, never a required fixture bypass. No production DB/cluster credentials are used to execute mutations.

## Context Checkpoints

At phase completion record stable SHA, changed interfaces, actual checks, review corrections, removal evidence, PR/base and next phase input. Preserve existing `e8a161aae`/`c22ea47ac` intent and tests on the other branch; do not cherry-pick rejected per-model web tables. Implementation and CI errors are tracked until resolved; ordinary CI pending is not a blocker.

## Rollout and External Boundaries

Final release requires old save/dispatch producers drained before version-2 projections are exposed, and no successful source prefetch. Initial costs/enrichment may be unavailable. DB fencing cannot revoke in-memory captures. Exact drain verification is a deployment prerequisite, not performed by this development task. A binary-only rollback is unsupported after migration; explicit restoration requires matching stopped writers/schema/data.

No PR merge, source publication to production, live migration or rollout is authorized by implementation request.
