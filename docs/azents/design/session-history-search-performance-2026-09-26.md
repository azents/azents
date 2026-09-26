---
title: "Session History Direct Search Performance Validation"
created: 2026-09-26
tags: [memory, performance, validation]
document_role: supporting
document_type: supporting-validation-report
---

# Session History Direct Search Performance Validation

## Purpose and scope

Validate the direct canonical-event search selected in `memory-260925/ADR-D1` before releasing the Session-history lookup tools. This is a bounded **synthetic local** test, not a production-size or production-latency claim. The working code was uncommitted on base `fa9ea3c75`; rerun after the PR commit if search implementation changes.

## Environment and workload

- PostgreSQL 17 testcontainer; the project Alembic head schema and SQLAlchemy async repository path. Local Agent Runtime reported eight available processors; container CPU/memory limits were not independently pinned.
- One Workspace and Agent, 120 active Team root Sessions, 100 user-message events each (12,000 events), about 140 characters per message. One event in root 91 contains `synthetic-rare-marker`; the miss query is absent. No User Session, archived Session, binary attachment, or concurrent writer is included in this performance workload; functional tests cover authorization and event projection separately.
- For each query, three warmups followed by 12 consecutive timed repository calls. Results are in milliseconds; p95 uses the observed value at the 95th percentile rank of this small sample. The local loop measures end-to-end repository query latency, not model response time.

## Execution and observations

Run from `python/apps/azents`: `uv run pytest -q src/azents/repos/session_history/repository_benchmark_tmp_test.py`. The one-off test seeded a temporary PostgreSQL database, invoked `SessionHistoryRepository.search_roots` for a global hit and miss and `search_events` for a scoped hit, then ran an illustrative scoped `EXPLAIN (ANALYZE, BUFFERS)` query. Two local runs completed; the second added the plan observation. The one-off benchmark test is intentionally removed from the routine suite after this report.

- First run: global hit p50 18.67 / p95 19.95; global miss p50 20.34 / p95 25.58; scoped hit p50 1.10 / p95 1.25.
- Second run: global hit p50 **20.43** / p95 **21.20** (max 23.52, one root returned); global miss p50 **21.01** / p95 **24.06** (max 25.30, none returned); scoped hit p50 **1.13** / p95 **1.34** (max 1.37, one message returned).
- Illustrative scoped plain-text lookup plan: bitmap index scan on `ix_events_session_id` to locate 100 events, then bitmap heap scan and text predicate; PostgreSQL reported 0.126 ms execution time for this simplified SQL. This plan is **not** an `EXPLAIN` of the complete JSONPath/global correlated query; timed repository calls above are the evidence for those actual code paths.

## Limits and reproduction

The query scans text within the authorized Session set and has no text index. Local cache warmth, synthetic uniform short text, one Agent, 120 roots, no concurrent sessions, and unknown production size mean these numbers do **not** prove an operational latency target at larger scale. A previously available read-only database login failed authentication before any data query, so current production cardinality and production search latency are not verified. No production data or credentials were copied.

To reproduce, create a disposable PostgreSQL 17 testcontainer with current Alembic head, seed 120 Team roots under one Agent and 100 user-message events per root, place a unique term in root 91/event 58, and time 3 warmup + 12 calls each to `search_roots` (hit and miss) and `search_events` (scoped hit). Use the current repository code and record corpus size, query, timing distribution, plans, and hardware before asserting any release SLO. If the actual production-scale corpus fails a suitable latency target, revisit `ADR-D1` in a new snapshot rather than silently dropping old Sessions from search.
