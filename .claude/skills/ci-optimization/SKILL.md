---
name: ci-optimization
description: Improve Azents general CI reliability, unit/integration/pytest and E2E test runtime, test-design and test-layer correctness, lint/typecheck/build performance, and runner cost using verified artifacts and repeated same-SHA measurements. Use for manual or scheduled CI optimization, slow or redundant tests, E2E convention violations, flaky CI, or general CI observability analysis; includes E2E as a subset.
---

# CI Optimization

Own the complete loop across general CI, not only numbered E2E lanes. Inspect
the Linux `.github/workflows/ci.yaml`, configured required checks and their dependency
graphs before selecting a candidate. Keep iOS as a separate quality workflow: report
its failures honestly, but exclude it from speed statistics, daily charts and the
two-attempt measurement requirement. Do not repeat iOS merely to obtain timing
samples or make its timing pair a prerequisite for Linux measurement completion.
Release, publication and deployment effects are not experiments unless authorized.

## Start safely

1. Audit registered worktrees, dirty state, branches and PRs. Remove only clean,
   completed worktrees belonging to this Session with definite merged/closed or
   completed-work evidence. Preserve foreign, dirty, unfinished, unknown and reused
   development environments. Record the audit before doing candidate work.
2. Fetch latest main with explicit refspec. Continue existing open optimization PRs
   and prior candidate evidence; do not create a duplicate or mix unrelated work.
   An approval-blocked candidate does not block independent authorized general-CI
   work: record that prerequisite and continue the other ranked candidates.
3. Record Requirements before code work. Use a focused temporary repository file for
   bounded tooling fixes and remove it before commit. Follow technical feature design
   for material new authority, persistence, operational or product decisions.
4. Rank current demonstrated reliability failures first, then expected whole-CI gate
   completion gain, confidence, runner cost and risk. Evaluate new candidates each
   recurring cycle even while continuing an existing PR.

## Collect trustworthy evidence

Use repository-root commands; shared tooling lives under `scripts/ci/`:

```bash
python -m scripts.ci.collect --repository azents/azents --run-id RUN \
  --attempt ATTEMPT --output /absolute/session/ci/main-RUN-ATTEMPT
python -m scripts.ci.analyze --samples-root /absolute/session/ci/baseline \
  --cohort baseline --json-output /absolute/session/ci/baseline.json
python -m scripts.ci.analyze --samples-root /absolute/session/ci/experiment \
  --cohort experiment --json-output /absolute/session/ci/experiment.json
```

Preserve complete metadata/artifacts before rerunning a workflow. Artifacts must match
head SHA, run and attempt; later-attempt artifacts must not be attached to earlier
attempts. Reject duplicate attempts and mixed-SHA experiment samples. Compare identical
enabled jobs, behavioral obligations and lifecycle boundaries. Testcase counts and
assertion locations may change when a verified test-layer correction moves exhaustive
checks to narrower tests; record that mapping rather than requiring historical counts.
For dynamically planned E2E lanes, compare the full testcase multiset within Required
and Web separately, retaining multiplicity and enabled lane jobs. Numbered lane
redistribution does not change coverage; keep original per-lane metrics and do not
attribute planner-driven timing differences to a candidate mechanism.

Include Python matrix unit/integration pytest, migrations, Docker-free support tests,
Helm tests, E2E/Web, TypeScript tests and all Linux lint/typecheck/build steps. The
shared pytest plugin records safe setup/call/teardown and fixture metadata. Other
runners retain native diagnostics plus workflow job/step time; do not label job duration
as test-call duration or claim unavailable per-case metrics exist. Native iOS evidence
remains quality/debugging evidence, not a recurring performance cohort.

Read [references/metrics.md](references/metrics.md) for metric and artifact contracts.

## Review the tests themselves

Slow tests can be incorrectly designed. Inspect their bodies and applicable testing
conventions before treating their cost as necessary or optimizing only fixtures,
images, scheduling, polling, workers or runners. Test code is an optimization target.

