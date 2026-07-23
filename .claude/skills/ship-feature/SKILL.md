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
| 2 | Implementation plan | Multi-phase plan under the project-approved `plans/` location, including validation matrix and fixture prerequisites |
| 3..N-3 | Phase implementation | Mandatory phase execution plan, code, and tests. Include frontend work as one or more implementation phases when needed |
| N-2 | E2E/testenv validation | Run planned E2E and fixture/prerequisite validation, record commands/environment/evidence, compare implementation against current specs, and fix discovered issues |
| N-1 | Spec promotion | Run `/spec-review`, mark design as implemented when appropriate, update specs, and propose ADRs if needed |
| N | Cleanup | Remove stale implementation plan documents after the feature is implemented and specs are current |

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

## Phase 1: Create the implementation plan

Create a multi-phase implementation plan in the project-approved planning location. The plan must include:

- Feature summary, Requirements short ID, ADR links, and design link
- Phase list with explicit PR boundaries
- Dependencies between phases
- Dependency and parallelization map identifying sequential phases and independent workstreams
- Data/API/runtime changes by phase
- Test strategy by phase
- E2E primary validation matrix for all added or changed user-facing behavior
- Fixture/prerequisite support requirements and why they are needed
- Blockers, missing prerequisites, or external/manual actions, including which phase they block
- Spec impact candidates
- Rollout and cleanup notes

Do not put file-by-file implementation details for every phase in the multi-phase
plan. Every implementation PR must add its own phase execution plan before code
implementation begins.

## Mandatory phase execution plan gate

Before editing implementation code or delegating implementation work for a phase,
create a phase execution plan in the implementation PR branch. Do not treat the
phase summary in the multi-phase plan as a substitute.

The phase execution plan must define:

- Phase objective, branch, base branch, and intended PR boundary
- Inputs and dependencies from previous phases
- Deliverables and observable completion criteria
- Explicit non-goals, including later-phase work that must not enter the PR
- Data, API, runtime, and generated-artifact interfaces that the phase owns or
  consumes
- Workstreams with one owner, owned paths, inputs, outputs, and validation for
  each task
- Dependency order and which workstreams may run in parallel
- Integration order and shared files reserved for the integrating agent
- Required format, lint, type, unit, integration, migration, build, and other
  phase-specific validation commands
- Scope-drift check to run before commit and PR creation

Use this concise structure:

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
- Final validation: `<commands>`
- Scope-drift check: `<diff and non-goal comparison>`
```

Report the plan when starting the phase, then begin implementation immediately
unless it exposes a product decision that requires requester confirmation.

### Parallel implementation rules

- Use implementation subagents for concrete, bounded workstreams after the phase
  plan fixes their contracts and ownership.
- Run workstreams in parallel only when their dependencies are satisfied and
  their owned paths do not overlap.
- Assign each path to one owner at a time. Reserve shared integration files for
  the integrating agent.
- Put explicit inputs, outputs, non-goals, owned paths, and validation commands
  from the phase plan into every implementation subagent task.
- Do not let a subagent implement a later phase, broaden an interface, or edit an
  unowned path. Stop and revise the phase plan first when scope must change.
- Use the primary agent for planning, interface decisions, integration, and final
  verification. Use implementation subagents for the bounded implementation
  described by the plan.

## Phase 2: Implement phases as stacked PRs

For each implementation phase:

1. Create a branch stacked on the previous phase branch.
2. Read relevant project instructions and conventions.
3. Write and report the mandatory phase execution plan.
4. Verify that interfaces and ownership are sufficient for safe parallel work.
5. Delegate bounded workstreams and implement only that phase's scope.
6. Add or update tests for the phase.
7. Update specs in the same PR only when the phase directly changes current behavior and cannot wait for the spec-promotion phase.
8. Compare the diff against the phase deliverables, owned paths, and non-goals.
9. Move later-phase or unrelated work out of the branch before committing.
10. Run the phase's final validation commands.
11. Commit and open the PR before starting implementation for the next phase.

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

If validation finds a bug, fix it in the validation PR or in the responsible earlier phase, then rebase following branches.

## Phase 4: Spec promotion PR

Run `/spec-review` and update current specs under `docs/azents/spec/`.

Also:

- Add the same `implemented` date to the Requirements snapshot and Design only when the implementation is complete and verified.
- Treat the implemented Requirements, accepted ADR, and Design as one immutable snapshot. Record later product or design changes in a new snapshot.
- If validation discovers an unrecorded hard-to-reverse decision, return to `feature-design` and record it before marking the snapshot implemented.
- Keep implemented/adopted ADRs immutable.

## Phase 5: Cleanup PR

After the feature is implemented, validated, and reflected in current specs, remove stale implementation plan documents. The source of truth becomes:

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
- Stack prefix: `{feature-name}`
- Planned PRs:
  1. Design
  2. Implementation plan
  3. Phase 1 — ...
- Validation matrix: <summary>
- Known blockers: <none or list>
```

When starting each implementation phase, report the complete `Phase Execution
Plan` block before editing implementation code or assigning implementation
subagents.

For each completed phase, report:

- PR URL
- Branch/base
- Phase plan path
- Scope completed
- Scope-drift result
- Validation run or skipped reason
- Next stacked branch

## Guardrails

- Do not inflate a simple fix or small self-contained change into a PR stack; use one focused PR.
- Do not start implementation without confirmed Requirements, a design, or explicit user approval.
- Do not edit phase implementation code or assign implementation subagents before
  the mandatory phase execution plan is written and reported.
- Do not start the next phase before the current phase PR is created.
- Do not ship an Azents feature when its new-format Requirements, ADR, and primary Design use different basenames.
- Do not collapse a large feature into one PR when phased delivery is expected.
- Do not leave stale plan documents after implementation is complete.
- Do not update generated clients manually; regenerate them from OpenAPI when API routes or schemas change.
- Keep all tracked docs, PR titles, PR bodies, comments, and examples in English.
