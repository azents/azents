---
title: "Agentic Historical Memory Phase 1: Shared Execution Core"
created: 2026-10-02
tags: [memory, engine, implementation, testing]
---

# Phase Execution Plan

- Phase: 1, shared execution-neutral model/tool core and foreground parity.
- Branch/base: `feat/memory-261002-1-shared-loop` → `main` at `602b1720e4cc707d4326113273fa7349b7bbbd0b`.
- PR boundary: approved snapshots/plans plus one common iteration orchestration, neutral stream and parallel tool primitives, foreground host adaptation, generic transient-host and parity tests.
- Inputs: [Requirements](../requirements/memory-261002-consolidated-history.md), [ADR](../adr/memory-261002-consolidated-history.md), [approved Design revision 2](../design/memory-261002-consolidated-history.md).
- Deliverables: foreground uses an execution-neutral prepare/model/admit/tool/termination loop. No fake Session, second copied model/tool algorithm or foreground transaction weakening. A transient test host proves no durable event identity is required by the common core.
- Non-goals: activating internal consolidation, new source/draft tables, VFS mutation, foreground snapshot replacement, deployment.
- Interfaces: typed neutral turn/termination outcomes; host-owned admission/persistence/lifecycle; core-owned stage ordering, turn limits, failure propagation and adapter closure. Existing provider lowerer/output dialect and foreground events remain unchanged.
- Approved Design mechanisms: M1; retain M2 host separation without activating its new domain consumer.
- Authority: REQ-8, ADR-D1/D2, current agent-execution-loop Spec and repository-owned transaction conventions.
- Design delta: **None**.
- Removal obligations: move the production foreground iteration orchestration into one common core; preserve foreground-specific repository operations behind its host. No duplicate retained production loop.
- Absence verification: search `AgentRunExecution.run` and generic core for duplicated turn loops; core contains no public Session/Run/Event types or DB imports.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
|---|---|---|---|---|---|
| Neutral iteration contracts/core | `/root` | `engine/events/iteration.py`, `iteration_stream.py`, `iteration_tools.py`, corresponding tests | Approved Design | Typed generic stage loop, stream normalization and parallel result/cancellation primitives | Deterministic stage/cancel/failure/limits/settlement tests |
| Foreground adapter | `/root` | `engine/events/execution.py`, existing execution tests | Core | Same admission, normalization, persistence and terminal semantics | Full existing execution suite and ownership/repository regressions |
| Approval/docs/Spec | `/root` | snapshot trio, feature/phase plan, flow Spec | Stable code | Truthful phase scope and approval | Catalog/unittest/whitespace |

- Integration order: neutral contracts → foreground adapter → neutral/transient tests → full foreground tests → whole-subproject lint/type checks → frozen diff → independent review → corrections/revalidation → commit/PR.
- Single independent reviewer: `/root/memory-implementation-reviewer`; root requests review only on a stable integrated diff with evidence.
- Final validation: root owns `uv` environment setup, focused/full pytest, Ruff, ty and documentation checks. Existing Engine semantics through supported lowerers remain covered; no provider-specific behavior is introduced.
- Scope-drift check: no new mode/authority/fallback, no Runtime startup or live operations, no independently cloned loop, no restoration of service-owned DB transactions.
- Context checkpoint: record branch/base/PR, concrete changed interfaces, reviewed SHA/diff, commands/results and remaining storage/internal/context phases here before advancing.

## Execution Checkpoint

The primary Agent completed integration and validation on the unchanged final code.

- Foreground now uses `ModelToolIterationCore`, `consume_iteration_stream` and
  `ParallelIterationTools`; no native stream or parallel-batch algorithm remains
  duplicated in its host. Public events and repository operations stay foreground-owned.
- Initial review found incomplete stream/tool extraction. Root corrected it and
  also preserved callback-before-cleanup and synchronous stream-factory cancellation.
- Final focused tests: **89 passed**.
- Final whole-backend tests: **7,231 passed, 3 skipped, 6 existing warnings**.
- Whole-backend Ruff lint, format check (1,884 files), and ty check: passed.
- Documentation catalog tests: **18 passed**; catalog/frontmatter/whitespace: passed.
- Single reviewer `/root/memory-implementation-reviewer`: initial complete review,
  targeted M1 correction review and final factory-edge review; no remaining findings.
- Final reviewed staged digest:
  `ec216b297126f260646e377759b0d140331063c65ea9dc457f060c2625eb106b`.
  This checkpoint adds evidence only after that review; implementation code is unchanged.
- Design delta: **None**. No consolidation activation, source/draft migration or
  foreground aggregate replacement is included in phase 1.
- Remaining scope: phases 2–5. Open this phase PR before creating the dependent
  storage/VFS branch. No first-phase CI wait or production action is required to proceed.