- Check for redundant assertions, repeated setup or journeys, obsolete checks, and
  waits for states that are not the behavior's actual completion authority.
- Apply `.claude/conventions/testenv/e2e-core-flows-only.md` and owning instructions:
  E2E proves representative assembled-product outcomes. Exhaustive condition matrices,
  internal branches, validation permutations, copy, confirmation/error dialogs and
  responsive UI interactions belong in unit, integration, component or Storybook tests
  unless the specific check requires a real cross-process/browser/provider boundary.
- Trace existing narrower coverage. Add missing executable assertions before moving
  or removing redundant E2E work; a render-only story is not interaction evidence.
  Retain representative E2E coverage of every affected feature's critical outcome,
  authorization, isolation, abrupt failure and recovery boundaries.
- Record old scenario/check -> retained E2E journey or exact narrower test, why that
  layer proves the behavior, and actual validation. Do not equate fewer E2E cases with
  weaker coverage, but do not claim preserved coverage from a proposed mapping alone.
- Rank grounded test-design/convention fixes alongside infrastructure candidates.
  Do not preserve a poorly placed test just to keep its count or body unchanged.
  Measure real CI after the correction; deleted runtime alone is not proof of a net
  coverage-preserving improvement.

## Model and rank

- Primary whole-CI metric: workflow creation to last configured required gate
  completion. It includes dependency scheduling and queues; identify those costs rather
  than describing it as a causal DAG estimate or the longest individual lane.
- Also report maximum job wall, every job/step wall, sum of job runner-seconds, and
  observability overhead. Different runner classes have different cost rates; don't
  add runners, jobs or image producers without approval and full cost evidence.
- E2E max-lane wall remains a named subset metric. Preserve its duration gate/planner
  policy; this extension does not authorize a new failing gate or changed threshold.
- Separate test call/setup/teardown from nested fixture and image timings. Inspect
  slow bodies and duplicate initialization, not startup attributed to the first test.
- Maintain a candidate ledger: tests/jobs, mechanism, retained coverage, observed
  phases, saving, dependency/lane takeover, overhead, compatible combinations and
  concrete rejection/blocker for every ranked candidate.
- Model the smallest compatible coverage-preserving candidate set likely to achieve
  at least 30 seconds or 5 percent net whole-CI completion gain. Small proven savings
  are useful building blocks; recompute dependency completion and takeover, never add
  aggregate body durations. Reliability value may justify below-threshold work.

## Implement and validate

Use `e2e-debugging` for E2E, `python-quality-check` for Python and
`typescript-quality-check` for TypeScript as appropriate. Read applicable conventions.
Keep fixes at the narrowest layer that removes proven waste while retaining behavior.

1. Deterministic unit/support tests for the changed mechanism.
2. Format, lint and strict type checks for affected projects and shared tooling.
3. Smallest real integration/E2E selection when product boundaries change.
4. Independent read-only `code-review`, then `spec-review` and matching Living Spec.
5. `ship-pr` for PR creation/monitoring; request `hardtack` when verification is ready.

Preserve required behavioral coverage, not an arbitrary number of tests. Remove or
relocate redundant/mis-layered checks only with the verified mapping above; never
silently drop assertions, covered states, authorization or recovery obligations to
make CI green. Do not replace abrupt failure with graceful cleanup, write product
state directly through SQL, add fixed sleeps/retries, increase timeouts or relax
existing gates. Local timing proves a mechanism, not whole-CI causal improvement.

## Repeat and accept

After first complete Linux CI success, preserve metadata/artifacts and repeat that CI
on the unchanged SHA. Require at least two complete successful same-SHA attempts and
the same enabled test/job scope, with no hidden failures or missing evidence. A green
status linking another SHA is not successful verification of this PR.

