---
title: "Historical Memory Bounded Load and Reliability Validation"
created: 2026-10-02
tags: [memory, testing, performance, vfs, scheduler]
document_role: supporting
document_type: supporting-validation-report
snapshot_id: memory-260930
---

# Historical Memory Bounded Load and Reliability Validation

## Purpose and Authority

This is one-time environment-sensitive evidence for the scale/reliability obligations
in [`memory-260930/DESIGN`](memory-260930-passive-session-context.md), revision 1,
M1–M15. It is not a recurring load suite, production SLO, capacity guarantee, or
new product threshold. Design delta: `None`.

The measurement ran on the Phase 6 working tree based on `e13215cc8` (Phase 5),
after the main refresh to `704e71323`. The owning code was the actual Historical
Memory repository, Memory VFS repository/backend, snapshot selector, and real
Local Job Runtime. No live service, production database, external credentials,
or provider was used. Final integrated correctness evidence is recorded separately
in the feature QA report; this report covers bounded load and capacity isolation.

## Environment

- Date: 2026-10-02 KST.
- Linux 6.8.0-139-generic, x86-64, glibc 2.41.
- Python 3.14.7; 8 visible CPUs; host-reported memory 32,859,256 KiB.
  These are observed host values, not reserved workload resources.
- PostgreSQL 17.11 disposable Docker test container using the backend fixture.
  Required assembled-product E2E uses its separate PostgreSQL 18 fixture.
- Alembic head: `459a4285993c`, extending `d29225579621` in one linear chain.
- SQLAlchemy async/psycopg sessions with the backend test fixture's outer rollback
  transaction and savepoint-backed operation transactions.
- No competing synthetic load was deliberately started. Other development tasks
  may share the Runtime; no dedicated hardware isolation is claimed.
- Seed rows were backend integration fixtures in a disposable database, not E2E
  scenario-side SQL writes. Product E2E creates state through public APIs.

## Corpus and Limits

- 10 Agents in 10 Workspaces, with one current member per Workspace.
- 1,000 active root Sessions: 100 per Agent, alternating Team and associated-User
  product modes. Each source has one semantic user event.
- 800 prepared, bounded summaries; 200 initially unprepared sources inside the
  rolling six-hour-to-ten-day admission window.
- 200 Saved Memory rows: 20 per Agent.
- Two additional exact client-tool results on one target Team source: one with
  1,048,576 bytes of synthetic text, one with 2,097,153 bytes exceeding the
  2 MiB exact-read boundary. No raw tool body is included in report output.
- Source activity is seven hours before the explicit repository sample time;
  prior completed source activity is eight hours before that sample time so
  retained summaries also exercise due refresh selection.
- Target Agent inventory: 100 roots and 80 prepared summaries (40 Team, 40 User).
- Discovery limit: 500 sources; due-Agent inventory limit: 25 Agents.
- Memory grep: root `azents://memory`, recursive, 200 searched-file slots,
  2 MiB candidate/scanned-byte budget, 20 matching-file slots, 10 lines/file,
  normal two-second backend deadline and isolated regex subprocess.
- Exact text read: first 10,000 decoded characters with the normal 2 MiB DB/body
  bound and two-second backend deadline.
- Snapshot competition probe: repository ceiling of 500 candidates for Team plus
  the associated User; the normal context service ceiling is 200. This corpus
  returns 80 candidates under either ceiling. Whole Historical blocks compete
  under 10,000 rendered bytes with lexical topic `Release decision`; the probe
  does not include Saved entries in its selector input.

The grep measurement excludes tool-result bodies. SQL-side CASE/octet guards,
exact-read scalar bounds, and body-free glob projections remain covered by the
regular PostgreSQL regression tests. This corpus contains no paired client call,
so broad grep needs five SELECTs including authorization; the separate ordinary
regression verifies exactly two event-candidate/pairing SELECTs when calls exist
across multiple sources.

## Commands and Method

The temporary harness was placed beside the backend repository tests solely to
consume their isolated database fixtures, then removed from the repository.
Its source and raw measurements are retained as Session validation artifacts,
not committed as a permanent executable load test:

- `historical-memory-load-harness.py` — exact one-time harness.
- `historical-memory-load-evidence.json` — raw latency, query-count, observations,
  environment, corpus, and EXPLAIN JSON.
- `historical-memory-load-run.log` — pytest invocation result.

Invocation from `python/apps/azents`:

```console
uv run pytest src/azents/repos/memory_vfs/phase6_load_validation_test.py -q
uv run pytest src/azents/services/historical_memory/concurrency_test.py -q
```

The load harness completed with `1 passed` in 16.96 seconds, including disposable
schema setup, corpus construction, samples, plans, and cleanup. Each steady-state
operation had three warm-ups and twelve timed samples. Durations use
`time.perf_counter()` and include application/database transaction overhead and,
for grep, subprocess work. SELECT counts use the SQLAlchemy cursor execution
hook. p50 is the sample median; p95 uses nearest-rank with twelve samples and
therefore equals the observed maximum. These small-sample values must not be
interpreted as a production percentile distribution.

Reproduction:

1. Use the recorded feature code/migration state and the backend PostgreSQL test
   fixture; do not point migration tests at a shared database.
