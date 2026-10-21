# General CI Measurement Reference

## Sample layout and collection

```text
ci/baseline/main-RUN-ATTEMPT/
  run.json
  artifact-inventory.json
  collection.json
  artifacts/
    ci-observability-python-azents-ATTEMPT/
      test-run.json
      junit.xml
      pytest-timings.jsonl
      lane-duration-seconds.txt
      summary.md
    e2e-observability-required-1/
    e2e-observability-web-1/
```

Use `python -m scripts.ci.collect` with explicit repository/run/attempt. Preserve
attempt artifacts before rerunning. GitHub may replace E2E artifacts on subsequent
attempts; reject artifacts created outside the selected attempt or with different
head SHA. General pytest artifact names carry attempt; the E2E planner/duration gate
retains its current artifact contract. Missing results after setup failure are not
successful tests. Preserve failed workflow metadata and missing-evidence classification.
Require the GitHub API SHA256 digest for every selected artifact and retain the exact
`artifact-ID.zip`. Collection authenticates ZIP bytes before extraction; replay
compares archive-derived file hashes with the manifest and extracted evidence. Missing
archives/digests or a rewritten local manifest cannot substitute for this proof.
Keep historical raw files; recollect available immutable artifacts or report an
unverified gap rather than adding a compatibility acceptance path.

`run.json` uses `gh run view --attempt N --json databaseId,attempt,status,conclusion,
headSha,headBranch,event,workflowName,createdAt,jobs`. Job names and steps are
extensible GitHub input decoded at the
boundary. Exact run/attempt/SHA and enabled scope govern acceptance, not PR context
color or artifacts from another commit. Baseline may contain several main SHAs;
experiment must have one SHA, equal enabled jobs and equal testcase evidence.
Compare testcase multisets across numbered lanes within Required and Web separately:
the existing planner may redistribute cases without changing scope. Preserve
multiplicity, the Required/Web boundary, general pytest producer identity, all
enabled lane jobs, and each lane's original metrics. Redistribution is not a
coverage reduction or by itself evidence of a causal performance improvement.

For a convention-backed test-layer correction, baseline and candidate E2E multisets
may legitimately differ. Preserve both raw multisets and report every removed or
relocated scenario/check with its retained representative E2E journey or exact
unit/integration/component/Storybook replacement and executed evidence. Keep this
scope correction distinct from scheduling-only comparisons. The two final unchanged-SHA
attempts must still have identical enabled jobs and testcase multisets, including the
replacement test producers. Missing replacement artifacts cannot establish preserved
behavioral coverage. Do not modify the gate, ignore missing producers, or simply divide
aggregate call work by worker count to hide a failure.

## Metric scopes

- **Whole-CI gate completion elapsed:** Linux CI workflow `createdAt` to last completion
  among configured gates: pre-commit, Python, E2E, TypeScript, Helm and Docker.
  This includes dependency scheduling/queue time and is not a reconstructed
  causal DAG length. Report actual workflow completion separately when available.
- **Job wall:** `completedAt - startedAt`, not queue time; include matrix and setup,
  test, artifact, cleanup costs. Report steps using the same boundary.
- **Maximum job wall:** diagnostic only; sequential plan/producer/aggregate/gate work
  means it is not whole-CI completion.
- **Runner job-seconds:** sum of all job walls, with reporting-job overhead separately
  named. Do not add macOS and Linux time as equal monetary cost; retain runner class
  and apply known rates explicitly when making financial claims.
- **E2E subset critical:** max of every enabled numbered required/Web lane wall.
  Keep this separate from general CI. Do not relabel historical E2E-only rows.
- **Test call/setup/teardown:** safe pytest phase records plus actual fixture scope.
  Nested fixture/setup durations overlap; never sum them twice. Native non-pytest
  reports remain native; job/step data does not imply per-case timing exists.

Observation alone does not authorize changing test selections or assertions. Verified
test-design corrections follow the Skill's test-layer mapping and validation contract.
They do not change branch protection, gate success conditions, E2E duration thresholds,
retry policy or runner count.
Keep iOS as a separate quality workflow. Preserve native diagnostics when investigating
failures, but exclude its durations from CI speed statistics, recurring charts and
the two-success timing acceptance requirement. Do not repeat iOS for measurement or
make a native timing pair a prerequisite for Linux measurement completion. Report
red native quality checks independently rather than hiding them as success.
Release/deploy workflows are excluded from experiments without explicit authorization.

## Profile and budget

Rank demonstrated reliability failures, then dependency-critical net savings, confidence,
runner cost and risk. Read slow tests and actual fixture lifecycle. Identify removed
work while preserving behavioral assertions at the appropriate test layer, isolated
state, abrupt restarts and real recovery.
Record every candidate's evidence, phases, scope, mechanism, estimated saving/overhead,
compatibility and concrete remaining blocker.

Model compatible small changes together, recomputing takeover and dependency completion
at every addition. Sum-of-body-time, all-removal ceilings and save50 heuristics are not
proven savings. Include image pulls/producer jobs/transfers/setup/teardown and reporting
costs. New resource usage requires explicit approval. Default acceptance is at least
30 seconds or 5 percent net whole-CI completion improvement; grounded reliability value
may justify below-threshold work. Existing failing duration policy remains E2E-specific.

Require two successful complete Linux CI attempts at the final unchanged SHA. Preserve each
attempt before rerun. Analyze baseline and experiment separately and report sample count,
mean/median, every attempt, absolute/percentage change and all failure evidence. Missing
new unit-test artifacts makes general-CI acceptance inconclusive even if E2E passed.

## Daily history and charts

Append deduplicated real main Linux CI records, keyed by workflow/run/attempt. Preserve full raw
history; display exactly 30 KST calendar dates ending at report date. Plot daily
mean/median/min–max/sample count and lower-is-faster. Failed/unverified/missing dates
remain gaps; do not interpolate. Mixed enabled scopes are descriptive trends, not causal
speed claims. Never mix synthetic tests, local timings or PR experiments with main.

## Historical E2E-only diagnostic

The retained `scripts/analyze_e2e_ci.py` accepts the historical layout with
`run.json` plus direct `e2e-observability-*` directories. It analyzes the E2E subset
only and cannot prove general-CI completion, unit-test observability or whole-CI gains.
Use it when inspecting old source evidence, not as the primary recurring optimizer.
