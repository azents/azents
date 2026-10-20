---
title: "Agent Deletion Phase 3: Pipeline Verification"
created: 2026-10-20
tags: [agent, lifecycle, backend, frontend, testing]
---

# Phase Execution Plan

- Phase: 3 of 4, deterministic pipeline and ownership verification.
- Branch/base: `test/agent-deletion-pipeline` → `feat/agent-deletion-readonly` (#2361, `09289455486d30851e7c4e6bd6770e0b97be2546`).
- Inputs: [approved harbor-261020 Design revision 2](../design/harbor-261020-agent-deletion-lifecycle.md), phase-1 participant/catalog contracts and phase-2 read-only/failure projection. Phase-2 local validation and independent review passed; latest-SHA CI is tracked concurrently.
- Approved Design mechanisms: M6/M12, verifying M1–M5 and M8–M11 without extending them.
- Authority: harbor-261020/REQ-1 through REQ-6 and REQ-8/REQ-9; ADR-D1 through ADR-D4; current Agent deletion spec.
- Design delta: None.
- PR boundary: expand missing unit, PostgreSQL and component state coverage on stable production interfaces. Correct only implementation defects exposed within the approved contracts.
- Deliverables: explicit evidence for ordered stopping/replay/cancellation, stale-attempt and failure recovery, final transaction ownership/rollback, representative write/deletion races and UI read-only states.
- Non-goals: new product behavior, persistence, configuration, cleanup authority, retry policy or E2E branch matrices. Phase 4 owns representative actual-deletion E2E and final spec promotion.
- Interfaces: existing immutable registry/context/results, completed repository operations, canonical lifecycle row lock, public deletion projection and component props remain authoritative.
- Removal obligations: replace obsolete orchestration-only expectations if encountered; preserve useful existing tests instead of duplicating them. No production removal remains assigned to this phase.
- Absence verification: inspect modified tests for old call-list authority, timing sleeps, provider/model prerequisites, SQL mocks used as constraint evidence, and unrelated behavior.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Registry and coordinator | /root | `core/agent_deletion*_test.py`, `services/agent_deletion*test.py`, `services/agent_decommission_test.py` | Phase 1/2 contracts | Order, waits, short-circuit, cause, cancellation, replay and isolation matrices | Deterministic fake collaborators; Ruff/ty/pytest |
| Persistence and scope | /root | `repos/agent_decommission/**`, deletion finalizer/operations and mutation-guard test modules | Real migrated PostgreSQL fixtures | Latch/legacy/exact recovery, stale attempts, rollback, shared/foreign owner retention, both lock-race orders | Real PostgreSQL authoritative lock observation; no ordering sleeps |
| Public projection/admission | /root | Agent service/API and owning mutation repository test modules | Existing authorized operations | Safe batched visibility, write-family/final-attachment denial, native cleanup allowance | Focused service and DB tests, existing permissions regressions |
| Component behavior | /root | Colocated Agent/read-only stories and lifecycle cache tests | Stable phase-2 UI contract | Status text, inspection/navigation, disabled writes and stale-client state | CI-contract Storybook plays, node tests, lint/typecheck |
| Coverage checkpoint | /root | This plan and Session evidence | Integrated test results | Map existing/new tests to Design Test Strategy; record genuine gaps | Docs validation; exact reviewer and latest-SHA CI |

Integration order: audit existing test evidence against required matrix → coordinator/registry gaps → durable boundaries/races → UI/projection gaps → root-owned focused and full checks → freeze diff → independent review → root corrections → PR.

Independent reviewer: `/root/deletion-fix-review`, read-only and requested only by root after the integrated diff and validation are stable. Root performs all implementation and validation; no delegated test implementation.

Final validation: backend Ruff/format/ty and complete pytest; affected PostgreSQL/migration checks; web lint/typecheck/node tests and selected CI-contract component plays; documentation validator and hooks; phase-3 latest-SHA CI plus earlier stack status. Reuse unchanged phase-2 generation/build evidence unless production interfaces change.

Scope-drift check: every new test maps to the approved Test Strategy, covers observable behavior rather than a replacement implementation detail, and keeps native Session/Runtime/shared-owner authorities intact. Any new material mechanism returns to Design instead of being smuggled into tests.

Context checkpoint records existing and added coverage, exact commands/results, review findings, changed interfaces, remaining phase-4 work and E2E prerequisites before opening this phase PR.

## Integrated Coverage Checkpoint

No production interfaces or behavior changed. The diff adds 135 backend cases and three directory stories, and strengthens status-story assertions. Phase 2 (#2361, SHA `09289455486d30851e7c4e6bd6770e0b97be2546`) completed all CI jobs successfully.

| Approved boundary | Existing evidence retained | Added evidence |
| --- | --- | --- |
| Registry/catalog | Real installed FK ownership and unexpected incoming edge | Duplicate/missing/unknown/cyclic handlers or dependencies, non-FK ownership, malformed composite identity |
| Coordinator and waits | Per-job retry isolation and native Session archive ordering | All six positions reject cancellation/ownership/failure without running later effects; all wait reasons stop recovery; ordered replay, bounded retry timing and no post-completion write |
| Domain participants | Native channel/Runtime and Session retirement suites | File storage/receipt failure replay, already-acknowledged blob skip, partial avatar replay and exact deduplicated target evidence, Runtime preflight loss and final-ack gates |
| Database fencing/finalizer | Same-worker reclaim, current-generation acknowledgement, legacy latch recovery | Ten completed-operation fences under same-owner and changed-owner reclaim; native file cleanup with exact receipts and other-Agent preservation; all avatar context fields; foreign provenance; real late RESTRICT failure rolls Runtime deletion back; atomic completed tombstone/error clear and repeat finalization |
| Read-only admission/publication | Phase-2 deletion-first PostgreSQL race, Single App/shared Multi App, generic HTTP mapping and Session/native admission suites | Write-first PostgreSQL lock race; ten settings/avatar/admin/memory/Project/environment mutations; unchanged read access and permission precedence; one-query safe status batch; upload with/without preview and reviewed GitHub/Google final attachment after deletion |
| UI | Phase-2 control stories and stale query-cache tests | Truthful active/deleting/error copy; desktop/mobile Session directory controls, preserved tabs/pagination/links and archived inspection |

Root-owned focused validation passed: 146 backend tests initially, full-backend Ruff/format/ty, web lint/typecheck, 759 node tests and seven selected Storybook plays. The complete backend rerun passed with 13,484 passed, 3 skipped and 8 warnings in 350.38 seconds before the two review-correction cases below. No paid model/provider calls, wall-clock ordering sleeps, or E2E SQL writes were added.

The assigned reviewer found one missing required historical regression. Root added a real PostgreSQL native-finalizer scenario with a completed recreation operation and two terminal items belonging to the target and another Runtime. Fresh post-finalization reads assert unchanged complete item/operation projections, including IDs, failure details, status and counters, plus the other Agent/Runtime. The same scenario reinstalls the exact old RESTRICT/deferrable FK and proves it rejects deletion. Test-owned DDL is installed before fixture inserts (PostgreSQL rejects ALTER after deferred trigger events exist) and rolled back by the existing fixture. The full focused suite, including catalog verification after that DDL regression, passed with 148 tests; full-backend Ruff/format/ty also passed again. The same reviewer confirmed the sole finding resolved and no additional material findings on the final integrated correction. No production change was required.

Later prerequisite discovery: the private main development environment is currently `needs-analysis`; it was only inspected and was not changed or cloned. The repository's required E2E fixtures independently build/run the checked Docker product and provide the existing Admin scheduler execution endpoint, so phase 4 can use that supported credential-free boundary without repairing unrelated shared source data.
