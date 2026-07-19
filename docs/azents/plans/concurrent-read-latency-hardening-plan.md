---
title: "Concurrent Read Latency Hardening Implementation Plan"
created: 2026-07-19
tags: [backend, runtime, toolkit, performance, plan]
---

# Concurrent Read Latency Hardening Implementation Plan

## Source of Truth

- Design: `docs/azents/design/concurrent-read-latency-hardening.md`
- Current Toolkit behavior: `docs/azents/spec/domain/toolkit.md`
- Current Runner behavior: `docs/azents/spec/flow/agent-runtime-control.md`
- Existing decisions: ADR-0085, ADR-0088, and ADR-0102

## Feature Summary

Remove multi-Session `read` latency caused by synchronous Runner filesystem work and repeated read-result appendix RPCs. Preserve existing read output and instruction applicability while adding bounded filesystem offloading, Session-local discovery caches, same-Session singleflight, correct operation ownership, Runtime snapshot reuse, and structured phase diagnostics.

## Stack Shape

```text
main
← feature/concurrent-read-latency-design
← feature/concurrent-read-latency-plan
← feature/concurrent-read-latency-runner
← feature/concurrent-read-latency-appendix
← feature/concurrent-read-latency-ownership-observability
← feature/concurrent-read-latency-validation
← feature/concurrent-read-latency-spec
← feature/concurrent-read-latency-cleanup
```

## Phase 1 — Design

- Branch: `feature/concurrent-read-latency-design`
- Scope:
  - Record confirmed latency causes and preserved behavior.
  - Define executor, discovery cache, singleflight, ownership, and diagnostics boundaries.
  - Define test and rollout strategy.
- Runtime behavior change: none.

## Phase 2 — Implementation Plan

- Branch: `feature/concurrent-read-latency-plan`
- Scope:
  - Define implementation PR boundaries and dependencies.
  - Define deterministic validation matrix and fixture assessment.
  - Record spec impact and cleanup responsibilities.
- Runtime behavior change: none.

## Phase 3 — Non-blocking Runner File Operations

- Branch: `feature/concurrent-read-latency-runner`
- Depends on: implementation plan.
- Scope:
  - Add a Runner-owned bounded filesystem executor.
  - Move direct blocking filesystem sections for file read/write/stat/list/grep/delete/mkdir/move and bulk mutations off the asyncio event loop.
  - Add cooperative cancellation checks to recursive list and grep traversal.
  - Preserve operation payloads, error codes, path handling, ordering, and limits.
  - Add executor queue wait and blocking execution diagnostics at the Runner boundary.
- Tests:
  - Existing Runtime Runner operation suite.
  - Deterministic blocked-scan responsiveness test.
  - Executor bound and cancellation tests.
  - Read/list/grep payload parity tests.
- Boundary:
  - No server/toolkit appendix changes.
  - No Runner operation limit increase.
  - No protocol or deployment setting change.

## Phase 4 — Appendix Discovery and Dedupe

- Branch: `feature/concurrent-read-latency-appendix`
- Depends on: non-blocking Runner file operations.
- Scope:
  - Add Session-toolkit-local AGENTS.md existence/negative cache with bounded TTL.
  - Add Claude Rules root path-list cache with bounded TTL.
  - Keep content, parsed frontmatter, and rendered output uncached.
  - Add same-Session asyncio singleflight around dedupe load, candidate filtering, discovery, content reads, state update, and rendering.
  - Filter persistent dedupe paths before stat/read work.
  - Clear local discovery caches on Session compaction.
- Tests:
  - Parallel read dedupe race with deterministic barriers.
  - Negative-cache hit and expiry.
  - Claude root-list cache hit and expiry.
  - Pre-I/O dedupe assertions through fake storage counters.
  - Fresh-content and compaction reset assertions.
  - Existing appendix ordering/rendering/failure tests.
- Boundary:
  - No Toolkit State schema change.
  - No content cache.
  - No operation ownership or logging changes beyond counters needed by tests.

## Phase 5 — Session Ownership and Latency Diagnostics

- Branch: `feature/concurrent-read-latency-ownership-observability`
- Depends on: appendix discovery and dedupe.
- Scope:
  - Make `RuntimeRunnerFileStorage` receive explicit nullable `owner_session_id` and use it for every Runner operation.
  - Construct Runtime Toolkit storage with the invoking Runtime Session ID.
  - Lazily resolve and reuse one ready Runtime ID/generation snapshot per storage instance.
  - Add structured visible file-storage and appendix phase diagnostics.
  - Report internal list/stat/read counts, cache result, dedupe skips, and duration without raw content.
  - Update focused caller tests to prove root and subagent Session ownership.
- Tests:
  - Runtime operation client spy assertions for every FileStorage method.
  - One Runtime repository lookup across a visible read plus appendix calls.
  - Root/subagent owner propagation.
  - Structured diagnostic field assertions.
  - Existing Runtime storage error mapping.
- Boundary:
  - No retry against a replacement Runner generation inside an in-flight operation.
  - Agent-level storage callers continue to pass `None` explicitly.

## Phase 6 — Validation

- Branch: `feature/concurrent-read-latency-validation`
- Depends on: all implementation phases.
- Scope:
  - Run the deterministic matrix across Runtime Runner and backend Toolkit/storage boundaries.
  - Add or refine missing regression tests discovered during validation.
  - Record commands, environment, results, operation-count evidence, and implementation-to-design/spec comparison in `docs/azents/design/concurrent-read-latency-hardening-validation-2026-07-19.md`.
  - Run available Docker-backed Runtime E2E or record the exact environment blocker and rely on GitHub CI for the required environment.
