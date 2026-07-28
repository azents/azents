---
name: ship-feature
description: "Ship a large, multi-phase feature after Requirements and design discussion are complete. Convert the approved Requirements, ADR, and design into an implementation plan and stacked PRs for phased delivery. Use when: (1) a large feature design is complete and the user says to implement, (2) the user invokes 'ship-feature' for phased delivery, (3) a design document requires multiple implementation phases. Use one focused PR instead for simple fixes and small, self-contained changes."
---

# Ship Feature Workflow

Use this workflow for large features that require multiple reviewable delivery phases after design is complete.

## Choose the delivery shape

Before creating plans or branches, choose the delivery shape based on reviewability, dependencies, validation, and rollout needs rather than an arbitrary line count.

- Use stacked PRs when the feature has multiple independently reviewable phases, sequential dependencies, cross-cutting validation, or rollout work that benefits from separate boundaries.
- Use one focused PR for bug fixes, maintenance changes, and small self-contained features that remain reviewable end to end.
- Include all required tests, generated artifacts, and spec or documentation updates in that single PR.
- Do not create separate design, plan, validation, spec-promotion, or cleanup PRs only to match this workflow.

For work that requires phased delivery, use this stacked PR series: approved Requirements/ADR/design baseline → implementation plan → phased implementation → validation → spec promotion → cleanup.

## PR stack structure

Use a consistent title prefix so reviewers can recognize the series.

```text
{feature-name} [1/N]: Design baseline
{feature-name} [2/N]: Implementation plan
{feature-name} [3/N]: Phase 1 — {phase summary}
{feature-name} [4/N]: Phase 2 — {phase summary}
...
{feature-name} [N-1/N]: Spec promotion
{feature-name} [N/N]: Cleanup
```

Recommended stack:

| Order | PR | Contents |
| --- | --- | --- |
| 1 | Design baseline | Approved Requirements, ADR, and design under the project-approved `docs/` locations |
| 2 | Implementation plan | Multi-phase plan under the project's documentation plans directory, including validation matrix and fixture prerequisites |
| 3..N-3 | Phase implementation | Mandatory phase execution plan, code, and tests. Include frontend work as one or more implementation phases when needed |
| N-2 | E2E/testenv validation | Run planned E2E and fixture/prerequisite validation, record commands/environment/evidence, compare implementation against current specs, and fix discovered issues |
| N-1 | Spec promotion | Run `/spec-review`, mark design as implemented when appropriate, update specs, and propose ADRs if needed |
| N | Cleanup | Remove stale implementation plan documents after the feature is implemented and specs are current |

Store the multi-phase implementation plan and every phase execution plan in the
project's documentation plans directory. For Azents, use `docs/azents/plans/`.
Create the directory when needed; cleanup may remove it when no tracked plans
remain.

## Phase 0: Confirm readiness

Before implementation:

- Identify the approved Requirements, accepted ADR, and approved primary Design.
- Confirm all three use the same canonical snapshot ID and basename.
- Confirm the design traces every requirement through accepted ADR decisions or explicit conventional implementation choices.
- Confirm non-goals and boundaries.
- Read relevant specs under `docs/azents/spec/`.
- Read relevant ADRs only for rationale or hard constraints.
- Identify impacted apps/packages and project rules.
- Confirm whether the feature needs E2E coverage, fixtures, credentials, or external prerequisites.

If Requirements are missing or unconfirmed, the core document basenames do not match, the ADR is missing, or the Design still has open product decisions, return to `feature-design` first. Current Azents core documents must use dated shared snapshot basenames; do not create numbered ADR files or treat legacy numbered ADRs as current records.

## Phase 1: Choose execution roles and create the implementation plan

After the Design is approved:

1. Keep implementation with the primary agent by default.
2. Delegate only work that can run independently in parallel without overlapping
   paths or shared interface decisions, or that needs isolated specialization.
3. Assign one independent reviewer before the first review. Record the exact
   agent name or path and give it to every implementation owner. Add a specialist
   only for an explicit review requirement the primary reviewer cannot cover.
4. Have the primary agent discover primary-owned scope. Limit delegated
   discovery to the assigned paths, interfaces, tests, dependencies, risks,
   validation, and blockers.
