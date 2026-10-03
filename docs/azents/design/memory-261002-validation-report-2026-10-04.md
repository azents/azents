---
title: "Agentic Historical Memory Verification and Capacity Report"
created: 2026-10-04
tags: [memory, validation, e2e, performance, security, backend]
document_role: supporting
document_type: supporting-validation-report
snapshot_id: memory-261002
---

# Agentic Historical Memory Verification and Capacity Report

## Scope and evidence identity

This supporting report records implementation verification of the approved
[memory-261002 Design revision 2](memory-261002-consolidated-history.md), M1–M15,
against [confirmed Requirements](../requirements/memory-261002-consolidated-history.md)
and the [accepted ADR](../adr/memory-261002-consolidated-history.md).
**Design delta: None.** This report creates no product or design authority.

The implementation stack is Phase 1 `972377431` (#2069), Phase 2 `d639f001c`
(#2085), Phase 3 `aa00517f5` (#2089), Phase 4 `d2cbc9703` (#2091), and the Phase 5
verification diff on `feat/memory-261002-5-verification`. The Phase 5 commit is the
commit introducing this report; the dependent PR and its CI identify the final
SHA without a self-referential tracked commit hash.

All evidence uses synthetic data and disposable local infrastructure. No merge,
deployment, production migration, live provider call or live handover was run.
Local verification is not evidence of deployed process quiescence or production
readiness. Final required CI belongs to each PR's final head SHA.

Environment: Linux x86_64 (`6.8.0-139-generic`, glibc 2.41), eight reported CPUs,
Python 3.14.7, `uv`, PostgreSQL 17 disposable testcontainers. No resource isolation,
production dataset, representative hardware or production cost model is claimed.
The manifests and canonical-update measurements use one Python process and real
repository transactions; capacity measurements use one and three independent
Python worker processes, one real Local Job Runtime per process. Product E2E uses
the ordinary application/PostgreSQL and deterministic provider proxy, without a
Runtime for Memory execution or external provider credentials.

## Validation matrix

Run backend commands from `python/apps/azents`, E2E commands from
`testenv/azents/e2e`, and documentation commands from the repository root:

```sh
uv run ruff check .
uv run ruff format --check .
uv run ty check --error-on-warning
uv run pytest -q
# E2E support boundary, Docker/listener-free:
uv run pytest -q src/support_tests
# Representative product journeys, with ordinary isolated E2E prerequisites:
uv run pytest -q src/tests/required/public/test_historical_memory.py
# Backend-only schema generation:
uv run python src/cli/dump_openapi.py
# Documentation:
python scripts/docs_catalog.py validate
git diff --check
```

Verified checkpoints before final review:

- Phase 3 complete backend: 7,406 passed, 3 skipped; Phase 4: 7,419 passed,
  3 skipped. Foreground regression remains in the complete backend suite.
- Phase 5 complete backend before adding the two finite-pass tests: 7,424 passed,
  3 skipped, 305.11 seconds. The final integrated matrix is recorded below.
- Product Historical Memory file: **2 passed**, 71.64 seconds; the retained legacy
  preparation journey separately passed in 274.68 seconds.
- Full E2E support suite: **327 passed**, 3.04 seconds; proxy-specific subset:
  **8 passed**. Backend, E2E and testenv Ruff/format/Ty passed.
- Context boundary/native continuation subset: **14 passed**, 5.61 seconds.
- Existing local capacity/configuration subset: **7 passed**, 3.95 seconds.
- One-time small/large manifest harness: **2 passed**, 11.92 seconds.
- Finite-pass and reverse-commit-order tests use actual PostgreSQL; they are small
  recurring regressions, not load tests.
- Public/admin OpenAPI dump succeeds with **no schema diff**, so generated clients
  require no change. The sampler route is testenv-only; no public aggregate CRUD
  or production activation mode was added.

The first versions of the additional tests exposed test-harness issues only:
a wrong VFS record field, an unscoped unit lookup, and incomplete foreign-key
cleanup of committed synthetic Sessions. They were corrected with typed entry
access, exact Agent filtering and the existing complete Session/Runtime cleanup
order. No product behavior was weakened to make these tests pass.

## Product journey and measured context growth

The genuine product journey creates Team and two personal source Sessions through
APIs, prepares canonical summaries with the ordinary Lightweight service and
runs three isolated consolidation chains through ordinary production services.
Each chain has 14 captured physical model requests: inventory/source/draft reads,
valid write, an intentional edit error with real tool feedback, successful edit,
exact coverage and normal completion. Publication is by the host's frozen-file
validation, never parsing final text as a replacement overview.

The captured requests/results prove no peer source/body/inventory hint, no
foreground 20k context in an internal unit, exact private tool schemas and no
Runtime callback. All three units publish; foreground composition, live aliases,
peer-source denial, archive/restore continuity and retained source lookup are
observable. The proxy also has support tests for continuation-chain isolation
and rejection of retired continuation state.

Measured compact JSON size of reconstructed logical `input` plus `instructions`
(in UTF-8, including serialized field syntax, excluding tool schemas):

| Unit | Requests | First input | Largest input | Final input |
|---|---:|---:|---:|---:|
| Team | 14 | 3,124 bytes | 13,430 bytes | 13,430 bytes |
| Personal A | 14 | 3,124 bytes | 13,450 bytes | 13,450 bytes |
| Personal B | 14 | 3,124 bytes | 13,450 bytes | 13,450 bytes |

Actual continuation delta JSON sizes range from 121 to 781 bytes. These are
fixture payload sizes, **not model token counts, billed usage or price**. Native
continuation reduces wire deltas but does not erase the cumulative logical-input
admission obligation. Physical retries are separately covered by provider
admission/budget tests, including native HTTP/WebSocket continuation. Missing
usage remains unknown, never zero; no production cost projection is made from
synthetic proxy usage.

## Complete-manifest measurements

Workload: one or 512 canonical sources, 32 historical influence identities per
source, eight inherited draft identities per source before admission, current
source generation 33. Older identities are synthetic metadata, not retained old
summary bodies. This intentionally stresses full historical influence rather
than only the current source-ID set. Setup is outside measurement.

| Measurement | 1 source / 32 identities | 512 sources / 16,384 identities |
|---|---:|---:|
| Inherited identities before union | 8 | 4,096 |
| Setup | 0.010 s | 7.414 s |
| Observe wall time | 13.420 ms | 83.200 ms |
| Mutation wall time | 19.932 ms | 246.470 ms |
| Publication wall time (after freeze) | 22.574 ms | 265.998 ms |
| Instrumented SQL total | 33.604 ms | 697.903 ms |
| Longest instrumented SQL statement | 1.078 ms | 161.916 ms |
| Observe SQL statements | 16 | 16 |
| Mutation SQL statements | 22 | 22 |
| Freeze + publication SQL statements | 41 | 41 |
| Complete-manifest checks during observe | 3 | 3 |
| Distinct-source shared-lock queries during observe | 2 | 2 |
| Framed compact output | 534 bytes | 534 bytes |

The benchmark asserts the resulting draft dependency count is exactly
`source_count * 32`. It does not page-limit or collapse different generations.
Statement instrumentation includes repository/savepoint operations; SQL time is
not the sum of the three displayed wall stages because freeze is measured in the
SQL total but outside the publication wall timer. This is one run per shape,
not p95/p99 or a throughput/SLO claim. Lock contention/deadline correctness is
covered by `manifest_deadline_test.py` with independent real transactions,
statement deadlines, all-or-none rollback and unconfirmed-authority rejection.
Observed times fit those local repository bounds; no claim is made for larger
manifests, production lock contention or growth without further measurement.

## Finite work, changes and replicas

`work_test.py` drives seven exact sources through four productive publications
with slice sizes **2, 2, 2, 1**. The finite upper bound survives each slice. A new
source arriving after claim remains pending and is delivered in the next pass;
a publication marks only its exact supplied work IDs.

`late_commit_test.py` uses independent actual PostgreSQL transactions. The lower
identity sequence remains uncommitted while higher-sequence work is committed,
delivered and published. The lower row commits afterward; it remains unpresented,
unpublished and pending despite being below the completed pass upper bound. The
next owner delivers it. This proves identity sequence is not treated as a commit
or coverage watermark.

A separate one-time canonical-change harness performs 32 genuine
`HistoricalMemoryRepository.publish_completed` updates (not synthetic generation
assignment), measures each operation, then retires obsolete pending metadata and
delivers only generation 33. All 33 exact work records remain represented; 32 are
superseded, one is eligible/delivered. The 32 updates took 167.101 ms total, with
7.037 ms maximum per update in this one run. Exact results are in the measurement
appendix. Content changes remain distinct from access-continuity invalidation.

Capacity measurement uses normal registered handler concurrency definitions but
replaces the model/domain work with explicitly blocked synthetic handlers. Every
child process reports its ready state before the parent releases any child; no
fixed sleep establishes ordering. Two extra Memory jobs queue per replica.

| Worker processes | Configured slots | Simultaneous preparation | Simultaneous consolidation | Ordinary completions while Memory blocked | Memory queued |
|---|---:|---:|---:|---:|---:|
| 1 | 16 | 12 | 2 | 2 | 2 |
| 3 | 48 | 36 | 6 | 6 | 6 |

After release all 16 Memory submissions per worker finish, active count is zero
and observed maxima remain preparation12/consolidation2. This verifies reserved
local capacity and replica multiplication, **not CPU/model/DB throughput**.
Checked-in Helm `server.worker.replicas` defaults to **1**. The local product
fixture has one devserver Worker; the measured three-process shape is a deliberate
capacity QA experiment, not evidence of three deployed replicas. At `R` workers,
configured Memory slots can be `14R` (consolidation `2R`) with ordinary reserve
`2R`. Exact-unit PostgreSQL ownership still gates duplicate consolidation claims;
that is independent of process capacity and tested with two real contenders.

## Authority, preservation and removal audit

| Mechanisms | Implemented evidence |
|---|---|
| M1 shared core | `engine/events/iteration.py` with foreground host; complete foreground regression and independent phase review |
| M2–M3 isolated principals/source versions | scoped inventories/reads/model captures; exact peer denial; source/grant/availability repository tests |
| M4–M5 VFS adapters and editable drafts | `vfs_mutation.py`, routed mutation tools; read-only capability rejection, exact patch/mutation/receipt tests; genuine E2E write/edit feedback |
| M6–M7 host publication and Lightweight | multi-turn host, no final-text publication, operation health/quota/exhaustion and provider dispatch admission tests |
| M8–M9 coverage, dependencies and ownership | exact work journal, complete manifest, frozen draft CAS, receipt replay, takeover/recovery, finite slices and reverse commit order |
| M10 denial | whole-unit removal, no contaminated draft reuse, purge independence, revoke/restore/grant recreation and clean regeneration tests |
| M11 limits/recovery | absolute deadline/heartbeat, request/tool/token reservations, no-progress/backoff, fenced cleanup, actual capacity and manifest evidence |
| M12–M13 boundary/live context | multilingual exact 10k/20k complete framing; empty peer; old selected manifest; newer live read without reselection; child/compaction hooks; native replay reset |
| M14–M15 handover/continuity | forward/rollback/reactivate repository/CLI tests; interrupted root/child reset; Saved preservation; old-code writes and unavailable-then-restored identity reconciliation |

Removal evidence:

- The common iteration core has two explicit hosts; internal execution never
  creates a fake foreground Session/Run or a copied inference loop.
- Automatic `_select_historical_entries`, ranking/dedup/packing and candidate-cap
  searches in backend source return no implementation. The old
  `services/historical_memory/snapshot.py` is deleted. Stage 1 event projection
  and per-source settings/VFS inspection are intentionally retained.
- Version-2 aggregate snapshots reject schema-1 bodies without compatibility
  interpretation; root preparation and coordinated reset own replacement.
- One generic mutation tool per name routes to Runtime or optional native VFS
  capabilities. Read-only backends have no throwing mutation placeholders.
  Foreground Skills/Memory stay read-only and preserve Skills import semantics.
- Capacity15 is replaced by preparation12/consolidation2 combined14 validation.
- E2E assertions/proxy, current Memory/Toolkit/execution/compaction/periodic/test
  Specs remove obsolete packing, no-integration and Runtime-exclusive claims.
- Saved CRUD, Stage 1, original-source lookup, public conversation events and
  immutable Skills remain intact. Public/admin schema dump has no change.
- No new public CRUD, activation mode, dual writer, Main fallback, Runtime
  fallback, retention source of truth, direct testenv DB write or live operation
  was introduced. Temporary feature plans are deleted only after validated Spec
  promotion; historical Requirements/ADR/Design remain as the authority snapshot.

## Reproduction and bounded limitations

For exact replay of the one-time measurements, create `/tmp/memory-phase5-validation`,
copy the Python blocks below into their indicated filenames, and execute from
`python/apps/azents` using the current feature checkout and its `uv` environment:

```sh
mkdir -p /tmp/memory-phase5-validation
uv run pytest -q -s -o asyncio_mode=auto /tmp/memory-phase5-validation/memory-phase5-benchmark_test.py
uv run python /tmp/memory-phase5-validation/memory-phase5-capacity-run.py
uv run pytest -q -s -o asyncio_mode=auto /tmp/memory-phase5-validation/memory-phase5-source-change_test.py
uv run pytest -q src/azents/repos/historical_memory_consolidation/work_test.py src/azents/repos/historical_memory_consolidation/late_commit_test.py src/azents/repos/historical_memory_consolidation/manifest_deadline_test.py src/azents/services/historical_memory/concurrency_test.py
```

Use only disposable testcontainer PostgreSQL through `azents.conftest`; never
point these synthetic helpers at production. The scripts are supporting report
recipes, not collected recurring tests. Product E2E prerequisites are prepared
through the normal testenv/fixture path and tests create state through product
APIs/services. New load evidence is needed for production-size corpora, more
replicas, real provider latency/cost or deployment-specific lock contention.

## Final integrated validation and independent review

Initial pre-review root-owned backend matrix: **7,426 passed, 3 skipped** in
303.71 seconds, with six dependency/deprecation warnings. Initial whole-backend
Ruff/format/Ty passed. Finite-pass/reverse-commit-order subset: **2 passed**, 3.95
seconds. Testenv substrate: **131 passed**, 4.47 seconds, with Ruff/format/Ty passing.

The initial independent review found that stored-response reset alone did not
bind opaque native state to its original automatic Memory selection. The owner
corrected this derived M12/M15 gap by atomically carrying already authorized
unit/revision identities alongside unchanged visible text, binding native
compatibility to each prepared instruction prefix plus those exact identities,
and stamping the corresponding request-local output normalizer across all native
families. Stored-response continuation also compares this binding. Neither hash
nor identity is access authority or extra model-visible Historical framing.
Durable Events and ordinary canonical history remain intact. Same-byte clean
publication after an unobserved denial/restore resets opaque replay; old/unbound
artifacts fail native compatibility even in a fresh adapter.

The corrective native/authority matrix is **77 passed** in 6.94 seconds: Responses
OpenAI/ChatGPT plus PydanticAI Gemini/Vertex/Anthropic/Bedrock, both durable and
transient envelopes, unchanged/changed/denied/new-revision/unbound cases, exact
tool pairs, fresh-adapter decoding, real PostgreSQL unobserved revoke/restore and
same-byte replacement, and public Google/Vertex SDK wire serialization using only
MockTransport and synthetic credentials. Supported Google SDK manual-history
signature handling is the SDK's documented mechanism, not application-invented
private state. The tests inspect actual wire absence of old opaque signatures and
server-only identities. Corrective whole-backend Ruff/format/Ty pass.

Shared provider/preparation interfaces changed, so root repeated the complete
matrix after correction. Final corrective backend: **7,493 passed, 3 skipped**,
321.00 seconds, six existing dependency/deprecation/synthetic-key warnings;
Ruff/format/Ty passed. Corrected output/native/SDK/authority focused matrix:
**125 passed**, 7.45 seconds. Product Historical Memory E2E: **2 passed**, 77.15
seconds; support suite: **327 passed**, 2.73 seconds; testenv substrate:
**131 passed**, 3.77 seconds, all corresponding static checks passing. Public/admin
OpenAPI dump has no spec diff. Documentation catalog/whitespace validation passes.

An earlier concurrent full run had no completion summary and was not counted.
The first complete solo rerun passed 7,492 tests with one old standalone native
fixture failure: it correctly could not replay an unbound artifact. The owner
made that intentional unchanged-fidelity fixture bind to a real prepared origin,
retained its opaque-delta privacy assertions, and reran the entire suite to the
7,493-pass final result above. Product code did not change after the corrected
product E2E. DB-only manifest/source-change and synthetic blocking-handler
capacity measurements are unchanged by the replay refinement. No production or
live provider operation occurred.

The complete stable Phase 5 diff is submitted to the feature's single read-only
reviewer `/root/memory-implementation-reviewer`. Review findings/corrections and
final-SHA required CI are delivery evidence in the phase PR and Session review
record, not fabricated by this local validation report. No intermediate successful
suite represents CI at an unverified final SHA.

## Measurement data appendix

### memory-phase5-manifest-measurements.jsonl

```json
{"complete_manifest_checks": 3, "cpu_count": 8, "distinct_shared_lock_queries": 2, "freeze_and_publication_queries": 41, "inherited_before": 8, "manifest_identities": 32, "measured_sql_max_ms": 1.078, "measured_sql_total_ms": 33.604, "mutate_ms": 19.932, "mutate_queries": 22, "observe_ms": 13.42, "observe_queries": 16, "platform": "Linux-6.8.0-139-generic-x86_64-with-glibc2.41", "postgres": "17 disposable testcontainer", "publish_ms": 22.574, "python": "3.14.7", "rendered_bytes": 534, "revision_id": "01a103414e0577b89f5f7fa672a6c3ad", "setup_seconds": 0.01, "source_count": 1, "topology": "one process, database-only repository operations; synthetic older generation metadata, no old bodies"}
{"complete_manifest_checks": 3, "cpu_count": 8, "distinct_shared_lock_queries": 2, "freeze_and_publication_queries": 41, "inherited_before": 4096, "manifest_identities": 16384, "measured_sql_max_ms": 161.916, "measured_sql_total_ms": 697.903, "mutate_ms": 246.47, "mutate_queries": 22, "observe_ms": 83.2, "observe_queries": 16, "platform": "Linux-6.8.0-139-generic-x86_64-with-glibc2.41", "postgres": "17 disposable testcontainer", "publish_ms": 265.998, "python": "3.14.7", "rendered_bytes": 534, "revision_id": "01a10341b2b376d78ebdf83858019614", "setup_seconds": 7.414, "source_count": 512, "topology": "one process, database-only repository operations; synthetic older generation metadata, no old bodies"}
```

### memory-phase5-capacity-measurements.json

```json
[
  {
    "replicas": 1,
    "topology": "independent Python worker processes; one LocalJobRuntime per process; synthetic blocking handlers, no model/network/DB work",
    "configured_slots": 16,
    "simultaneously_active_preparation": 12,
    "simultaneously_active_consolidation": 2,
    "ordinary_completed_while_blocked": 2,
    "queued_memory": 2,
    "readiness": [
      {
        "pid": 20892,
        "active": {
          "preparation": 12,
          "consolidation": 2
        },
        "ordinary_completed_while_memory_blocked": 2,
        "queued_memory": 2,
        "ready_ms": 0.652
      }
    ],
    "completion": [
      {
        "pid": 20892,
        "maxima": {
          "preparation": 12,
          "consolidation": 2
        },
        "memory_completed": 16,
        "active_after_close": 0
      }
    ],
    "cpu_count": 8,
    "python": "3.14.7",
    "platform": "Linux-6.8.0-139-generic-x86_64-with-glibc2.41"
  },
  {
    "replicas": 3,
    "topology": "independent Python worker processes; one LocalJobRuntime per process; synthetic blocking handlers, no model/network/DB work",
    "configured_slots": 48,
    "simultaneously_active_preparation": 36,
    "simultaneously_active_consolidation": 6,
    "ordinary_completed_while_blocked": 6,
    "queued_memory": 6,
    "readiness": [
      {
        "pid": 20897,
        "active": {
          "preparation": 12,
          "consolidation": 2
        },
        "ordinary_completed_while_memory_blocked": 2,
        "queued_memory": 2,
        "ready_ms": 0.606
      },
      {
        "pid": 20898,
        "active": {
          "preparation": 12,
          "consolidation": 2
        },
        "ordinary_completed_while_memory_blocked": 2,
        "queued_memory": 2,
        "ready_ms": 0.674
      },
      {
        "pid": 20899,
        "active": {
          "preparation": 12,
          "consolidation": 2
        },
        "ordinary_completed_while_memory_blocked": 2,
        "queued_memory": 2,
        "ready_ms": 0.637
      }
    ],
    "completion": [
      {
        "pid": 20897,
        "maxima": {
          "preparation": 12,
          "consolidation": 2
        },
        "memory_completed": 16,
        "active_after_close": 0
      },
      {
        "pid": 20898,
        "maxima": {
          "preparation": 12,
          "consolidation": 2
        },
        "memory_completed": 16,
        "active_after_close": 0
      },
      {
        "pid": 20899,
        "maxima": {
          "preparation": 12,
          "consolidation": 2
        },
        "memory_completed": 16,
        "active_after_close": 0
      }
    ],
    "cpu_count": 8,
    "python": "3.14.7",
    "platform": "Linux-6.8.0-139-generic-x86_64-with-glibc2.41"
  }
]
```

### memory-phase5-source-change-measurements.json

```json
{
  "real_canonical_updates": 32,
  "final_generation": 33,
  "total_exact_work": 33,
  "superseded": 32,
  "eligible_delivered": 1,
  "update_ms": [
    5.904,
    6.538,
    6.488,
    7.037,
    6.407,
    5.811,
    5.38,
    5.278,
    5.438,
    5.614,
    6.574,
    5.394,
    4.68,
    4.377,
    5.011,
    5.178,
    4.777,
    4.697,
    4.51,
    4.487,
    4.753,
    4.952,
    5.316,
    4.651,
    4.845,
    4.485,
    4.414,
    4.448,
    5.484,
    5.305,
    4.474,
    4.394
  ],
  "update_total_ms": 167.101,
  "update_max_ms": 7.037,
  "topology": "one process, ordinary repository publication, disposable PostgreSQL 17"
}
```

### memory-phase5-model-context-measurements.json

```json
[
  {
    "chain": "4e8f26e2982ec6bce0851ed0c45fd480",
    "requests": 14,
    "logical_context_utf8_bytes": [
      3124,
      3813,
      4380,
      4962,
      5875,
      6936,
      7527,
      8703,
      9806,
      10347,
      10987,
      11593,
      12346,
      13430
    ],
    "physical_input_json_bytes": [
      121,
      377,
      261,
      267,
      560,
      156,
      269,
      259,
      777,
      162,
      250,
      275,
      257,
      776
    ],
    "first_model": "gpt-5.5"
  },
  {
    "chain": "a0a5af4f3a33c00b22d49418d925b3ca",
    "requests": 14,
    "logical_context_utf8_bytes": [
      3124,
      3813,
      4380,
      4962,
      5879,
      6944,
      7535,
      8715,
      9822,
      10363,
      11003,
      11609,
      12362,
      13450
    ],
    "physical_input_json_bytes": [
      121,
      377,
      261,
      267,
      564,
      156,
      269,
      259,
      781,
      162,
      250,
      275,
      257,
      780
    ],
    "first_model": "gpt-5.5"
  },
  {
    "chain": "1f5eead6743e30a502860a3350b00ac7",
    "requests": 14,
    "logical_context_utf8_bytes": [
      3124,
      3813,
      4380,
      4962,
      5879,
      6944,
      7535,
      8715,
      9822,
      10363,
      11003,
      11609,
      12362,
      13450
    ],
    "physical_input_json_bytes": [
      121,
      377,
      261,
      267,
      564,
      156,
      269,
      259,
      781,
      162,
      250,
      275,
      257,
      780
    ],
    "first_model": "gpt-5.5"
  }
]
```

## One-time reproduction recipes

These scripts are reproduced as report evidence only and are not a recurring
load-test suite. Copy each block to the indicated temporary filename.

### memory-phase5-benchmark_test.py

```python
"""One-time disposable manifest measurements; results, not a recurring load suite."""
import datetime
import json
import logging
import os
import platform
import time
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from uuid6 import uuid7

from azents.rdb.session import SessionManager
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import RDBConsolidationDraft, RDBConsolidationDraftDependency, RDBConsolidationEvidence
from azents.repos.historical_memory_consolidation.ownership import ConsolidationOwnershipRepository
from azents.repos.historical_memory_consolidation.drafts import ConsolidationDraftRepository, DraftFileChange
from azents.repos.historical_memory_consolidation.publication import ConsolidationPublicationRepository
from azents.core.historical_memory_publication import validate_consolidation_overview
from azents.testing.consolidation import seed_consolidation_corpus, create_consolidation_source

pytest_plugins = ['azents.conftest']
RESULT = Path('/tmp/memory-phase5-validation/memory-phase5-manifest-measurements.jsonl')

@pytest.mark.parametrize('source_count', [1, 512])
async def test_manifest_measurement(rdb_engine: AsyncEngine, rdb_session_manager: SessionManager[AsyncSession], source_count: int) -> None:
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    claim = await ConsolidationOwnershipRepository(manager).claim(corpus.team)
    assert claim is not None
    drafts = ConsolidationDraftRepository(manager)
    await drafts.observe(claim.principal, path='summary.md')
    setup_start = time.perf_counter()
    async with manager() as session:
        draft = await session.scalar(sa.select(RDBConsolidationDraft))
        assert draft is not None
        source_ids = [corpus.team_source]
        for index in range(source_count - 1):
            source_ids.append(await create_consolidation_source(session, manager=manager, key=corpus.team, summary='Synthetic current canonical source', title=f'Synthetic manifest source {index}'))
        await session.execute(sa.update(RDBHistoricalMemorySource).where(RDBHistoricalMemorySource.source_session_id.in_(source_ids)).values(summary_generation=33))
        evidence = []
        inherited = []
        for source_id in source_ids:
            for generation in range(1, 33):
                item = dict(source_session_id=source_id, summary_generation=generation, evidence_hash='a' * 64, availability_generation=1, membership_grant_id=None)
                evidence.append(dict(id=uuid7().hex, attempt_id=claim.principal.attempt_id, **item))
                if generation <= 8:
                    inherited.append(dict(id=uuid7().hex, draft_id=draft.id, **item))
        await session.execute(sa.insert(RDBConsolidationEvidence), evidence)
        await session.execute(sa.insert(RDBConsolidationDraftDependency), inherited)
    setup_seconds = time.perf_counter() - setup_start
    await ConsolidationOwnershipRepository(manager).renew(claim.principal)
    statements: list[str] = []
    timings: list[float] = []
    starts: list[float] = []
    def before(_conn, _cursor, statement, _parameters, _context, _many):
        starts.append(time.perf_counter())
        statements.append(statement)
    def after(_conn, _cursor, _statement, _parameters, _context, _many):
        timings.append(time.perf_counter() - starts.pop())
    event.listen(rdb_engine.sync_engine, 'before_cursor_execute', before)
    event.listen(rdb_engine.sync_engine, 'after_cursor_execute', after)
    try:
        begin = time.perf_counter()
        observed = await drafts.observe(claim.principal, path='summary.md')
        observe_ms = (time.perf_counter() - begin) * 1000
        observe_queries = len(statements)
        manifest_checks = sum('complete_draft_influence' in s for s in statements)
        shared_lock_queries = sum('FOR SHARE NOWAIT' in s and 'SELECT DISTINCT' in s for s in statements)
        statements.clear()
        markdown = f'## Historical Context\nSynthetic bounded context.\n\n## Source Routes\n- azents://memory/historical/team/{corpus.team_source}/summary.md — Synthetic evidence\n'
        begin = time.perf_counter()
        await drafts.mutate(claim.principal, tool_call_id='benchmark-author', request_digest='b' * 64, expected_draft_revision_id=observed.draft_revision_id, expected_observation_epoch=observed.observation_epoch, changes=[DraftFileChange('summary.md', observed.file_revision_id, markdown)])
        mutate_ms = (time.perf_counter() - begin) * 1000
        mutate_queries = len(statements)
        statements.clear()
        pub = ConsolidationPublicationRepository(manager)
        frozen = await pub.freeze(claim.principal)
        begin = time.perf_counter()
        published = await pub.publish(claim.principal, expected_draft_revision_id=frozen.revision_id, expected_observation_epoch=frozen.observation_epoch, overview=validate_consolidation_overview(key=corpus.team, markdown=markdown))
        publish_ms = (time.perf_counter() - begin) * 1000
        publication_queries = len(statements)
    finally:
        event.remove(rdb_engine.sync_engine, 'before_cursor_execute', before)
        event.remove(rdb_engine.sync_engine, 'after_cursor_execute', after)
    async with manager() as session:
        count = await session.scalar(sa.select(sa.func.count()).select_from(RDBConsolidationDraftDependency))
    assert count == source_count * 32
    assert manifest_checks == 3 and shared_lock_queries == 2
    row = dict(source_count=source_count, manifest_identities=source_count * 32, inherited_before=source_count * 8, setup_seconds=round(setup_seconds,3), observe_ms=round(observe_ms,3), observe_queries=observe_queries, complete_manifest_checks=manifest_checks, distinct_shared_lock_queries=shared_lock_queries, mutate_ms=round(mutate_ms,3), mutate_queries=mutate_queries, publish_ms=round(publish_ms,3), freeze_and_publication_queries=publication_queries, measured_sql_total_ms=round(sum(timings)*1000,3), measured_sql_max_ms=round(max(timings)*1000,3), rendered_bytes=len(validate_consolidation_overview(key=corpus.team, markdown=markdown).rendered_block.encode()), revision_id=published.revision_id, python=platform.python_version(), cpu_count=os.cpu_count(), platform=platform.platform(), postgres='17 disposable testcontainer', topology='one process, database-only repository operations; synthetic older generation metadata, no old bodies')
    with RESULT.open('a') as stream:
        stream.write(json.dumps(row, sort_keys=True) + '\n')
    print(json.dumps(row, sort_keys=True))
```

### memory-phase5-capacity-worker.py

```python
"""One-time synchronized per-process capacity evidence, not throughput measurement."""
import asyncio
import dataclasses
import datetime
import json
import os
import sys
import time
from azcommon import di
from azents.job_runtime.local import LocalJobRuntime
from azents.job_runtime.registry import get_job_handler_registry
from azents.job_runtime.types import JobHandlerRegistry, JobRequest, JobOutcomeStatus
from azents.scheduler.executor import SCHEDULER_JOB_HANDLER_KEY
from azents.services.historical_memory.constants import HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY
from azents.services.historical_memory.job import HISTORICAL_MEMORY_PREPARE_HANDLER_KEY

async def main():
    release = asyncio.Event()
    ready = asyncio.Event()
    active = {'preparation': 0, 'consolidation': 0}
    maxima = dict(active)
    ordinary_completed = 0
    async def memory(kind):
        active[kind] += 1
        maxima[kind] = max(maxima[kind], active[kind])
        if active == {'preparation': 12, 'consolidation': 2}:
            ready.set()
        try:
            await release.wait()
            return {'complete': True}
        finally:
            active[kind] -= 1
    async def prepare(context):
        return await memory('preparation')
    async def consolidate(context):
        return await memory('consolidation')
    async def ordinary(context):
        nonlocal ordinary_completed
        ordinary_completed += 1
        return {'ordinary': True}
    handlers = {HISTORICAL_MEMORY_PREPARE_HANDLER_KEY: prepare, HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY: consolidate, SCHEDULER_JOB_HANDLER_KEY: ordinary}
    registry = JobHandlerRegistry(tuple(dataclasses.replace(d, handler=handlers[d.key]) for d in get_job_handler_registry().definitions() if d.key in handlers))
    runtime = LocalJobRuntime(handlers=registry, container_factory=di.Container, max_concurrency=16, cancellation_grace_seconds=0.1)
    deadline = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=90)
    handles = []
    started = time.perf_counter()
    try:
        for key, count in [(HISTORICAL_MEMORY_PREPARE_HANDLER_KEY, 13), (HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY, 3)]:
            for index in range(count):
                handles.append(await runtime.submit(JobRequest(handler_key=key, execution_key=f'{os.getpid()}:{key}:{index}', deadline=deadline, payload={})))
        async with asyncio.timeout(30):
            await ready.wait()
            ordinary_handles = [await runtime.submit(JobRequest(handler_key=SCHEDULER_JOB_HANDLER_KEY, execution_key=f'ordinary:{index}', deadline=deadline, payload={})) for index in range(2)]
            outcomes = await asyncio.gather(*(h.wait() for h in ordinary_handles))
            assert all(o.status is JobOutcomeStatus.SUCCEEDED for o in outcomes)
        assert active == {'preparation': 12, 'consolidation': 2}
        print(json.dumps({'pid': os.getpid(), 'active': active, 'ordinary_completed_while_memory_blocked': ordinary_completed, 'queued_memory': 2, 'ready_ms': round((time.perf_counter()-started)*1000,3)}), flush=True)
        command = await asyncio.to_thread(sys.stdin.readline)
        assert command.strip() == 'release'
        release.set()
        assert all(o.status is JobOutcomeStatus.SUCCEEDED for o in await asyncio.gather(*(h.wait() for h in handles)))
    finally:
        release.set()
        await runtime.close()
    assert runtime.active_count == 0
    print(json.dumps({'pid': os.getpid(), 'maxima': maxima, 'memory_completed': len(handles), 'active_after_close': runtime.active_count}), flush=True)

asyncio.run(main())
```

### memory-phase5-capacity-run.py

```python
"""One-time one/three-process rendezvous report using real Local Job Runtimes."""
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
root = Path(__file__).parent
rows = []
for replicas in (1, 3):
    workers = [subprocess.Popen([sys.executable, str(root / 'memory-phase5-capacity-worker.py')], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(replicas)]
    try:
        ready = [json.loads(worker.stdout.readline()) for worker in workers]
        assert len({row['pid'] for row in ready}) == replicas
        assert all(row['active'] == {'preparation': 12, 'consolidation': 2} for row in ready)
        for worker in workers:
            worker.stdin.write('release\n')
            worker.stdin.flush()
        completed = [json.loads(worker.stdout.readline()) for worker in workers]
        for worker in workers:
            assert worker.wait(timeout=20) == 0, worker.stderr.read()
        row = dict(replicas=replicas, topology='independent Python worker processes; one LocalJobRuntime per process; synthetic blocking handlers, no model/network/DB work', configured_slots=16 * replicas, simultaneously_active_preparation=sum(r['active']['preparation'] for r in ready), simultaneously_active_consolidation=sum(r['active']['consolidation'] for r in ready), ordinary_completed_while_blocked=sum(r['ordinary_completed_while_memory_blocked'] for r in ready), queued_memory=sum(r['queued_memory'] for r in ready), readiness=ready, completion=completed, cpu_count=os.cpu_count(), python=platform.python_version(), platform=platform.platform())
        rows.append(row)
        print(json.dumps(row, sort_keys=True))
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.wait()
(root / 'memory-phase5-capacity-measurements.json').write_text(json.dumps(rows, indent=2) + '\n')
```

### memory-phase5-source-change_test.py

```python
"""One-time canonical update/work coalescence measurement, not a load suite."""
import datetime
import json
import time
from pathlib import Path
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7
from azents.rdb.session import SessionManager
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import RDBConsolidationWork
from azents.core.historical_memory import HistoricalMemoryCompletion
from azents.core.historical_memory_consolidation import ConsolidationWorkState
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.historical_memory_consolidation.ownership import ConsolidationOwnershipRepository
from azents.repos.historical_memory_consolidation.work import ConsolidationWorkRepository, work_predicate
from azents.testing.consolidation import seed_consolidation_corpus
pytest_plugins = ['azents.conftest']

async def test_repeated_canonical_changes(rdb_session_manager: SessionManager[AsyncSession]):
    manager = rdb_session_manager
    corpus = await seed_consolidation_corpus(manager)
    repository = HistoricalMemoryRepository(manager)
    samples = []
    for index in range(32):
        now = datetime.datetime.now(datetime.UTC)
        begin = time.perf_counter()
        assert await repository.publish_completed(source_session_id=corpus.team_source, completion=HistoricalMemoryCompletion(source_activity_at=now, source_tail_event_id=uuid7().hex, prepared_at=now, source_title_snapshot='Synthetic changing source', summary=f'Synthetic canonical content generation {index + 2}')) is not None
        samples.append(round((time.perf_counter() - begin)*1000,3))
    claim = await ConsolidationOwnershipRepository(manager).claim(corpus.team)
    assert claim is not None
    work = ConsolidationWorkRepository(manager)
    retired = await work.retire_obsolete_pending(claim.principal)
    page = await work.page(claim.principal, after_sequence=None, limit=50)
    assert retired == 32
    assert len(page.entries) == 1 and page.entries[0].version.summary_generation == 33
    async with manager() as session:
        source = await session.get(RDBHistoricalMemorySource, corpus.team_source)
        assert source.summary_generation == 33
        total = await session.scalar(sa.select(sa.func.count()).select_from(RDBConsolidationWork).where(work_predicate(corpus.team)))
        superseded = await session.scalar(sa.select(sa.func.count()).select_from(RDBConsolidationWork).where(work_predicate(corpus.team), RDBConsolidationWork.state == ConsolidationWorkState.SUPERSEDED))
    row = dict(real_canonical_updates=32, final_generation=33, total_exact_work=total, superseded=superseded, eligible_delivered=1, update_ms=samples, update_total_ms=round(sum(samples),3), update_max_ms=max(samples), topology='one process, ordinary repository publication, disposable PostgreSQL 17')
    Path('/tmp/memory-phase5-validation/memory-phase5-source-change-measurements.json').write_text(json.dumps(row,indent=2)+'\n')
    print(json.dumps(row))
```
