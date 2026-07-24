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

## Phase 1: Assemble the delivery team and create the implementation plan

After the Design is approved, create one stable delivery team for the complete
feature stack before implementation planning begins.

1. Identify the smallest set of durable implementation workstreams required by
   the approved Design. Default to one implementation role. Split roles only for
   independent domains such as frontend, backend, runtime, infrastructure, or
   testenv work that benefit from separate ownership.
2. Create one implementation subagent for each durable workstream and one
   independent review subagent for the complete stack. Assign roles for the
   feature, not for individual phases. Add a specialist reviewer only for an
   explicit review requirement that the primary reviewer cannot cover.
3. Brief each role from the approved Requirements, ADR, Design, relevant specs,
   applicable project rules, and its initial role boundary.
4. Ask each implementation role to perform read-only codebase discovery and
   report relevant paths, interfaces, existing tests and fixtures, dependencies,
   risks, validation commands, and genuine blockers. Do not allow implementation
   edits before the phase execution plan gate.
5. Ask the independent reviewer to perform read-only baseline discovery and
   prepare review risks and criteria without contributing implementation or
   owning implementation paths.
6. While the role agents perform discovery, have the primary agent draft the
   multi-phase implementation plan. Reconcile the discovery reports before
   finalizing the plan.

Keep each implementation role and the independent reviewer assigned to the same
subagent throughout the stack. A phase change alone is never a reason to create
a new subagent. Add or replace a role only when a genuinely new durable
workstream appears, an existing role becomes unavailable, or its ownership is
no longer compatible with the plan. Record the reason and ownership change. If
no compatible owner is available, report the blocker instead of silently
collapsing or combining roles.

Create the multi-phase implementation plan as a tracked document.

The plan must include:

