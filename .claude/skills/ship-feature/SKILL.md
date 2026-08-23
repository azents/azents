---
name: ship-feature
description: "Ship a large, multi-phase feature after Requirements, ADR, and Design are approved. Convert approved Design mechanisms into an implementation plan and reviewable delivery phases without creating new design authority. Use a focused PR for small self-contained work."
---

# Ship Feature Workflow

Use this workflow after feature design is complete and the requester asks to
implement.

## Choose the delivery shape

Choose based on reviewability, dependencies, validation, and rollout boundaries:

- Use one focused PR for a small self-contained feature, fix, or maintenance change.
  Include its tests, generated artifacts, and required documentation.
- Use stacked PRs when independent review phases, sequential dependencies,
  cross-cutting validation, or rollout boundaries make the work clearer.
- Do not create extra design, plan, validation, spec, or cleanup PRs only to match
  this workflow.

For phased work, use this sequence:

```text
approved design baseline
→ implementation plan
→ implementation phases
→ validation
→ spec promotion
→ plan cleanup
```

Use a consistent `{feature-name} [n/N]: <phase>` title prefix. Store the
multi-phase plan and all phase execution plans under the project-approved plans
directory; for Azents, use `docs/azents/plans/`.

## Phase 0: Confirm readiness

Before planning implementation:

- identify the confirmed Requirements, accepted ADR, and approved primary Design;
- confirm their shared snapshot basename and current project rules;
- verify complete forward Requirements traceability and reverse Design Authority;
- verify Design approval matches the current Design revision and exact material
  mechanism ID set;
- verify no material decision remains pending;
- verify every Removal and Replacement obligation has a boundary and absence
  evidence, or an explicit `None` finding;
- read relevant current Specs and impacted application/package rules; and
- identify E2E, fixture, credential, and external prerequisites.

Return to `feature-design` when Requirements, ADR, Design authority, approval, or a
material decision is incomplete. Do not reconstruct missing product or design
intent in an implementation plan.

## Phase 1: Create the implementation plan

Plans decompose approved Design mechanisms into execution scope. They never create
product or Design authority.

Before writing the plan:

1. identify approved mechanism IDs, workstreams, dependencies, interfaces, paths,
   validation, and removal obligations;
2. assign one exact independent reviewer and distribute that reviewer identity to
   every implementation owner; add a specialist only for an explicit review gap
   that reviewer cannot cover; and
3. limit implementation discovery to assigned paths, approved mechanisms,
   interfaces, tests, dependencies, risks, validation, and blockers; and
4. classify new findings:
   - local detail within an approved contract → plan it;
   - product scope or user-visible contract change → return to Requirements;
   - new material mechanism or decision → return to `feature-design`;
   - unsupported mechanism → omit it.

The tracked multi-phase plan must contain:

- links to Requirements, ADR, and approved Design;
- approved mechanism IDs and authority references;
- PR phases, dependencies, interfaces, integration boundaries, and owners;
- context checkpoints and the exact reviewer;
- data, API, runtime, test, E2E, fixture, and prerequisite work;
- removal obligations and absence verification;
- spec impact, rollout, external actions, blockers, and plan cleanup; and
- `Design delta: None`.

Keep phase summaries reviewable; leave file-level execution details to each phase
plan. If discovery requires a material Design change, update and reapprove Design
before continuing.

## Mandatory phase execution plan

Before implementation begins for a phase, read
[references/phase-execution-plan-template.md](references/phase-execution-plan-template.md)
and add a tracked phase plan to that phase branch.

The plan must bind the phase to approved mechanism IDs and authority references,
set `Design delta: None`, assign non-overlapping paths and interfaces, include
removal obligations, define integration and validation, and record the scope-drift
and context checkpoints.

Report the complete phase plan, then start immediately only while `Design delta`
remains `None`.

## Execution ownership and context

- The primary agent owns orchestration, shared decisions, assigned implementation,
  reviewer assignment, phase progression, and final integration.
- Implementation owners stay within assigned paths and interfaces, run focused
  checks, and request the exact reviewer directly.
- The reviewer is read-only and reviews from confirmed Requirements, accepted ADR,
  approved Design and Design Authority, the phase contract, and the current diff.
- Requirements, ADR, approved Design, and current Specs are product and design
  authority. Plans are authoritative only for approved execution scope, ownership,
  paths, ordering, and validation.

