---
name: ship-feature
description: "Ship a feature after design discussion is complete. Convert the design into an implementation plan and stacked PRs for phased delivery. Use when: (1) design discussion is complete and the user says to implement, (2) the user invokes 'ship-feature', (3) a design document exists and must be turned into code."
---

# Ship Feature Workflow

After feature design is complete, deliver the work as a stacked PR series: design document → implementation plan → phased implementation → validation → spec promotion → cleanup.

## PR stack structure

Use a consistent title prefix so reviewers can recognize the series.

```text
{feature-name} [1/N]: Design
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
| 1 | Design document | Approved design under the project-approved `docs/` location |
| 2 | Implementation plan | Multi-phase plan under the project-approved `plans/` location, including validation matrix and fixture prerequisites |
| 3..N-3 | Phase implementation | Phase-specific plan, code, and tests. Include frontend work as one or more implementation phases when needed |
| N-2 | E2E/testenv validation | Run planned E2E and fixture/prerequisite validation, record commands/environment/evidence, compare implementation against current specs, and fix discovered issues |
| N-1 | Spec promotion | Run `/spec-review`, mark design as implemented when appropriate, update specs, and propose ADRs if needed |
| N | Cleanup | Remove stale implementation plan documents after the feature is implemented and specs are current |

## Phase 0: Confirm readiness

Before implementation:

- Identify the approved design document.
- Confirm non-goals and boundaries.
- Read relevant specs under `docs/azents/spec/`.
- Read relevant ADRs only for rationale or hard constraints.
- Identify impacted apps/packages and project rules.
- Confirm whether the feature needs E2E coverage, fixtures, credentials, or external prerequisites.

If the design is missing or still has open product decisions, return to `feature-design` first.

## Phase 1: Create the implementation plan

Create a multi-phase implementation plan in the project-approved planning location. The plan must include:

- Feature summary and design link
- Phase list with explicit PR boundaries
- Dependencies between phases
- Data/API/runtime changes by phase
- Test strategy by phase
- E2E primary validation matrix for all added or changed user-facing behavior
- Fixture/prerequisite support requirements and why they are needed
- Blockers, missing prerequisites, or external/manual actions, including which phase they block
- Spec impact candidates
- Rollout and cleanup notes

Do not put file-by-file implementation details for every phase in the multi-phase plan. Each implementation PR can add its own phase-specific plan when needed.

## Phase 2: Implement phases as stacked PRs

For each implementation phase:

1. Create a branch stacked on the previous phase branch.
2. Read relevant project instructions and conventions.
3. Implement only that phase's scope.
4. Add or update tests for the phase.
5. Update specs in the same PR only when the phase directly changes current behavior and cannot wait for the spec-promotion phase.
6. Commit and open a PR with the agreed stack title prefix.

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

- Mark the design implemented only when the implementation is complete and verified.
- Propose a new ADR when the shipped behavior includes a hard-to-reverse decision, persistent contract, or long-term operational policy.
- Keep implemented/adopted ADRs immutable.

## Phase 5: Cleanup PR

After the feature is implemented, validated, and reflected in current specs, remove stale implementation plan documents. The source of truth becomes:

- Current specs
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

- Design: `<path>`
- Stack prefix: `{feature-name}`
- Planned PRs:
  1. Design
  2. Implementation plan
  3. Phase 1 — ...
- Validation matrix: <summary>
- Known blockers: <none or list>
```

For each completed phase, report:

- PR URL
- Branch/base
- Scope completed
- Validation run or skipped reason
- Next stacked branch

## Guardrails

- Do not start implementation without a design or explicit user approval.
- Do not collapse a large feature into one PR when phased delivery is expected.
- Do not leave stale plan documents after implementation is complete.
- Do not update generated clients manually; regenerate them from OpenAPI when API routes or schemas change.
- Keep all tracked docs, PR titles, PR bodies, comments, and examples in English.
