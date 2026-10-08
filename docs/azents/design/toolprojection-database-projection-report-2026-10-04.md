---
title: "Tool Preparation Database Projection Measurement"
created: 2026-10-04
tags: [backend, performance, concurrency, testing]
document_role: supporting
document_type: supporting-verification
snapshot_id: toolprojection-261004
---

# Tool Preparation Database Projection Measurement

## Scope and Environment

This is a one-time local validation of the saved MCP snapshot database slice of model preparation, not a production latency or complete `prepare_model_call` benchmark. It excludes provider discovery/network, Runtime coordination, tool execution and the separately retained generic Engine ownership gate.

- Python 3.14.7; Linux x86_64, PostgreSQL 17 testcontainer, production SQLAlchemy read/write session factories, one process/engine/pool and one seeded fixture.
- Single empty saved MCP snapshot, exact same Agent/Session/state identity and payload for both paths.
- Baseline reconstructs the previous `OwnerBoundSessionManager` description read. It is a measurement-only control, not a supported fallback mode.
- Candidate uses an independent PostgreSQL read-only scope. Mutation manager remains owner-bound.
- Ten warm-up pairs followed by 200 samples per path, alternating sample order. No introduced writer contention. p95/p99 use nearest-rank sample percentiles; p50 is the median.
- `before_cursor_execute` captures statement and explicit `FOR UPDATE` counts without parameters, credentials or payload recording.

## Results

Owner-bound baseline: p50 **6.580 ms**, p95 **8.065 ms**, p99 **10.315 ms**; **1,600 SQL statements / 200 explicit FOR UPDATE statements** for 200 loads.

Read-only projection: p50 **1.194 ms**, p95 **1.617 ms**, p99 **2.097 ms**; **200 SQL statements / zero explicit FOR UPDATE statements** for 200 loads.

The observed reduction belongs only to this uncontended DB projection slice. Local scheduling, concurrency, transaction mode setup and pool conditions affect the sample. No full-call p95/p99 gain, deployment improvement, contention-retry reduction or production percentage is inferred.

## Structural Verification

A separate deterministic real-PostgreSQL test holds the actual execution root-tree lock in an independent write transaction, then requires execution-bound snapshot and GitHub selection reads to complete before that holder is released. It uses `asyncio.Event` ordering, not sleeps. Their write scopes remain owner-bound. Runtime/binding/worktree projection absence tests independently verify no actual reconciliation/admission or write-manager entry. These structural assertions are not derived from timing noise.

## Reproduction and Evidence

The temporary measurement ran from the backend subproject with:

```console
uv run pytest -q src/azents/toolprojection_benchmark_test.py
```

The measurement test passed and was removed from the deliverable after its one-time use. The reproduction harness initializes a fixture with the existing `_create_agent_and_session` helper, reads its actual owner generation, saves one snapshot, constructs baseline/candidate managers for the same store identity, performs alternating timed loads and collects SQL counts. Recreate those steps with the environment and sampling policy above; do not modify production factories to add a baseline mode.

Runtime evidence retained by the implementation owner includes the JSON result, pytest log and standalone reproduction harness. Harness SHA-256: `0e3da7f97507d0988ae1e0fe3bed5bfd747714a70d4029516205a0c81092a7ea`. The report contains the public-safe workload, environment, command, results and limitations; no private storage URL or deployed resource identifier is required.