5. Have the primary agent create the tracked multi-phase plan from the approved
   documents and concise delegated discovery reports.

Reuse delegated owners and the reviewer while their context remains relevant
and compact. At each phase boundary, use the checkpoint and review evidence to
continue, reset, or reassign them. Record every role change and redistribute an
updated reviewer path before the next review.

Create the multi-phase implementation plan as a tracked document.

The plan must include:

- Feature summary and Requirements, ADR, and Design links
- PR phases, dependencies, and parallelization boundaries
- Execution roster for primary-owned work, delegated work, reviewer, and
  context checkpoints
- Data/API/runtime changes, test strategy, E2E matrix, and fixture prerequisites
- Blockers, external actions, spec impact, rollout, and cleanup

Do not put file-by-file implementation details for every phase in the multi-phase
plan. Every implementation PR must add its own phase execution plan before code
implementation begins.

## Mandatory phase execution plan gate

Before editing implementation code or delegating implementation work for a
phase, create a separate tracked phase execution plan document.

Keep the phase plan in the implementation PR branch. A phase summary in the
multi-phase plan, chat transcript, task prompt, or PR body is not a substitute.

Use this required structure:

```markdown
## Phase Execution Plan

- Phase: `<number and name>`
- Branch/base: `<branch>` → `<base>`
- PR boundary: `<deliverable>`
- Inputs: `<completed dependencies>`
- Deliverables: `<observable outcomes>`
- Non-goals: `<explicit exclusions>`
- Interfaces: `<contracts fixed before parallel work>`

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... | ... |

- Integration order: `<sequence>`
- Independent review: `<scope, criteria, inputs, output>`
- Final validation: `<commands>`
- Scope-drift check: `<diff and non-goal comparison>`
- Context checkpoint: `<completed behavior, changed interfaces, evidence, remaining scope, relevant paths, risks>`
```

Report the plan when starting the phase, then begin implementation immediately
unless it exposes a product decision that requires requester confirmation.

### Execution boundaries

- The primary agent owns orchestration, shared decisions, primary-owned
  implementation, reviewer assignment, and final integration.
- Delegated owners work only within their phase-plan paths and interfaces. Run
  them in parallel only when dependencies are satisfied and paths do not overlap.
- Every implementation owner runs focused checks and directly requests the
  assigned reviewer.
- The reviewer starts from the phase contract and diff at review time, remains
  read-only, and reports to the requesting owner.

### Handoff and context control

- Use tracked Requirements, ADR, Design, specs, and plans as authoritative
  sources. Give each subagent only the relevant sections, paths, interfaces,
  inputs, outputs, non-goals, rules, and validation commands.
- Update the plan when the contract is incomplete. Return unresolved product
  intent to `feature-design`.
- Set a time, turn, tool-call, or milestone checkpoint for delegated and review
  work. At that boundary, collect progress, remaining scope, validation,
  blockers, and repeated failures; then continue, rescope, reset, or stop.
- Before opening a phase PR, record completed behavior, changed interfaces,
  validation evidence, remaining scope, relevant paths, risks, and blockers.
- Start the next phase from this checkpoint and review evidence. Continue a
  role only while its retained context remains useful and compact.
- While waiting, prepare later-phase inputs without starting later-phase work or
  advancing the stack. Silence alone is not evidence of progress.

## Phase 2: Implement phases as stacked PRs

For each implementation phase:

1. Create the stacked branch, read project rules, and write the phase plan.
2. Assign each workstream to the primary agent or a qualified delegated owner.
3. Implement the workstreams and integrate them in dependency order.
4. Update specs when the phase changes current behavior and cannot wait for spec
   promotion. Remove unrelated or later-phase changes.
5. Have each owner run focused checks and directly request review from the exact
   assigned reviewer with the relevant contract, scope, diff, and rules.
6. Have the reviewer perform one read-only review. Batch required corrections,
   run affected checks, and use `/code-review` for targeted re-review decisions.
   When required, the implementation owner directly requests the same reviewer.
7. Have the primary agent verify scope, integration, and validation evidence.
   Apply affected checks and re-review criteria to any resulting diff change.