At phase boundaries, record completed behavior, changed interfaces, evidence,
remaining scope, relevant paths, risks, and blockers. Reuse an active role only
while its context remains relevant and compact; record role changes and redistribute
the exact reviewer identity. Update incomplete execution decomposition in the plan;
return product intent or a material mechanism to `feature-design`. While waiting,
prepare later inputs without starting later-phase work; silence is not progress.

## Phase 2: Implement each phase

For each phase:

1. create the stacked branch and tracked phase plan;
2. confirm approved mechanism IDs, authorities, owners, paths, interfaces, and
   dependencies;
3. implement workstreams and assigned Design removal obligations in dependency
   order;
4. check both directions of scope drift:
   - approved behavior or removal work is missing; or
   - the diff adds a material mechanism absent from Design Authority;
5. remove unrelated, unauthorized, or later-phase changes and update current Specs
   when a behavior change cannot wait for spec promotion;
6. have each owner run focused checks and request one read-only review from the
   assigned reviewer;
7. batch required corrections, apply the `/code-review` re-review criteria, and run
   affected checks; when re-review is required, the same owner directly requests it
   from the same reviewer;
8. have the primary agent verify integration and run final validation on the stable
   diff; reuse evidence only while the diff is unchanged, prerequisites are fresh,
   and the environment is equivalent; and
9. record the checkpoint, commit, and open the phase PR before the next phase.

A phase may refine local implementation details within approved contracts. It may
not add material behavior, state, configuration, contracts, fallbacks,
compatibility paths, failure behavior, operational modes, authority, or sources of
truth. Feasibility, reversibility, convention, or low risk does not change this
boundary.

Design-required removal belongs in its owning implementation phase, normally the
phase that activates the replacement. Use an explicit later phase only when an
approved dependency requires the old path temporarily.

## Phase 3: Validate

Before spec promotion, record:

- commands, environment, test results, and E2E evidence;
- fixture and prerequisite validation;
- failures found and fixes applied;
- implemented behavior versus current Specs;
- implemented material mechanisms versus Design Authority, including missing and
  unauthorized behavior; and
- completed removal obligations and absence evidence.

Fix discovered bugs in the validation PR or responsible earlier phase. Rerun only
evidence invalidated by the correction; rerun the full matrix when it crosses
interfaces or shared behavior. Apply `/code-review` re-review criteria and rebase
dependent branches when an earlier phase changes. When re-review is required, the
implementation owner directly requests the existing independent reviewer.

## Phase 4: Promote Specs

Run `/spec-review` and update current Specs. Mark Requirements and Design with the
same `implemented` date only after implementation and validation are complete.
Keep implemented Requirements, accepted ADRs, and Designs immutable.

If validation reveals an unrecorded material decision or mechanism, return to
`feature-design` and complete authority, feasibility, and approval before marking
the snapshot implemented.

## Phase 5: Clean up plans

After implementation, validation, and spec promotion, remove the feature's
multi-phase and phase execution plans. The remaining sources of truth are current
Specs, immutable implemented Requirements, accepted ADRs, useful historical
Designs, and code.

Cleanup PRs remove stale plan documents and references only. All Design-required
implementation removals must already be complete in their owning phases.

## Stack operations

Use the `stacked-prs` workflow for rebasing, retargeting, or merging stack branches.
Create each planned PR before waiting on CI, merge front to back, and preserve clean
worktrees and dependent bases. Use `--force-with-lease` for branch rewrites, and
retarget dependent PRs before deleting their base branch.

## Output expectations

When starting shipping, report Requirements, Design, implementation plan, owners,
reviewer, approved mechanism IDs, `Design delta: None`, removal obligations, stack
shape, validation matrix, and blockers.

Before each phase, report the complete tracked phase plan. After each phase, report
the PR, branch/base, completed scope, authority and drift result, removals, review,
validation, checkpoint, and next branch.

## Guardrails

- Do not inflate small work into a stack.
- Do not implement before confirmed Requirements, accepted ADR, and matching Design
  approval.
- Plans never create Design authority; every phase starts with `Design delta: None`.
- Return new material decisions to `feature-design` and keep local details
  agent-owned.
- Keep implementation and independent review separate and use the exact reviewer.
- Do not start the next phase before opening the current phase PR.
- Keep snapshot basenames aligned and generated clients source-generated.
- Remove temporary plans only after validated spec promotion.
- Keep tracked documentation and GitHub-facing text in English.
