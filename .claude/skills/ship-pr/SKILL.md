---
name: ship-pr
description: "Run the PR shipping flow. Use for: (1) '/ship-pr', (2) requests such as 'create a PR and monitor it'. PR creation itself is delegated to /create-pr."
---

# Ship PR (/ship-pr)

Check that the current branch is ready for review, then create the PR through `/create-pr`. This skill owns the quality and spec gates; the actual PR creation procedure is delegated to `/create-pr`.

## Workflow

### 1. Establish review ownership

Satisfy the `/code-review` gate before creating the PR.

- For a single-agent change, the current agent is the implementation owner. Run
  `/code-review`, apply required findings, and commit.
- For a delegated implementation, use the completed review evidence when the
  named implementation owner directly requested review from the named
  independent reviewer, applied required findings, ran affected validation,
  and received the reviewer's recheck. The shipping agent performs final
  verification only; it does not start a replacement review or apply findings.
- If delegated review evidence is incomplete, return the work to the
  implementation owner and its assigned reviewer before continuing.

### 2. Complete required fixes

The implementation owner applies review findings on the same branch.

- Fix Critical and Warning findings, run affected validation, and commit.
- Apply Suggestion and Consistency findings when reasonable.
- In a delegated workflow, have the same independent reviewer recheck addressed
  findings. The shipping agent must route required final-verification changes
  back to the implementation owner instead of editing them directly.

For a single-agent change, run review and fixes only once. After
`/code-review` → apply required fixes → commit, do not start another review loop
within the same `/ship-pr` execution. Continue to PR creation.

### 3. Call `/create-pr`

Call `/create-pr` with the validation context. Because `/create-pr` only creates the PR, leave the following information in the conversation context so it can be included in the PR body when appropriate:

- Tests and quality checks that were run, plus results
- Whether the PR body should include `## Spec Impact`

Follow the `/create-pr` rules.

### 4. Report the result

- Created PR URL
- Review owner, reviewer, findings, and recheck result
- Final verification result