Compare Linux CI baseline and experiment separately. Report each attempt's SHA, run/attempt,
gate completion, jobs/steps, test-phase mechanism and all overhead. Report mean and
median, absolute/percentage change and resource costs. Classify accepted,
reliability-accepted, inconclusive or rejected. Do not claim success from one run.

A failed CI or validation run is work to diagnose and repair while the task is active.
Continue compatible, coverage-preserving corrections and obtain successful exact-SHA
validation; do not stop merely by recording the failure or attributing it to noisy
infrastructure. Preserve each failed attempt separately and never rerun until green
without an evidence-backed investigation.

For recurring work, continue compatible proven candidates when measurement misses
acceptance. Finish without an accepted change only with documented exhausted candidates,
concrete missing evidence or a prerequisite/authority blocker. Do not call an unprofiled
slow test infeasible. Never merge without approval.

## Close unsuccessful experiments

When ending an experiment as failed, rejected, ineffective or inconclusive, complete
cleanup in the same work cycle:

1. Preserve the failure, measurements, exact SHAs, run/attempt identities, artifact
   provenance and next findings in the durable report. The report is the failure
   record; an open experiment PR or retained branch is not the archive.
2. Close the unsuccessful experiment PR and verify that it is closed. A Draft label,
   noisy evidence, a future feasible candidate or an approval blocker is not a reason
   to leave a terminally unsuccessful PR open.
3. Delete the experiment's remote branch after preserving its report and evidence.
   Do not create archive branches merely to retain failed work.
4. Remove its clean, Agent-owned worktree through the managed-worktree lifecycle.
   For a worktree explicitly reused by new active work, switch it to the new task's
   branch instead. Protect dirty, foreign or unknown worktrees and report actual
   cleanup blockers without forcing deletion.
5. Delete the local experiment branch only after no worktree has it checked out;
   managed worktree removal preserves that branch. A protected checked-out worktree
   is a real blocker to report, not a reason to force removal or claim success.
6. Verify and report the PR, branch and worktree cleanup outcome. Later work starts
   as a new active experiment rather than leaving the failed PR waiting indefinitely.

## Durable reporting and recurring prompts

- Accumulate KST date, SHA/workflow/run/attempt, conclusions, enabled scope, job and
  gate times, mean/median and costs in durable Session files. Preserve original E2E
  history as its own scope; never fill general-CI values with E2E subset values.
- Append deduplicated real main records with
  `python -m scripts.ci.history --analysis /absolute/session/ci/baseline.json
  --history /absolute/session/ci-main-history.jsonl --cohort main`.
  The tool rejects non-main sources, conflicting attempts and experiment relabeling.
  Keep baseline/experiment and independent workflows/runner classes separate.
  Preserve historical iOS evidence, but do not append it to the Linux benchmark or
  generate native speed charts for recurring reports.
- Render only the latest 30 KST calendar dates including report date:

  ```bash
  python -m scripts.ci.chart --history /absolute/session/ci-main-history.jsonl \
    --workflow CI --date YYYY-MM-DD --output /absolute/session/ci-30d.png
  ```

  Plot mean/median/min–max/n and lower-is-faster; expose missing, failed and unverified
  dates without interpolation. Keep raw history beyond 30 days. Never mix synthetic
  fixtures or experiments with main trends. Visually inspect exported PNGs.
  Install plotting only when needed with the E2E project's optional `ci-report`
  dependency group (`uv sync --group ci-report`); test producers do not install it.
- Keep Scheduled Task title/objective, linked documentation and reporting tools aligned
  with general-CI scope. Preserve schedule/channel/cleanup/merge constraints; replace
  tasks through the Scheduled Task Skill, not database edits.
- Report selected/new candidates, blocked combinations, verification/review, PR link,
  exact measurements, classification, next work and no-merge statement. Update PR
  bodies with measured evidence, not only expected savings.

Historical E2E-only datasets use `scripts/analyze_e2e_ci.py` within this Skill as a
subset diagnostic. They cannot fill missing whole-CI metrics or establish general-CI
acceptance.
