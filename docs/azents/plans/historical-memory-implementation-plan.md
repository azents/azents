---
title: "Historical Memory Implementation Plan"
created: 2026-10-01
updated: 2026-10-01
tags: [memory, engine, vfs, frontend, testing]
---

# Historical Memory Implementation Plan

## Authority

- Requirements: [`memory-260930/REQ`](../requirements/memory-260930-passive-session-context.md)
- ADR: [`memory-260930/ADR`](../adr/memory-260930-passive-session-context.md)
- Approved Design: [`memory-260930/DESIGN`](../design/memory-260930-passive-session-context.md), revision `1`
- Approved authority IDs: `M1` through `M15`
- Design approval: 2026-10-01, Collaborative, requester
- Design delta: `None`

Plans decompose the approved Design and create no product or architecture authority.

## Delivery Shape

Use six stacked PRs. Every phase is based on the preceding phase, opens its PR
before later implementation starts, and uses title prefix:

```text
Historical Memory [n/6]: <phase>
```

The full stack is created before waiting on CI. Merge is not authorized by this
plan and requires explicit requester approval.

## Ownership and Review

- Primary owner/orchestrator: `/root`
- Independent read-only reviewer for every phase: `/root/historical-memory-reviewer`
- The reviewer reads the complete stable integrated phase diff only after root
  validation. It never edits files or creates implementation authority.
- Root owns integration, validation, finding resolution, re-review requests,
  branch/PR progression, Spec promotion, and plan cleanup.

## Stack

### Phase 1 — Persistence and domain foundation

- Branch: `feature/historical-memory-1-foundation`
- Base: `main`
- Mechanisms: `M1`, `M2`, `M4`, `M5`, `M6`, `M7`, `M14`, `M15`
- Deliverables:
  - approved Requirements/ADR/Design snapshot;
  - generated Historical Memory persistence migration and repository contracts;
  - Historical Memory model-operation kind and strict output types;
  - semantic source-event projection and declarative conversational-tool registry;
  - unit/repository tests for admission/result/retry state and projections.
- Excludes Scheduler dispatch, provider execution service, snapshots, VFS, API/UI,
  tool removal, Specs, and implementation markers.
- Removal obligations: None.

### Phase 2 — Preparation pipeline and boundary snapshots

- Branch: `feature/historical-memory-2-preparation`
- Base: Phase 1
- Mechanisms: `M1` through `M8`, `M14`, `M15`
- Deliverables:
  - five-minute Scheduler discovery and registered Job Runtime handler;
  - bounded Agent jobs, Lightweight model operation, prompt/input/output flow;
  - atomic result publication, retry/recovery, metrics;
  - Session Toolkit State snapshots at initial and post-compaction boundaries;
  - deterministic Saved/Historical selection and injected Memory block;
  - focused integration tests.
- Excludes VFS reads, public API/UI, old read-tool removal, Specs, and E2E.
- Removal obligations: replace per-turn dynamic Saved Memory selection only when
  boundary snapshots are active and equivalence tests pass.

### Phase 3 — Pluggable VFS read platform

- Branch: `feature/historical-memory-3-vfs-platform`
- Base: Phase 2
- Mechanisms: `M9`, `M11`, `M14`
- Deliverables:
  - mount backend registry, VFS read context, exact/directory/glob validators;
  - common read_text/grep/glob contracts and conformance suite;
  - immutable Skills backend and optional transfer bridge;
  - Runtime path adapter;
  - Runtime-independent readable-storage Toolkit owning `read`, `grep`, `glob`;
  - tool catalog/lowerer tests with and without Runtime.
- Excludes Memory backend/tree, read-tool removals, API/UI, Specs, and E2E.
- Removal obligations:
  - remove RuntimeToolkit ownership of `read`, `grep`, `glob` after the new Toolkit
    passes the same Runtime-path behavior tests;
  - replace static read routing through `AZENTS_VFS_SUPPORTED_MOUNTS` while
    preserving current Skills exact projection behavior.

### Phase 4 — Live Memory VFS and model-tool cutover

- Branch: `feature/historical-memory-4-memory-vfs`
- Base: Phase 3
- Mechanisms: `M6`, `M8`, `M9` through `M12`, `M14`
- Deliverables:
  - live PostgreSQL Memory VFS backend and accepted namespace;
  - Saved/Historical/source/event/tool-result renderers;
  - backend-native bounded glob/grep/read and current authority checks;
  - automatic snapshot paths and Memory README guidance;
  - final Saved-only mutation tool surface;
  - source lifecycle and privacy tests.
