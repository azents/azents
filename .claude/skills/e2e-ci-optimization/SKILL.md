---
name: e2e-ci-optimization
description: Analyze and ship Azents E2E reliability and required-CI performance improvements using observability artifacts, critical-path modeling, focused reproduction, PR creation, and repeated same-SHA measurement. Use when asked to reduce E2E CI time, investigate flaky required E2E, rank optimization candidates, implement the next E2E improvement, or verify that an E2E optimization produced a real net gain.
---

# E2E CI Optimization

Own the complete improvement loop. For every recurring or scheduled improvement run,
ship one feasible improvement whenever at least one actionable candidate exists. If the
highest-impact candidate is blocked, continue down the ranked candidate list and select
the best candidate that can be implemented and validated safely in the current run.
Analysis-only completion is valid only when the requester explicitly asks for analysis or
the investigation establishes that no feasible candidate exists.

Reuse these skills instead of duplicating their procedures:

- `e2e-debugging` for focused reproduction and fixture diagnosis.
- `code-review` for the review gate.
- `spec-review` for Living Spec impact.
- `ship-pr` for PR creation and CI monitoring.

Run commands from the repository root unless a command says otherwise.

## Delivery contract

Determine the requested stopping point before execution:

- **Analysis only**: collect evidence, rank candidates, and recommend the next action.
- **Implementation**: continue through focused validation and review.
- **Ship or improve**: continue through PR creation, at least two successful same-SHA
  CI measurements, measured acceptance or rejection, and PR body update.
- **Recurring or scheduled improvement**: exhaust the ranked candidate list until one
  feasible improvement is selected, then complete the ship flow for that improvement.
  Finish without an implementation only when every discovered candidate is infeasible,
  and report the concrete blocker for each candidate.

Treat requests such as "improve E2E", "optimize E2E CI", or "find and fix the next
candidate" as ship requests unless the requester limits the scope.

Never merge a PR without explicit approval.

## 1. Establish a current baseline

1. Create a separate worktree or branch from the latest `origin/main`.
2. Refresh main with an explicit refspec before rebasing:

   ```bash
   git fetch origin +refs/heads/main:refs/remotes/origin/main
   git rebase origin/main
   ```

3. Record temporary task Requirements before code work. Delete the temporary file
   before commit.
4. Record requester exclusions, such as an approach or closed PR that must not be
   reused.
5. Collect recent main runs and download every `e2e-observability-*` artifact before
   making performance claims.

Keep research findings in a disposable working note outside the repository. Consolidate
the result and delete or retain the note according to the current Session workflow.

See [references/metrics.md](references/metrics.md) for sample layout, collection
commands, and metric definitions.

Analyze baseline and experiment samples separately:

```bash
python .agents/skills/e2e-ci-optimization/scripts/analyze_e2e_ci.py \
  --cohort baseline \
  --samples-root /tmp/e2e-ci-baseline \
  --json-output /tmp/e2e-ci-baseline.json
python .agents/skills/e2e-ci-optimization/scripts/analyze_e2e_ci.py \
  --cohort experiment \
  --samples-root /tmp/e2e-ci-experiment \
  --json-output /tmp/e2e-ci-experiment.json
```

The experiment analyzer rejects mixed commit SHAs and reports whether at least two
successful same-SHA attempts are available for acceptance.

## 2. Rank by impact

Rank candidates in this order:

1. A current reproducible reliability failure.
2. Expected required-CI critical-path reduction.
3. Breadth and confidence.
4. Regression and operational risk.

Do not rank by aggregate test duration. For each run, change the affected lane times
and recompute the maximum required-lane wall time.

Default performance acceptance threshold:

- at least 30 seconds net critical-path reduction; or
- at least 5 percent net critical-path reduction.

Reliability value may justify work below the performance threshold.

Include every new producer, dependency, artifact transfer, pull, load, setup, and
teardown cost. Reject optimizations that only move existing work to a new prerequisite.

## 3. Validate the candidate

For a reliability candidate:

1. Load `e2e-debugging`.
2. Reproduce the smallest test selection repeatedly on current main.
3. Capture authoritative product, provider-fake, and fixture readiness evidence.
4. Check whether a later fix already removed the failure mechanism.
5. Replace races with generation, correlation, barriers, persisted status, or other
   observable boundaries. Never extend a timeout or add a sleep as the fix.

For a performance candidate:

1. Identify the actual required-gate critical path.
2. Model lane takeover after the candidate is shortened.
3. Validate dependency and resource contention assumptions.
4. Prefer changes that overlap independent work without adding a new prerequisite.
5. Define the exact artifact evidence that will prove the mechanism worked.

## 4. Implement and validate

Read applicable repository, testenv, Python, and GitHub Actions conventions before
editing.

Preserve product behavior and required coverage. Do not write directly to the product
database from E2E tests or substrate.

Validation order:

1. Unit or Docker-free support tests for the changed mechanism.
2. Formatting, lint, and type checks for the affected project.
3. The smallest real Docker E2E selection.
4. Broader affected checks only when needed.

Record local timing as mechanism evidence, not as a substitute for CI measurement.

## 5. Review and create the PR

1. Load and run `code-review`.
2. Address required findings and rerun affected validation.
3. Load and run `spec-review`.
4. Update the matching Living Spec when the CI or test strategy changed.
5. Load and run `ship-pr`.
6. Request `hardtack` as reviewer.

Write the PR in English. Include:

- the changed behavior;
- modeled baseline and expected impact;
- validation performed;
- measurement risks;
- `## Spec Impact` when applicable.

## 6. Measure the same SHA

After the first complete PR CI succeeds:

1. Preserve its metadata and artifacts before rerunning.
2. Rerun the complete workflow on the same commit at least once.
3. Require at least two successful attempts for acceptance.
4. For each attempt, record:
   - required lane wall times;
   - required critical path;
   - failures;
   - the changed fixture or image timings;
   - within-run overlap or removed work;
   - all new overhead.
5. Compare the experiment mean with the recent-main baseline mean and median.
6. Classify the result:
   - **accepted**: reliable and above the threshold;
   - **reliability accepted**: removes a demonstrated failure mechanism;
   - **inconclusive**: insufficient or noisy evidence;
   - **rejected**: below threshold or slower.

Do not claim a result from one favorable run.

## 7. Update the PR with measured evidence

Replace expected impact in the PR body with:

- baseline sample count, mean, and median;
- exact commit SHA;
- every same-SHA attempt and required lane time;
- experiment mean;
- absolute and percentage change;
- mechanism evidence from artifacts;
- pass/fail and final classification.

If the result is rejected, say so directly and recommend closing or revising the PR.
Do not preserve an ineffective optimization merely because implementation is complete.

## Final report

Report:

- selected candidate and why it ranked first;
- implementation summary;
- review result;
- PR URL;
- baseline and same-SHA measurements;
- acceptance classification;
- remaining risk or next candidate;
- explicit statement that the PR was not merged.
