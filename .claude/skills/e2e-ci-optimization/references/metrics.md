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
    └── e2e-observability-required-3/

/tmp/e2e-ci-experiment/
└── pr-32321108387-attempt-1/
    ├── run.json
    ├── e2e-observability-required-1/
    ├── e2e-observability-required-2/
    └── e2e-observability-required-3/
```

Each `run.json` must contain the output of:

```bash
gh run view RUN_ID --json status,conclusion,headSha,createdAt,jobs
```

For a rerun attempt, include `--attempt ATTEMPT`.

Each required-lane artifact must contain `pytest-timings.jsonl` with test call records
and `junit.xml` with test cases. The analyzer rejects samples without this evidence.
Reliability failure counts use every complete attempt; performance timing, image, and
overlap summaries use successful attempts only.

Download and preserve one attempt before starting the next rerun. GitHub artifact
downloads normally expose the latest attempt after rerun.

## Core metrics

### Required critical path

For one run:

```text
max(required-1 wall, required-2 wall, required-3 wall, ...)
```

Use job `startedAt` and `completedAt`. Do not use queue time.

### Candidate critical-path saving

For every run:

1. subtract the candidate saving from each affected lane;
2. recompute the maximum lane wall;
3. subtract the new maximum from the original maximum.

Average those per-run savings. Never use aggregate test-duration reduction as the
required-CI claim.

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