- Feature summary, Requirements short ID, ADR links, and design link
- Phase list with explicit PR boundaries
- Dependencies between phases
- Dependency and parallelization map identifying sequential phases and independent workstreams
- Stable delivery team roster identifying each role, assigned subagent,
  persistent ownership, planned phases, and any approved reassignment
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
```

Report the plan when starting the phase, then begin implementation immediately
unless it exposes a product decision that requires requester confirmation.

### Document-based handoff

Treat the approved Requirements, ADR, Design, multi-phase implementation plan,
and current phase execution plan as the handoff contract for every subagent.

- Keep each handoff complete enough for an implementation or review subagent to
  perform its assigned work without relying on conversation history.
- For initial discovery, provide the approved core documents, relevant specs,
  project rules, and role boundary. After planning, every subagent task must also
  cite the relevant plans and restate its workstream, owned paths, inputs,
  outputs, non-goals, and validation.
- When the written contract lacks implementation detail, update the multi-phase
  or current phase plan before assigning or continuing work.
- When Requirements, ADR, or Design intent is missing or inconsistent, return
  to `feature-design` and requester confirmation instead of resolving product
  intent in an implementation plan.
- Treat the written contract as authoritative even when the same subagent
  continues across phases.
- For each new phase, the current phase plan replaces prior task-level scope,
  owned paths, non-goals, and validation instructions. Requirements, ADR,
  Design, and the multi-phase plan remain the higher-level contract.

### Delivery role boundaries

- The primary agent is the sole orchestrator for this workflow. It owns
  planning, interface and scope decisions, coordination, implementation
  verification, accepted review-finding integration, and final verification.
- The primary agent alone controls phase progression and role-level
  orchestration. It creates, assigns, coordinates, continues, replaces, or
  stops implementation owners and independent reviewers, and it decides
  workstream reassignment.
- Implementation subagents own bounded feature implementation and focused
  validation defined by the phase execution plan and report their results to
  the primary agent.
- A separate subagent that did not participate in implementation performs the
  independent code review after primary-agent verification and reports its
  findings to the primary agent.
- The primary agent applies accepted review findings directly. When a finding
  requires workstream-level reimplementation rather than a localized review
  fix, delegate that reimplementation to an implementation subagent and prefer
  the original implementer.

### Long-running subagent work

- Assume implementation and review workstreams may take a long time. Never ask
  a subagent to finalize early, shorten validation, or return a partial result
  merely because the primary agent is waiting.
- When coordination needs visibility, ask for a progress update covering
  completed scope, remaining scope, current validation, and genuine blockers.
  Explicitly tell the subagent to continue the complete written contract after
  reporting progress.
- While waiting, use primary-agent time to inspect repository state, research
  the next phase, identify applicable conventions, and prepare future phase-plan
  inputs. Do not edit later-phase implementation code, assign later-phase
  implementation, create the next phase branch, or advance the stack before the
  current phase PR exists.
- Treat silence or a long runtime as ongoing work, not as evidence that scope
  should be reduced. Wait for the complete workstream or a genuine blocker.

### Parallel implementation rules

- Continue the stable implementation role owners for concrete, bounded
  workstreams after the phase plan fixes their contracts and ownership.
- Run workstreams in parallel only when their dependencies are satisfied and
  their owned paths do not overlap.
- Assign each path to one owner at a time. Reserve shared integration files for
  the integrating agent.
- Put explicit inputs, outputs, non-goals, owned paths, and validation commands
  from the phase plan into every implementation subagent task.
- Do not let a subagent implement a later phase, broaden an interface, or edit an
  unowned path. Stop and revise the phase plan first when scope must change.

## Phase 2: Implement phases as stacked PRs

For each implementation phase:

1. Create a branch stacked on the previous phase branch.
2. Read relevant project instructions and conventions.
3. Write and report the mandatory phase execution plan.
4. Verify that interfaces and ownership are sufficient for safe parallel work.
5. Have the primary agent continue the existing implementation role owners that
   participate in this phase. Give each owner the current phase plan and its
   bounded implementation and test work.
6. Create a new role owner only when the stable delivery team rules require an
   approved addition or replacement, then update the multi-phase and phase plans
   before implementation continues.
7. Confirm completed workstreams satisfy their documented interfaces and
   dependency order.
8. Update specs in the same PR only when the phase directly changes current behavior and cannot wait for the spec-promotion phase.
9. Compare the diff against the phase deliverables, owned paths, and non-goals.
10. Move later-phase or unrelated work out of the branch before committing.
11. Have the primary agent run the phase's verification commands.
12. Have the primary agent continue the existing independent reviewer after
    verification and provide the current phase contract and diff.
13. Have the primary agent apply accepted review findings directly. Delegate
    only workstream-level reimplementation, preferably to the original
    implementation subagent.
14. Have the primary agent verify the fixes and ask the same independent
    reviewer to recheck addressed findings.
15. Re-run affected checks and the phase's final validation commands.
16. Commit and open the PR before starting implementation for the next phase.

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

If validation finds a bug, assign the behavior correction to the existing
implementation role owner in the validation PR or responsible earlier phase.
Have the primary agent verify the correction, continue the existing independent
reviewer, apply accepted review findings, and rebase following branches when an
earlier phase changes.

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
- Stable delivery team: `<implementation role owners and independent reviewer>`
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
- Branch/base
- Phase plan path
- Scope completed
- Scope-drift result
- Implementation workstreams and the documents used for their handoff
- Stable role owners continued, added, or reassigned
- Primary-agent verification results
- Independent review result
- Accepted review fixes and final validation results
- Next stacked branch

## Guardrails

- Do not inflate a simple fix or small self-contained change into a PR stack; use one focused PR.
- Do not start implementation without confirmed Requirements, a design, or explicit user approval.
- Do not edit phase implementation code or assign implementation subagents before
  the mandatory phase execution plan is stored in the documentation plans
  directory and reported.
- Do not create phase-specific implementation or review subagents when the
  stable role owner remains available and compatible with the workstream.
- Keep implementation and independent review assigned to separate subagents.
- Keep phase progression and role-level orchestration with the primary agent.
  Implementation and review subagents do not reassign role owners, appoint
  independent reviewers, or advance the phase workflow.
- Do not start the next phase before the current phase PR is created.
- Do not ship an Azents feature when its new-format Requirements, ADR, and primary Design use different basenames.
- Do not collapse a large feature into one PR when phased delivery is expected.
- Do not leave stale plan documents after implementation is complete.
- Do not update generated clients manually; regenerate them from OpenAPI when API routes or schemas change.
- Do not pressure implementation or review subagents to finish early; ask for
  progress and research later phases while waiting.
- Keep all tracked docs, PR titles, PR bodies, comments, and examples in English.
