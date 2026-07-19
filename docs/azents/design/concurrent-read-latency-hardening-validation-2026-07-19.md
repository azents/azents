---
title: "Concurrent Read Latency Hardening Validation"
created: 2026-07-19
tags: [backend, runtime, toolkit, performance, validation]
---

# Concurrent Read Latency Hardening Validation

## Scope

This report validates the implementation stack for `docs/azents/design/concurrent-read-latency-hardening.md` through the following branches:

1. `feature/concurrent-read-latency-runner`
2. `feature/concurrent-read-latency-appendix`
3. `feature/concurrent-read-latency-ownership-observability`
4. `feature/concurrent-read-latency-validation`

The validation covers Runner event-loop responsiveness, bounded filesystem execution, cooperative cancellation, appendix discovery and dedupe behavior, Session ownership, Runtime snapshot reuse, structured diagnostics, model-visible output parity, and current-spec drift.

## Environment

- Date: July 19, 2026
- Repository: `azents/azents`
- Python interpreter: CPython 3.14
- Runtime Runner test environment: local filesystem and deterministic threading barriers
- Backend test environment: fake Runtime operation client, fake FileStorage, async barriers, and structured log capture
- Docker-backed E2E: unavailable because the local environment has no Docker Unix socket

No external credentials, database migration, public test endpoint, or new fixture seed was required.

## Commands and Results

### Runtime Runner

```console
cd python/apps/azents-runtime-runner
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
```

Result after validation test refinement:

- Ruff: passed
- Format check: passed
- Pyright: 0 errors
- Pytest: 45 passed

### Backend Toolkit and Hooks

```console
cd python/apps/azents
uv run ruff check src/azents/engine/tools/builtin.py src/azents/engine/tools/builtin_agents.py src/azents/engine/tools/builtin_test.py src/azents/engine/tools/claude_rules.py src/azents/engine/tools/claude_rules_test.py src/azents/engine/hooks
uv run ruff format --check src/azents/engine/tools/builtin.py src/azents/engine/tools/builtin_agents.py src/azents/engine/tools/builtin_test.py src/azents/engine/tools/claude_rules.py src/azents/engine/tools/claude_rules_test.py src/azents/engine/hooks
uv run pyright
uv run pytest -q src/azents/engine/tools/builtin_test.py src/azents/engine/tools/claude_rules_test.py src/azents/engine/hooks
```

Result:

- Ruff: passed
- Format check: passed
- Pyright: 0 errors
- Pytest: 89 passed
- Existing dependency warnings: three `testcontainers` deprecation warnings

### Docker-backed Product-path E2E

```console
cd testenv/azents/e2e
uv run pytest -q src/tests/azents/public/test_runtime_exec_process_tools.py
```

Result: blocked during fixture setup before product code execution.

The Docker client attempted to connect to the local Unix socket and failed with `FileNotFoundError: [Errno 2] No such file or directory`, which surfaced as `docker.errors.DockerException: Error while fetching server API version`. This is the exact local-environment blocker anticipated by the implementation plan. GitHub CI remains the required Docker-backed execution environment.

## Deterministic Evidence

