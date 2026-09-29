# E2E CI Measurement Reference

## Sample layout

Keep measurement data outside the repository:

Choose the analyzer cohort explicitly. A baseline may contain several recent main
SHAs. An experiment must contain attempts from exactly one commit SHA.

```text
/tmp/e2e-ci-baseline/
└── main-32315071726/
    ├── run.json
    ├── e2e-observability-required-1/
    ├── e2e-observability-required-2/
    ├── e2e-observability-required-3/
    └── e2e-observability-web-1/

/tmp/e2e-ci-experiment/
└── pr-32321108387-attempt-1/
    ├── run.json
    ├── e2e-observability-required-1/
    ├── e2e-observability-required-2/
    ├── e2e-observability-required-3/
    └── e2e-observability-web-1/
```

Each `run.json` must contain the output of:

```bash
gh run view RUN_ID --json status,conclusion,headSha,createdAt,jobs
```

For a rerun attempt, include `--attempt ATTEMPT`.

Each enabled suite-lane artifact gated by `ci-python-e2e` must contain
`pytest-timings.jsonl` with test call records and `junit.xml` with test cases. This
includes `web-*` whenever Web E2E is enabled. The analyzer rejects samples without
this evidence.
Reliability failure counts use every complete attempt; performance timing, image, and
overlap summaries use successful attempts only.

Download and preserve one attempt before starting the next rerun. GitHub artifact
downloads normally expose the latest attempt after rerun.

## Core metrics

### Gated E2E critical path

For one run:

```text
max(required-1 wall, required-2 wall, ..., web-1 wall, ...)
```

Use job `startedAt` and `completedAt`. Do not use queue time.

### Test and fixture phase attribution

Read `pytest-timings.jsonl` by `record_type` and `phase`:

- Use `test_phase` records with `phase=call` for actual test-body runtime.
- Inspect `setup` and `teardown` separately, using `fixture` records and their scope
  to identify shared startup, cleanup, or repeated initialization.
- Summarize successful samples by node ID with sample count, mean, median, and range;
  keep failures and skips separate. Follow moved tests across lane assignments.
- Treat first-test setup as fixture work, not as test-body work. A body may itself
  create provider/Gateway contexts, so profile those operations inside the call.
- Count shared fixture time once when building a budget. Do not add nested fixture
  records or a test's setup total to the same startup cost again.

Use measured phase boundaries to distinguish removable waste from required readiness,
restart, recovery, or elapsed-time behavior. Preserve those observable boundaries.

### Candidate critical-path saving

For every run:

1. subtract the candidate saving from each affected lane;
2. recompute the maximum lane wall;
3. subtract the new maximum from the original maximum.

Average those per-run savings. Never omit an enabled suite or use aggregate
test-duration reduction as the required-CI claim.

### Compatible small-change bundles

Apply the 30-second/5-percent threshold to the final bundle. Keep small, validated
test/scenario/fixture improvements available for combination:

1. Record each candidate's affected node IDs, fixture scopes, lanes, removed work,
   retained assertions/state transitions, evidence, saving estimate, and overhead.
2. Apply the complete set to every baseline run's observed lane assignment; subtract
   non-overlapping savings once and add producer, setup, transfer, and cleanup costs.
3. Recompute the maximum across all gated lanes after each addition and for the bundle.
   Investigate takeover lanes as well as the original critical lane.
4. Check compatibility: one change may remove another's saving or alter fixture
   lifetime/resource contention. Do not simply sum independently measured gains.
5. Validate each mechanism locally, then measure the final unchanged SHA in at least
   two successful full workflows. Distinguish modeled budgets from observed CI gains.

Synthetic calculation example, **not CI evidence**: lane A takes 500s, lane B 490s,
and all other gated lanes at most 470s. Three independent 10s reductions in A make
A 470s, but the gate becomes B's 490s: only 10s saved. Add two compatible 10s
reductions in B and the gate becomes 470s: 30s saved by the bundle. This example
assumes zero new overhead; real acceptance must include it.

Before reporting an exhausted recurring cycle, retain the ranked candidate ledger and
the concrete evidence or constraint rejecting each remaining feasible combination.
An unprofiled slow test or one subthreshold infrastructure experiment does not establish
that every compatible test-level improvement is infeasible.

### Parallel overlap

When independent work is moved into one concurrent fixture:

```text
sum(individual operation durations) - concurrent fixture wall time
```

This proves overlap inside the measured attempt. It does not by itself prove the
whole required gate improved.

### Experiment comparison

Use at least two successful attempts at one commit:

```text
absolute improvement = baseline mean - experiment mean
percentage improvement = absolute improvement / baseline mean * 100
```

Also report the baseline median and every attempt separately so noise remains visible.

## Reliability evidence

Count failed test node IDs across the sampled runs. For each candidate:

- record the first and latest failure;
- identify subsequent fixes that touched the relevant path;
- count consecutive passes after the failure;
- distinguish a current reproducible mechanism from a historical one-off;
- retain the failure message and authoritative diagnostic state.

Do not infer that a timeout needs a longer timeout.

## Acceptance defaults

- Performance: at least 30 seconds or 5 percent net required critical-path gain.
- Reliability: removal of a demonstrated current failure mechanism.
- Same-SHA attempts: at least two complete successes.
- Merge: never without explicit requester approval.
