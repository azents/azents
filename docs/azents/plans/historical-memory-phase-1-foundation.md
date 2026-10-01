---
title: "Historical Memory Phase 1: Persistence and Domain Foundation"
created: 2026-10-01
updated: 2026-10-01
tags: [memory, backend, database, engine, testing]
---

# Historical Memory Phase 1: Persistence and Domain Foundation

## Phase Execution Plan

- Phase: `1/6 — Persistence and domain foundation`
- Branch/base: `feature/historical-memory-1-foundation` → `main`
- PR boundary: approved snapshot documents plus durable Historical Memory source
  state, model-operation contracts, and semantic event projection, without
  scheduling or provider execution
- Inputs: confirmed `memory-260930/REQ`, accepted `memory-260930/ADR-D1` and
  `ADR-D3` through `ADR-D15`, approved `memory-260930/DESIGN` revision `1`
- Deliverables: generated migration, RDB/domain/repository contracts, model
  operation kind, strict summary output type, conversational-tool registry,
  source event projection, focused tests, and tracked plans
- Non-goals: Scheduler task, Job Runtime handler, provider call, snapshot
  selection, VFS router/backend, tool removal, public API/UI, E2E, Spec promotion,
  deployment, or merge
- Interfaces: `historical_memory_sources` row contract; repository create/admit,
  due/progress, publish and failure operations; `HISTORICAL_MEMORY` model
  operation kind; declarative conversational-tool projection; bounded semantic
  evidence records; strict `summary` decode
- Approved Design mechanisms: `M1`, `M2`, `M4`, `M5`, `M6`, `M7`, `M14`, `M15`
- Authority references: `memory-260930/REQ-1` through `REQ-4`, `REQ-6`,
  `REQ-8`, `REQ-10`; `ADR-D4`, `ADR-D6` through `ADR-D10`, `ADR-D15`;
  current Memory, Session, Context Compaction, Toolkit, and Periodic Execution
  Specs
- Design delta: `None`
- Removal obligations: None in Phase 1. Existing behavior remains authoritative
  until replacement phases activate it.
- Absence verification: no Scheduler registration, background handler,
  model-provider service, snapshot prompt, VFS Memory mount, public route/UI, or
  removed tool appears in this diff

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Approved authority and plans | `/root` | `docs/azents/{requirements,adr,design,plans}/memory-260930-*`, `docs/azents/plans/historical-memory-*` | Approved Design | Immutable-ready design baseline and execution plan | Snapshot validator, docs tests, diff check |
| Schema and model | `/root` | `python/apps/azents/db-schemas/rdb/migrations/versions/*historical_memory*`, `python/apps/azents/db-schemas/rdb/revision`, `python/apps/azents/src/azents/rdb/models/historical_memory.py`, model registration surfaces | Authority baseline | `historical_memory_sources` schema and constraints | Generated migration inspection, schema/model tests |
| Domain and repository | `/root` | `python/apps/azents/src/azents/core/historical_memory.py`, `python/apps/azents/src/azents/repos/historical_memory/**` | Schema/model | Typed source/progress/result records and atomic DB operations | Ruff, typecheck, focused repository tests |
| Model-operation contract | `/root` | `python/apps/azents/src/azents/core/model_operation.py`, model stream call-kind/error/testing contracts directly required by the new kind | Domain | Truthful Historical Memory operation and strict output type | Existing model-operation tests plus focused additions |
| Semantic source projection | `/root` | `python/apps/azents/src/azents/engine/events/conversational_tool_projection.py`, `python/apps/azents/src/azents/engine/events/historical_memory_projection.py`, focused fixtures/tests | Event types, domain contract | Declarative durable-name registry and bounded evidence tiers/rendering | Projection unit tests, legacy malformed fallback tests |

- Integration order: authority/plan → migration/model → domain/repository → model
  operation → semantic projection → integrated backend checks
- Independent review: `/root/historical-memory-reviewer`; `/root` requests review
  only after every Phase 1 workstream is complete, the integrated diff is stable,
  and final validation passes
- Final validation: root runs docs validation, `python -m unittest
  scripts.tests.test_gen_docs_index -q`, `git diff --check`, backend Ruff/format,
  configured typecheck, focused new tests, affected existing model/event/repository
  tests, and migration/schema assertions
- Scope-drift check: Phase 1 must cover only the listed foundations, must not
  activate behavior, and must not add a second source of truth, durable attempt
  ledger, new user setting, Main-model fallback, compatibility alias, or material
  mechanism outside `M1/M2/M4/M5/M6/M7/M14/M15`
- Context checkpoint: approved documents and plans are present; Phase 1 starts from
  main commit `ea5b080db`; remaining phases own execution, VFS, cutover, UI, E2E,
  Specs, implemented markers, and plan cleanup; conditional risks remain summary
  quality and later VFS query performance, neither of which is exercised here

## Completion Checkpoint

- Implemented behavior: durable source admission/result/progress state, strict
  Historical Memory model-operation and output contracts, declarative
  conversational-tool projection, and bounded redacted source evidence
- Changed interfaces: `historical_memory_sources`,
  `HistoricalMemoryRepository`, `ModelOperationKind.HISTORICAL_MEMORY`, and
  model-stream call kind `historical_memory`
- Authority and drift: `M1/M2/M4/M5/M6/M7/M14/M15` implemented for this phase;
  `Design delta: None`; no Scheduler, provider execution, snapshot, VFS,
  public API/UI, tool-removal, or Spec-promotion behavior activated
- Migration evidence: PostgreSQL 17 revision `459a4285993c` passed
  upgrade/downgrade/upgrade, schema index inspection, and Alembic model-parity
  check
- Integrated validation: backend Ruff and formatting passed; whole-subproject
  type checking passed; full backend suite passed with `6008 passed, 3 skipped`;
  documentation validation tests passed with `14` tests; generated OpenAPI
  remained unchanged; `git diff --check` passed
- Independent review: `/root/historical-memory-reviewer` reported three
  warnings about preparation reauthorization, publication authority locking,
  and provider-tool semantic evidence; all were corrected and the targeted
  re-review approved the stable diff with no remaining findings
- Remaining scope: Phases 2-6 own execution, snapshots, VFS, cutover, UI/E2E,
  final validation, Spec promotion, implemented markers, and plan cleanup