| Requirement | Evidence | Result |
|---|---|---|
| Blocked recursive scan does not block unrelated read | `test_blocked_file_list_does_not_block_unrelated_read` holds one recursive list filesystem worker and completes an unrelated read before releasing it | Passed |
| Filesystem worker concurrency is bounded | `test_file_operation_executor_never_exceeds_worker_bound` submits four blocked reads with `max_file_operation_workers=2`; maximum observed active workers is 2 and no task completes before release | Passed |
| Cancellation reaches blocking traversal | `test_cancelled_file_list_signals_blocking_traversal` verifies task cancellation sets the thread-safe traversal cancellation event | Passed |
| Existing file payloads remain compatible | Runtime Runner read/write/list/stat/grep tests compare existing final payloads, path behavior, ordering, and error codes | Passed |
| Parallel AGENTS.md reads singleflight internal I/O | `test_parallel_reads_singleflight_agents_appendix_io` holds the first candidate read and verifies one appendix result and one stat/read sequence | Passed |
| Missing AGENTS.md probes use bounded negative cache | `test_missing_agents_candidates_use_negative_cache_until_compaction` verifies repeated reads avoid duplicate stat work and compaction clears the cache | Passed |
| Claude root discovery uses bounded cache | `test_cached_discovery_and_pre_io_dedupe_avoid_repeat_rpcs` verifies root lists are reused and deduped paths skip stat/read work | Passed |
| Parallel Claude reads singleflight discovery/content I/O | `test_parallel_reads_singleflight_rule_discovery_and_content_io` verifies one list/stat/read sequence and one appendix result | Passed |
| Content remains fresh after dedupe reset | Existing AGENTS.md and Claude Rules compaction tests modify or rediscover content after reset without a content cache | Passed |
| Every FileStorage operation carries Session ownership | `test_file_storage_propagates_owner_and_reuses_runtime_snapshot` exercises get/stat/put/exists/list/list_dirs/grep/delete and observes the same Session owner on every Runner call | Passed |
| Root/subagent Runtime and Session identities remain distinct | `test_subagent_read_and_appendix_share_parent_runtime_with_child_owner` performs an actual visible read and AGENTS appendix: one parent Runtime lookup and three child-Session-owned Runner operations | Passed |
| Visible read and appendices share one Runtime snapshot | `test_read_and_agents_appendix_share_runtime_and_log_diagnostics` asserts one Runtime repository lookup across visible read plus AGENTS stat/read | Passed |
| Structured diagnostics expose phase counts without content | Backend log-capture tests assert visible tool duration/count and AGENTS/Claude duration, cache, dedupe, list/stat/read, discovered, and appended counts | Passed |
| Model-visible appendices preserve existing behavior | Existing ordering, raw frontmatter, caps, self-read exclusion, successful-read-only activation, failure isolation, and `<system-reminder>` rendering tests | Passed |

## Operation-count Evidence

The focused tests produce the following deterministic count transitions:

### AGENTS.md

For one successful root-level read with one existing `/workspace/agent/AGENTS.md`:

- visible `read` Runner operations: 1
- candidate paths: 1
- discovery cache hits: 0
- discovery cache misses: 1
- internal stat operations: 1
- internal read operations: 1
- appended paths: 1
- Runtime repository lookups across visible read and appendix: 1

For a repeated missing candidate within the negative-cache TTL:

- second stat operations: 0
- cache hits: 1

### Claude Rules

For the first Project read with one workspace rule and no Project rule directory:

- root list operations: 2
- discovered paths: 1
- discovery cache hits: 0
- discovery cache misses: 2
- internal stat operations: 1
- internal read operations: 1
- appended paths: 1

For the second read before cache expiry after the rule path is durably deduped:

- root list operations: 0
- discovered paths: 1
- discovery cache hits: 2
- discovery cache misses: 0
- dedupe-skipped paths: 1
- internal stat operations: 0
- internal read operations: 0
- appended paths: 0

## Failures Found and Fixes Applied

### Missing direct executor-bound regression

The implementation used a fixed `ThreadPoolExecutor` worker bound, but the original Runner tests proved responsiveness and cancellation without directly asserting the maximum active filesystem work count. Validation added `test_file_operation_executor_never_exceeds_worker_bound` and reran the full Runner suite.

### Runtime snapshot identity review finding

Independent code review found that the cached Runtime snapshot initially depended on the first `FileStorage` caller's `agent_id`. A subagent visible tool could call with the child Agent ID while appendix work used the parent Runtime Agent ID. The storage now binds `runtime_agent_id` at construction, so all visible and appendix calls reuse the intended parent Runtime while retaining the invoking child Session as `owner_session_id`. The regression test uses the actual visible read and appendix path.

