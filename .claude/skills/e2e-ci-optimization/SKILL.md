---
name: e2e-ci-optimization
description: Analyze and ship Azents E2E reliability and required-CI performance improvements using observability artifacts, critical-path modeling, focused reproduction, PR creation, and repeated same-SHA measurement. Use when asked to reduce E2E CI time, investigate flaky required E2E, rank optimization candidates, implement the next E2E improvement, or verify that an E2E optimization produced a real net gain.
---

# E2E CI Optimization

Own the complete improvement loop. For every recurring or scheduled improvement run,
ship the smallest coverage-preserving candidate set that can meet acceptance whenever
actionable candidates exist. Start with the highest-confidence change, but do not stop
after one implementation when modeled or measured impact remains below acceptance.
Continue adding compatible, separately explainable safe changes in the same cycle until
the combined result is accepted or every remaining candidate is infeasible.
Analysis-only completion is valid only when the requester explicitly asks for analysis
or the investigation establishes that no feasible candidate exists.

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
  CI measurements, measured acceptance, or a final exhausted-candidate rejection, and
  PR body update.
- **Recurring or scheduled improvement**: exhaust the ranked candidate list until one
  or more compatible changes form the smallest feasible candidate set likely to meet
  acceptance, then complete the ship flow for that set. If measurement misses
  acceptance, add the next compatible, separately explainable coverage-preserving
  candidate and repeat on the new SHA. Finish without an accepted implementation only
  when every discovered candidate is infeasible or the measured combined result
  remains below acceptance after all feasible candidates are exhausted. Report the
  concrete blocker or measured shortfall for each remaining candidate.

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

Build an acceptance budget before editing:

1. Model the smallest high-confidence change.
2. If it is unlikely to clear acceptance after lane takeover, combine it with the next
   compatible, separately explainable coverage-preserving candidate.
3. Continue until the modeled candidate set can clear acceptance or no feasible
   combination remains.
4. Keep each change separately explainable and validate its mechanism even when CI
   acceptance is measured for the combined set.

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

Treat test-level optimization as first-class implementation work. A safe candidate may
change:

- E2E test code and scenario structure;
- fixtures, provider fakes, barriers, and readiness evidence;
- test-support code and deterministic configuration;
- CI setup or artifact handling;
- production code when the bottleneck is a real product mechanism.

Prefer the narrowest layer that removes measured waste while retaining the same
observable behavior and failure boundary. Several compatible changes may be shipped in
one candidate set when one change cannot meet acceptance alone.

Never manufacture acceptance by deleting tests, weakening assertions, reducing the
covered state matrix, replacing abrupt failure with graceful cleanup, bypassing real
lease/recovery/lifecycle behavior, extending timeouts, or adding sleeps. Adding runners
or other CI resources requires explicit requester approval, and the acceptance model
must include their complete cost.

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

When the result is not accepted:

1. Preserve the completed attempt artifacts and record the measured shortfall.
2. Return to candidate ranking when another compatible, separately explainable
   coverage-preserving change is feasible.
3. Add that change to the same candidate set, rerun focused validation and review, and
   produce a new commit SHA.
4. Restart the complete two-successful-attempt measurement for that unchanged new SHA.
5. Stop with `inconclusive` or `rejected` only after feasible candidates are exhausted,
   evidence cannot distinguish the result, or the remaining changes require an
   unapproved coverage, reliability, or runner tradeoff.

## 7. Update the PR with measured evidence

Replace expected impact in the PR body with:

- baseline sample count, mean, and median;
- exact commit SHA;
- every same-SHA attempt and required lane time;
- experiment mean;
- absolute and percentage change;
- mechanism evidence from artifacts;
- pass/fail and final classification.

If the final result is rejected after all feasible compatible candidates are exhausted,
say so directly, update the PR with the measured rejection, and close it. Do not leave
the rejected experiment open merely to recommend closure. Keep the PR open when another
feasible candidate remains, the evidence is inconclusive, or the requester explicitly
asks to retain it. Do not preserve an ineffective optimization merely because
implementation is complete.

## Final report

Report:

- selected candidate set and why each change was included;
- implementation summary;
- review result;
- PR URL;
- baseline and same-SHA measurements;
- acceptance classification;
- remaining risk or next candidate;
- explicit statement that the PR was not merged.
