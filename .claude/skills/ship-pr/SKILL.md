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
  `/code-review`, address required findings, run affected validation, and commit.
- For a delegated implementation, use the completed review evidence when the
  named implementation owner directly requested review from the named
  independent reviewer, required findings were addressed, affected validation
  ran, and any required targeted re-review completed.
- Complete any missing review evidence before continuing.

### 2. Complete the review gate

Batch accepted findings into one correction pass on the same branch.

- Address Critical and Warning findings. Address Suggestion and Consistency
  findings when reasonable.
- Run affected validation and commit the resulting changes.
- Use the `/code-review` re-review criteria. When required, the implementation
  owner directly requests targeted re-review from the same independent reviewer.
  After self-review, assign an independent reviewer before the request.
- If final verification changes the diff, rerun affected validation and apply
  the re-review criteria again before calling `/create-pr`.

### 3. Call `/create-pr`

Call `/create-pr` with the validation context. Because `/create-pr` only creates the PR, leave the following information in the conversation context so it can be included in the PR body when appropriate:

- Tests and quality checks that were run, plus results
- Whether the PR body should include `## Spec Impact`

Follow the `/create-pr` rules.

### 4. Report the result

- Created PR URL
- Review requester, reviewer, findings, and re-review decision or result
- Final verification result