- Required evidence:
  - blocked recursive scan versus unrelated read progress;
  - parallel same-Session read internal RPC counts;
  - absent instruction-root cache counts;
  - output parity for AGENTS.md and Claude Rules appendices;
  - owner Session IDs on internal operations;
  - executor queue/execution and hook duration diagnostic fields.

## Phase 7 — Spec Promotion

- Branch: `feature/concurrent-read-latency-spec`
- Depends on: successful validation.
- Scope:
  - Run `/spec-review` against changed code paths.
  - Update `docs/azents/spec/domain/toolkit.md` with discovery cache, singleflight, fresh-content, ownership, and diagnostics behavior.
  - Update `docs/azents/spec/flow/agent-runtime-control.md` with bounded non-blocking filesystem execution and appendix internal ownership.
  - Add changed code paths and update `last_verified_at`/`spec_version` as required.
  - Mark `docs/azents/design/concurrent-read-latency-hardening.md` implemented only after validation succeeds.
  - Confirm that no new ADR is required.
- Tests:
  - documentation pre-commit validation;
  - targeted implementation suites as a final drift check.

## Phase 8 — Cleanup

- Branch: `feature/concurrent-read-latency-cleanup`
- Depends on: spec promotion.
- Scope:
  - Remove `docs/azents/plans/concurrent-read-latency-hardening-plan.md`.
  - Remove only temporary plan references that no longer belong in current documentation.
  - Keep the implemented design, validation report, living specs, and code.
- Runtime behavior change: none.

## Dependency Summary

| Phase | Requires | Provides |
| --- | --- | --- |
| Runner | Plan | Responsive event loop and bounded blocking work |
| Appendix | Runner | Reduced discovery/RPC amplification and race-free dedupe |
| Ownership/diagnostics | Appendix | Correct scheduling attribution, Runtime reuse, production evidence |
| Validation | All implementation | Deterministic proof and drift findings |
| Spec | Validation | Current living behavior documentation |
| Cleanup | Spec | Removal of temporary plan document |

## E2E Primary Validation Matrix

| Behavior | Primary verification | Required result |
| --- | --- | --- |
| Runner responsiveness | Deterministic component test with blocked filesystem worker | Unrelated async operation progresses before blocked scan release |
| Filesystem worker bound | Component test with held worker tasks | Active blocking tasks never exceed the executor bound |
| Cooperative cancellation | Component test with recursive traversal barrier | Cancellation signal stops further traversal and no final success is emitted |
| Parallel same-Session reads | Backend hook test with concurrent tasks and storage counters | Each instruction path is read and appended once per dedupe lifecycle |
| Missing AGENTS.md | Backend hook test with fake time/counters | Repeated read within TTL performs no second stat for the absent path |
| Unchanged Claude rule roots | Backend hook test with fake time/counters | Repeated read within TTL performs no second recursive list |
| Fresh content | Backend hook test editing bytes between append lifecycles | Post-compaction appendix contains new bytes, not cached content |
| Session ownership | Runtime operation client spy and root/subagent integration tests | Every visible/internal file operation carries the invoking Session ID |
| Runtime lookup reuse | Repository spy across visible read and appendices | One ready Runtime lookup per FileStorage lifetime |
| Model-visible parity | Existing appendix and file operation tests | Ordering, caps, raw frontmatter, reminders, and failures are unchanged |
| Production diagnostics | Structured log tests | Phase duration and internal operation counts are present without content |

## Fixture and Prerequisite Support

No new testenv seed, external credential, public test endpoint, or database migration is required.

Existing test doubles need the following deterministic capabilities:

- block and release one filesystem task;
- expose active filesystem worker counts;
- count list/stat/get calls by path;
- advance a fake monotonic clock for TTL expiry;
- hold the first dedupe update while a second hook task starts;
- capture Runner operation ownership and structured log records.

Docker-backed Runtime E2E uses existing fixtures. If the local environment lacks a Docker socket, the validation report records the blocker and GitHub CI remains the mandatory product-path execution environment.

## Test Commands by Phase

### Runner

```console
cd python/apps/azents-runtime-runner
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
```

### Backend Toolkit and storage

```console
cd python/apps/azents
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q src/azents/engine/tools/builtin_test.py src/azents/engine/tools/claude_rules_test.py src/azents/engine/hooks
```

### Product-path E2E

```console
cd testenv/azents/e2e
uv run pytest -q src/tests/azents/public/test_runtime_exec_process_tools.py
```

The validation phase may add a more focused read appendix E2E path if the existing fixture exposes stable instruction files without adding product-only synchronization APIs.

## Spec Impact Candidates

- `docs/azents/spec/domain/toolkit.md`
- `docs/azents/spec/flow/agent-runtime-control.md`

No public API, generated client, protobuf, database schema, Helm value, or external integration contract is expected to change.

## Rollout and Cleanup Notes

- Deploy server and Runtime Runner images through the normal release path.
- Existing Runtime Runners receive the implementation after normal workload replacement/restart; no manual production mutation is part of this work.
- Compare read latency, internal RPC counts, owner distribution, cache hits, and executor timings after rollout.
- Do not tune Runner Session/Runtime concurrency upward to mask regressions.
- Remove this plan in the final cleanup PR after current specs are promoted.

## Blockers and Manual Actions

- No implementation blocker is known.
- Docker-backed E2E may be unavailable locally; GitHub CI is the required fallback environment.
- No credentials or manual production action are required.