- Removal obligations:
  - remove `list_memories`, `get_memory`, `search_memories`;
  - remove `search_sessions`, `read_session_history`,
    `read_session_tool_result`;
  - remove obsolete model prompt/tool descriptions and tests;
  - retain repositories needed by the VFS backend rather than deleting canonical
    source access logic.
- Absence verification: tool catalog snapshot, source grep for removed factories
  and names, Runtime/VFS parity tests, and Memory-disabled behavior tests.

### Phase 5 — Historical settings and generated clients

- Branch: `feature/historical-memory-5-settings`
- Base: Phase 4
- Mechanisms: `M13`, `M14`
- Deliverables:
  - read-only Historical Memory public list/detail APIs;
  - exact Team/User authorization and non-enumerating errors;
  - regenerated Python and TypeScript public clients;
  - Saved/Historical settings UI with search and source links;
  - frontend/API tests and accessibility coverage.
- Removal obligations: replace the Saved-only settings content area with the
  approved Saved + Historical presentation while retaining Saved CRUD.

### Phase 6 — Integrated QA, Spec promotion, and plan cleanup

- Branch: `feature/historical-memory-6-qa-spec`
- Base: Phase 5
- Mechanisms: `M1` through `M15`
- Deliverables:
  - deterministic E2E matrix and focused reliability/security regression suite;
  - report-style load validation for discovery, Memory grep, snapshots, and
    background concurrency;
  - corrections required by validation and independent review;
  - Living Spec updates and generated documentation indexes through pre-commit;
  - Requirements/Design `implemented` date after verified completion;
  - removal of this implementation plan and all Historical Memory phase plans.
- Removal obligations: current Specs replace obsolete tool/prompt/VFS behavior;
  temporary plans are removed only after validation and Spec promotion.

## Cross-Phase Interfaces

- Phase 1 freezes repository/domain APIs consumed by Phase 2.
- Phase 2 exposes Historical source rows and Session snapshot records consumed by
  Phase 4; it does not depend on Memory VFS.
- Phase 3 freezes VFS backend/router/conformance contracts consumed by Phase 4.
- Phase 4 freezes public domain service/query contracts consumed by Phase 5.
- Phase 6 may fix defects within approved mechanisms. A material contract change
  returns to feature Design and invalidates approval.

## Validation Matrix

- Python formatting/lint/typecheck/tests for every affected backend subproject.
- TypeScript format/lint/typecheck/build for Phase 5 and final integration.
- Migration generation and schema assertions; no hand-written Alembic revision.
- Job Runtime/Scheduler/model-operation focused tests.
- Snapshot/compaction boundary and privacy integration tests.
- VFS backend conformance for Runtime, Skills, and Memory.
- Tool catalog absence tests after cutover.
- OpenAPI generation and client consistency.
- Deterministic testenv E2E for the Design matrix.
- Report-style bounded load validation in Phase 6.
- `/spec-review` immediately before final Spec promotion.

## Prerequisites and Fixtures

- Existing deterministic model proxy gains Historical Memory strict JSON cases.
- Test fixtures can set Session activity, active Run, archive/purge, Team/User
  membership, Agent model chain, client tool calls/results, and Scheduler trigger.
- No live provider credential is required for required CI.
- Live-provider validation is optional and non-gating.

## Removal and Absence Checkpoints

- Phase 2: per-turn dynamic selection no longer drives automatic context.
- Phase 3: exactly one `read`, `grep`, `glob` declaration each; RuntimeToolkit no
  longer owns them.
- Phase 4: six dedicated Memory/history read tools are absent without aliases.
- Phase 5: Historical UI is read-only; Saved CRUD still exists.
- Phase 6: old Specs and all temporary plans are absent; implemented snapshot is
  immutable.

## Rollout and Rollback

- Preparation Scheduler remains disabled until the cutover phase is ready.
- Schema and VFS infrastructure are additive before activation.
- Final activation enables rolling discovery and removes old read tools in the
  same tested stack boundary.
- Operational rollback disables discovery and Memory use while retaining rows.
- No live infrastructure mutation, merge, or deployment is performed by this
  implementation plan.

## Context Checkpoints

At every phase PR record:

- implemented mechanisms and authority;
- changed interfaces and migrations;
- focused and integrated validation;
- completed removals and absence evidence;
- reviewer findings and resolutions;
- remaining stack scope and risks;
- Design delta: `None`.

## Blockers

None at plan creation. Conditional feasibility items from the approved Design are
validation obligations, not blockers:

- Runtime-independent generic read ownership;
- PostgreSQL-backed bounded regex grep performance;
- representative Historical summary quality.
