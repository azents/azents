---
title: "Historical Memory Integrated QA Report"
created: 2026-10-02
tags: [memory, testing, e2e, vfs, security, documentation]
document_role: supporting
document_type: supporting-validation-report
snapshot_id: memory-260930
---

# Historical Memory Integrated QA Report

## Scope and Authority

This report records root-owned integrated validation of
[`memory-260930/REQ`](../requirements/memory-260930-passive-session-context.md),
the accepted [ADR](../adr/memory-260930-passive-session-context.md), and approved
[Design revision 1](memory-260930-passive-session-context.md), mechanisms M1–M15.
Design delta: `None`. It covers the complete six-phase stack on main baseline
`704e71323`, with the final QA branch based on Phase 5 commit `e13215cc8`.
The requester subsequently asked for another main refresh. The complete stack
was rebased onto `8507ac5fc`, with Phase 5 now at `4118f6424`, and the affected
integrated checks below were repeated. No additional feature, compatibility
path, deployment, or live infrastructure change belongs to this phase.

## Environment and Evidence Boundary

Validation ran on 2026-10-02 KST in the Agent Runtime using Python 3.14.7,
current-worktree dependencies, disposable PostgreSQL/Redis fixtures, Docker
Runtime fixtures, and a local deterministic OpenAI Responses provider proxy.
The required journey builds content-matched Server/Runner/Provider images from
the worktree without image overrides or live credentials. Product state is
created through product APIs, never E2E-side SQL writes.

The testenv-only Historical sampler requires an aware domain sampling instant
and exact Agent ID. It calls real admission and preparation/publication services
without modifying source activity. Production discovery and jobs explicitly
use real time; execution deadlines and provider watchdogs remain wall-clock
based. The sampler proves the service path, not Scheduler dispatch or Job Runtime
supervision. Those contracts have separate integration coverage.

## Root Integrated Results

| Check | Command or scope | Result |
| --- | --- | --- |
| Backend quality | `uv run ruff check .`; `ruff format --check .`; `ty check --error-on-warning` in `python/apps/azents` | Passed; 1,824 formatted files |
| Full backend | `uv run pytest -q` | Final rebased tree: 6,850 passed, 3 skipped, 4 warnings; 283.03 s |
| Migration graph/schema | `uv run pytest -q migration_tests` on a disposable PostgreSQL container | 9 passed, 2 warnings; 8.32 s |
| Focused Historical/VFS matrix | Historical services/repositories, Memory VFS, VFS router, Saved tools, generic reads, run resolution, semantic projection, testenv sampler, Scheduler registry | Final rebased tree: 144 passed, 3 warnings; 8.05 s |
| Rebase conflict and migration regression | Catalog cleanup migration tests, deterministic Scheduled tool operations, and the full migration suite | 21 passed, 3 warnings; 18.45 s |
| Testenv support project | Ruff, format, whole typecheck, `uv run pytest -q` in `testenv/azents` | 131 passed; 3.63 s |
| E2E substrate | Ruff, format, whole typecheck, `uv run pytest -q src/support_tests` | Final rebased tree: 295 passed, 2 warnings; 4.15 s |
| Required assembled Historical journey | `uv run pytest -vv src/tests/required/public/test_historical_memory.py --tb=short` | Final rebased tree: 1 passed, 4 warnings; 63.42 s |
| Web unit tests | `pnpm --filter @azents/web test` | 321 passed |
| TypeScript workspace | `pnpm format:check`; `pnpm lint`; `pnpm typecheck`; `pnpm build` | Passed, including regenerated TypeScript clients and all seven build tasks |
| OpenAPI and generated clients | `uv run python src/cli/dump_openapi.py`; generated client imports and Historical list/detail/model smoke check | No Public/Admin schema drift; Python list/detail and `source_path` available |
| Storybook | Rebuilt stories through a local named browser session | Historical disabled-loaded play finished without browser errors after rebase; source links visible, mutation actions absent; empty/loading/error and Saved-editing states inspected before rebase |
| Documentation | `python scripts/docs_catalog.py validate`; `python -m unittest scripts.tests.test_docs_catalog` | Frontmatter valid; 18 catalog tests passed |
| Patch integrity | `git diff --check` | Passed |

Existing dependency deprecations, the migration graph's known SQLAlchemy sorting
warning, and fixture HTTPS verification warnings remain visible in the logs.
The full backend's three skips are not counted as passes. No live-provider test
was enabled or represented as verified.