8. Run final validation once on the stable integrated diff. Reuse evidence only
   while the diff is unchanged, prerequisite snapshots are fresh, and the
   environment is equivalent. Refresh invalidated checks and required E2E
   evidence.
9. Record the phase checkpoint, commit, and open the PR before the next phase.

Keep each phase reviewable. Do not mix unrelated refactors, cleanup, or future phases.

## Phase 3: Validation PR

Run the planned validation before spec promotion.

Include:

- Commands run
- Environment details
- Test results
- E2E evidence
- Fixture/prerequisite validation results
- Any failures found and the fixes applied
- A strict comparison table between implemented behavior and current specs, including missing implementation or spec drift

If validation finds a bug, address it in the validation PR or responsible
earlier phase and run affected checks. Repeat only validation entries whose
evidence may have been invalidated; rerun the full matrix when the correction
crosses interfaces or shared behavior. Use the `/code-review` re-review criteria
and, when required, have the implementation owner directly request targeted
re-review from the existing independent reviewer. Then have the primary agent
perform final verification and rebase following branches when an earlier phase
changes.

## Phase 4: Spec promotion PR

Run `/spec-review` and update current specs under `docs/azents/spec/`.

Also:

- Add the same `implemented` date to the Requirements snapshot and Design only when the implementation is complete and verified.
- Treat the implemented Requirements, accepted ADR, and Design as one immutable snapshot. Record later product or design changes in a new snapshot.
- If validation discovers an unrecorded hard-to-reverse decision, return to `feature-design` and record it before marking the snapshot implemented.
- Keep implemented/adopted ADRs immutable.

## Phase 5: Cleanup PR

After the feature is implemented, validated, and reflected in current specs,
remove the multi-phase implementation plan and every phase execution plan for
the feature. The documentation plans directory may disappear when no tracked
plans remain. The source of truth becomes:

- Current specs
- Immutable implemented Requirements snapshots
- Adopted ADRs
- Implemented design documents when they still carry useful historical rationale
- Actual code

Cleanup PRs should only remove stale plan documents and related references. Do not mix behavior changes or refactors.

## Stacked PR operations

Use the `stacked-prs` workflow when rebasing, retargeting, or merging stacked branches.

Rules:

- Merge from front to back only.
- Use `--force-with-lease` for stack branch rewrites.
- Retarget dependent PR bases before deleting base branches.
- Preserve a clean working tree before rebase/cherry-pick operations.

## Output expectations

When starting the shipping workflow, report:

```markdown
## Ship Feature Plan

- Requirements: `<path>` (`<short-id>`)
- Design: `<path>`
- Multi-phase implementation plan: `<path under the documentation plans directory>`
- Execution roles: `<primary-owned work, delegated owners, and independent reviewer>`
- Stack prefix: `{feature-name}`
- Planned PRs:
  1. Design
  2. Implementation plan
  3. Phase 1 — ...
- Validation matrix: <summary>
- Known blockers: <none or list>
```

When starting each implementation phase, report the complete `Phase Execution
Plan` block before editing implementation code or giving phase work to the
implementation role owners.

For each completed phase, report:

- PR URL
- Branch/base and phase plan
- Completed scope and scope-drift result
- Execution roles, handoffs, and next-phase context decision
- Review, re-review, and final validation results
- Next stacked branch

## Guardrails

- Do not inflate a simple fix or small self-contained change into a PR stack; use one focused PR.
- Do not start implementation without confirmed Requirements, a design, or explicit user approval.
- Do not edit phase implementation code or assign implementation subagents before
  the mandatory phase execution plan is stored in the documentation plans
  directory and reported.
- Keep phase progression and role-level orchestration with the primary agent.
- Keep implementation and independent review separate. Use the exact reviewer
  assigned by the primary agent and the `/code-review` re-review criteria.
- Do not start the next phase before the current phase PR is created.
- Do not ship an Azents feature when its new-format Requirements, ADR, and primary Design use different basenames.
- Do not collapse a large feature into one PR when phased delivery is expected.
- Do not leave stale plan documents after implementation is complete.
- Do not update generated clients manually; regenerate them from OpenAPI when API routes or schemas change.
- Keep all tracked docs, PR titles, PR bodies, comments, and examples in English.