2. Materialize the retained harness temporarily at the invocation path.
3. Recreate the recorded ten-Agent/1,000-root corpus using the existing
   `_create_agent`/`_create_source` backend fixture helpers. The harness supplies
   scoped member rows and initial source/result fixtures, then calls production
   repository and backend methods for every measured operation.
4. Run the exact commands above. The harness emits JSON under the current
   Session output folder; change only that artifact destination if needed.
5. Remove the temporary test file before normal whole-subproject checks or
   committing. Compare corpus/limits/versions before comparing latency.

## Results

Initial cold admission accepted all 200 previously unprepared eligible sources
in **25.46 ms**, below the configured 500-source batch bound. Subsequent admission
samples correctly accepted zero additional sources; they measure inventory
checking after admission, not repeated inserts of fresh rows.

| Operation | p50 ms | p95/max ms | SELECTs/sample | Observed result |
| --- | ---: | ---: | ---: | --- |
| Admission inventory after admission | 10.22 | 12.03 | 1 | 0 new admissions |
| Due-Agent inventory | 16.74 | 29.71 | 1 | 10 due Agents |
| Broad grep, literal `Release` | 78.85 | 89.16 | 5 | 161 searched, 20 matched, matching-file-limit truncation |
| Broad grep, regex `(Release|Saved)\s+\w+` | 84.22 | 104.40 | 5 | 161 searched, 20 matched, matching-file-limit truncation |
| Broad grep, no-match identifier | 79.74 | 91.05 | 5 | 161 searched, 0 matched, searched-file-limit truncation |
| Source event with adjacency | 6.13 | 11.31 | 4 | Authorized event plus previous-event link |
| 1 MiB exact tool-result character page | 12.47 | 18.99 | 2 | 10,000 characters, continuation/truncated true |
| Oversized exact tool-result rejection | 10.23 | 18.30 | 2 | No body returned |
| Team/User snapshot query plus whole-block selection | 19.19 | 21.09 | 1 | 80 candidates, 10 entries, both scopes retained |

The no-match grep truncation is deliberate: candidate omission by the deterministic
row/query byte allocation cannot be advertised as an exhaustive negative result.
The returned reason remains explicit. No sample hit the backend deadline.

## Query Plans

The raw artifact records `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` for the actual
captured due-Agent statement and two representative ID/summary inventory SQL
projections. The latter are scoped projection probes, not exact reproductions of
all VFS authorization/CASE clauses; the end-to-end measurements above execute
those production clauses.

- Actual due-Agent query: 10 output Agents, 1,000 eligible source rows,
  **156.739 ms** instrumented execution, 34,383 shared-hit blocks,
  zero shared-read/temp blocks. The plan uses active Agent-Session indexing,
  Historical primary-key lookups, Agent primary-key lookups, and the existing
  `ix_events_session_id` membership/visible-event checks. Grouping/sort is in
  memory. Its instrumented EXPLAIN duration is reported separately from the
  prepared query samples and is not substituted for their 16.74 ms median.
- Representative source ID inventory: 100 rows, **0.280 ms** execution,
  10 shared-hit blocks, `ix_agent_sessions_agent_active_last_user_input`
  Index Scan plus an in-memory ID sort; no reads or spill.
- Representative prepared-summary inventory: 80 rows, **0.691 ms** execution,
  340 shared-hit blocks, active Session index plus
  `historical_memory_sources_pkey` Nested Loop and in-memory sort; no reads/spill.

The fresh, rolled-back fixture has small/default statistics and estimate/actual
row differences. This experiment demonstrates bounded behavior at the recorded
corpus, not an asymptotic scan guarantee. Larger production inventories should
receive fresh planner/statistics and latency observation before claiming capacity;
this report does not authorize a new index, migration, or new SLO.

## Reserved Job Runtime Capacity

`services/historical_memory/concurrency_test.py` uses the real LocalJobRuntime and
application handler registry definitions. Only handler bodies are replaced with
explicit event barriers to make execution observable:

1. Submit one more Historical execution than its configured handler capacity
   (default 15) into the 16-slot process Runtime.
2. Await authoritative barriers proving all Historical slots are occupied.
3. Submit an ordinary registered Scheduler job while Historical work remains
   blocked; its succeeded outcome arrives before Historical release.
4. Assert the queued Historical job did not start prematurely, release the
   barrier, and await every successful outcome and Runtime shutdown.

The regression passed and verifies handler-cap acquisition occurs before global
capacity acquisition. It proves at least one non-memory slot remains available
under Historical backlog; it does not measure provider throughput or claim that
foreground processing uses this same Runtime pool. Synchronization uses events,
not sleeps or scheduler-yield timing assumptions.

## Findings and Limits

- Recorded inventory, grep, exact-read, snapshot, and reserved-capacity observations
  satisfy the bounded-validation objectives on this corpus.
- Matching and candidate omissions remain explicitly truncated; no-match results
  are not falsely advertised as exhaustive.
- Exact oversize bodies are denied before text reaches the application result.
- Initial failed harness execution assumed the fixture's hashed event ID would
  have a next neighbor. Canonical ordering places generated tool-result IDs
  before that event; the harness was corrected to verify its actual previous
  neighbor. No product code change was needed.
- No discovery/model throughput, live provider quality, cold disk performance,
  pathological production inventory distribution, or distributed fleet capacity
  claim follows from this single-host run.
- Temporary load code is absent from the final repository diff. Only this report,
  regular bounded capacity regression, and retained validation artifacts remain.