No additional implementation defect was found within the validated scope after these fixes.

## Implementation-to-Design Comparison

| Design requirement | Implementation status | Evidence |
|---|---|---|
| Dedicated bounded filesystem executor | Implemented | Runner-owned `ThreadPoolExecutor`; direct bound test |
| Blocking filesystem work off asyncio loop | Implemented | File operation handlers use `_run_file_operation`; blocked-scan responsiveness test |
| Cooperative traversal cancellation | Implemented | Thread-safe cancellation event and cancellation test |
| Short-lived discovery-only caches | Implemented | AGENTS missing cache and Claude rule-path cache tests |
| No instruction content or match-result cache | Implemented | Content reads remain on append path; compaction/fresh-content tests |
| Same-Session appendix singleflight | Implemented | Per-toolkit locks and deterministic parallel tests |
| Persistent dedupe before content I/O | Implemented | Storage counters show zero repeated stat/read calls |
| Invoking Session ownership on visible/internal file RPCs | Implemented | Root and subagent operation-client spy tests |
| One ready Runtime snapshot per storage lifetime | Implemented | Repository spy asserts one lookup across visible read and appendix |
| Visible tool and appendix structured diagnostics | Implemented | Log-capture field and count assertions |
| Existing output and failure behavior | Implemented | Existing appendix and Runtime storage test suites pass |
| No in-flight retry against replacement generation | Implemented | Storage retains one immutable ID/generation snapshot and existing operation errors propagate |

## Current-spec Comparison

| Current spec area | Current statement | Implemented behavior | Drift / action |
|---|---|---|---|
| Toolkit: AGENTS.md loading | Fresh successful-read appendix, path dedupe, compaction reset, no prompt-time Runtime access | Preserved, with discovery negative cache and same-Session singleflight | Spec is correct but incomplete; add cache, pre-I/O dedupe, singleflight, ownership, and diagnostics |
| Toolkit: Claude Rules loading | Fresh rule content, deterministic roots/order, path dedupe, compaction reset, fail-open Runtime errors | Preserved, with root-path cache and same-Session singleflight | Spec is correct but incomplete; add root cache, pre-I/O dedupe, ownership, and diagnostics |
| Toolkit: Runtime file tools | Runtime-backed file tools are auto-bound | Storage is Runtime-Agent-bound, Session-owned, and shares one readiness snapshot per turn | Add explicit Runtime snapshot reuse and visible-tool diagnostics |
| Runtime Control: ordinary operation ownership | Session-scoped file operations use invoking Session ID; subagents use their own Session | Now true for visible tools and appendix-internal RPCs | Clarify appendix-internal ownership; no contradictory behavior remains |
| Runtime Control: Runner execution | Runner handles file operations with fair scheduling and operation diagnostics | Blocking filesystem sections use a dedicated bounded executor | Add non-blocking filesystem executor and cooperative cancellation contract |
| Runtime Control: diagnostics | Scheduler logs queue/execution timing and ownership | Filesystem executor separately logs queue wait, blocking execution, status, and worker bound | Add filesystem-specific diagnostic fields |

No current spec statement contradicts the implementation. The specs omit the newly validated performance, cache, ownership-detail, snapshot, and diagnostic contracts. These updates belong in the dedicated spec-promotion PR.

## E2E and CI Decision

The deterministic component matrix is complete and mandatory. The local Docker-backed product-path test could not start because Docker is unavailable. The validation PR must therefore require GitHub CI to execute the repository's Docker-capable checks before the stack is merged.

No optional/live test was skipped for credential reasons, and no product-only synchronization API or fixture was added.

## Validation Conclusion

The implementation satisfies the design acceptance criteria at the Runner, Runtime storage, and appendix hook boundaries. The only unavailable evidence is local Docker-backed product-path execution, with an exact environment blocker recorded. The stack is ready for spec promotion after CI confirms the Docker-capable environment.