Raw root logs remain in the Session output folder as `phase6-backend-full.log`,
`phase6-migrations.log`, `phase6-focused-matrix.log`, `phase6-root-e2e.log`,
`phase6-e2e-support.log`, `phase6-web-tests.log`, and `phase6-ts-build.log`.
The Storybook screenshot is `hm-historical-disabled-story.png`. These are
execution artifacts, not an additional tracked test suite. Final rebased logs use
the `phase6-post-rebase-*` prefix; conflict/migration evidence is
`phase6-rebase-migration-conflicts.log` and Storybook build evidence is
`phase6-storybook-build.log`. The initial full run had 6,847 passes before three
direct compaction-boundary regressions were added. The new checks prove committed
summary-head reselection once, subsequent filtering without reselection, and
rejection of missing or another Session's head.

The rebase's two Phase 1 conflicts preserved main's deferred-constraint migration
tests and deterministic Scheduled tool clock. Phase 2–5 are patch-identical in
`git range-diff`; the restored Phase 6 Spec preserves main's duration-gate change
and adds the Historical section as the next Spec version. Earlier stack branches
were updated with `--force-with-lease`. No main contract was reverted.

## Representative Product Journey

The required journey verifies one cohesive public-path flow:

1. Create a Workspace, deterministic model integration, Runtime-free Public
   Agent, Team source, and private associated-User source through product APIs.
2. Sample below six hours and observe no admission or preparation. At seven
   hours, observe three admissions: the automatically created empty Team-primary
   root plus the two conversational sources. Two actual strict model summaries
   are published; no Saved entries are manufactured.
3. Inspect exact Team/User Historical settings inventory and source detail.
   Start a new Team Session and inspect captured model input: the Team summary
   and canonical VFS path are present, private User context is absent, and the
   six obsolete read/history tool names are absent.
4. Execute model-selected generic `read`, `glob`, and `grep` against Memory
   without a Runtime. Private source reads disclose no summary; an absolute
   Runtime path returns the capability error.
5. Archive the source and observe human inventory and live VFS withdrawal.
   Restore it and observe the retained result without regenerating a summary.
6. Disable Memory and observe no preparation or permitted live Memory summary,
   while human Historical settings remain inspectable.

The deterministic summary distinguishes a user correction from an Agent
proposal, local result evidence from production deployment, unfinished work,
and unverified delivery. This validates the strict provider contract and
consumption path, not the semantic quality of a live provider.

## Narrower Matrix Ownership

The representative journey intentionally does not reproduce every branch as
E2E. The complete backend run and focused matrix exercise the existing narrower
contracts:

- Historical repository tests: rolling eligibility, older admitted work,
  current scope/member/lifecycle checks, failed-refresh retention, atomic
  publication, and purge cascade.
- Preparation/output/model-operation tests: strict and bounded output,
  model-operation attribution, candidate progress, empty completion, and
  real deadlines despite explicit domain samples.
- Snapshot and Worker/run tests: persisted initial/compaction boundary identity,
  topic ranking, whole-group bounds, missing-state behavior, and ordinary-turn
  filtering without reselection.
- Semantic projection tests: human correction/evidence precedence,
  conversational tool delivery state, omissions, and credential redaction.
- Memory VFS tests: current-root authorization, exact source events,
  tool-result isolation, SQL-side body bounds, body-free glob, bounded grep,
  and non-enumerating denied/disabled paths.
- Saved tool and API tests: independent save/upsert/delete authority remains.
- Scheduler/Job Runtime tests: activated registration, real discovery dispatch,
  handler execution/coalescing, and reserved ordinary-job capacity under
  saturated Historical preparation.
- Human settings route/repository/service and frontend tests: read-only
  Historical access, search/cursor correctness, and Saved/Historical state
  ownership. Storybook play specifically checks disabled-state read-only
  Historical controls; it is not evidence for every UI interaction.

Pure proxy support tests cover fixture isolation plus malformed/oversized/empty
responses. Those fixture modes are not claimed as separately executed assembled
product journeys.

## Scale, Rollout, and Removals

The separate [bounded load report](historical-memory-load-test-report-2026-10-02.md)
records the one-time 1,000-root/10-Agent corpus, bounded grep, snapshot competition,
large exact tool-result paging/rejection, query plans, and reserved capacity.
No permanent load suite or production SLO was added.

Five-minute `historical_memory_discovery` is enabled by default. The change does
not apply or deploy live resources. The six dedicated Memory/history factories,
dynamic per-turn Saved selection path, static read-mount routing, and Runtime
ownership of generic read tools are absent from the production paths. Saved
CRUD and original Session evidence remain canonical. Memory is live VFS data,
not transferable stored files or a replacement for immutable Skills projection.

Current Memory, Agent, Toolkit, execution-loop, compaction, periodic execution,
file-exchange, and test-strategy Specs describe the implemented boundaries.
Requirements and Design receive the same verified implementation date. The
feature's temporary implementation and phase plans are removed after Spec
promotion; the immutable snapshot, current Specs, code, and these useful
validation reports remain the sources of truth.

Independent final review and all-stack required CI are separate release gates;
this local QA report does not claim a merge or deployment.
