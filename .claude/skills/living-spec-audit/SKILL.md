---
name: living-spec-audit
description: Audit current implementation against `docs/azents/spec/**/*.md`, update Living Specs to match reachable implementation behavior, and maintain bounded recurring coverage checkpoints. Use for full or recurring spec-drift audits, periodic Living Spec synchronization, stale `code_paths` checks, or requests to make specs reflect the implementation without changing code.
---

# Living Spec Audit

Compare Living Specs with reachable current implementation behavior. Treat the
implementation as authoritative after excluding unambiguous defects, and correct
only `docs/azents/spec/**/*.md`. Never change implementation as an audit correction.

Keep coverage checkpoints in `.claude/living-spec-audit-state.json`. Keep findings,
reasoning, issue identifiers, and pull request identifiers out of that state file.

Run commands from the repository root. Keep the audit checkout at the planned commit
until checkpoint completion. Make spec corrections in a separate worktree so that
the audit checkout remains fixed and clean.

## Select a mode

### Full audit

Use full mode only when the requester explicitly asks to inspect every current audit
range at one commit.

```bash
python .agents/skills/living-spec-audit/scripts/audit_state.py plan \
  --mode full \
  --output /tmp/living-spec-audit-plan.json
```

Do not complete a full plan unless every planned range was inspected.

### Incremental audit

Use incremental mode for recurring audits. It checks:

1. one existing bounded range, selected by its range checkpoint, comparing its
   mapped Living Specs with current reachable implementation; and
2. independently, commits from the 24 hours ending at plan creation, checking
   changed or deleted implementation and Living Specs for drift.

Inspect missing `code_paths` in the selected scope and classify relevant unmapped
changes. The old global change checkpoint does not extend the 24-hour window.

```bash
python .agents/skills/living-spec-audit/scripts/audit_state.py plan \
  --mode incremental \
  --output /tmp/living-spec-audit-plan.json
```

An empty range checkpoint means the range has not been audited. Do not mark
uninspected ranges complete or advance the old global change checkpoint.

Inspect rotation health with:

```bash
python .agents/skills/living-spec-audit/scripts/audit_state.py status \
  --rotation-days 14
```

## Inspect the plan

The plan is disposable execution data and must remain outside the repository.

- `changed_checks` groups exact changed implementation files by bounded range.
- `changed_specs` and `deleted_specs` identify direct Living Spec changes.
- `deleted_checks` identifies removed implementation paths and their mapped specs.
- `missing_code_paths` identifies current patterns that match no tracked file.
- `full_ranges` contains every range for full mode.
- `rotation_ranges` contains exactly one selected range for incremental mode.
- Each range contains exact files, matched specs, per-file spec mappings, and
  unmapped implementation files.

New implementation files receive a deterministic path-based range automatically.
Unmapped files are findings to classify, not files to silently discard.

For the selected range and the recent changed checks:

1. Read `docs/azents/AGENTS.md` and the applicable path instructions.
2. Run mechanical checks first: missing paths, moved symbols, routes, models,
   configuration keys, state values, and deleted behavior.
3. Inspect reachable production call paths. Do not run tests by default; use the
   minimum targeted test only when needed to resolve a specific uncertainty.
4. Compare current behavior, APIs, data models, permissions, state transitions,
   errors, recovery, and user-visible behavior with the matched specs.
5. Search adjacent callers and tests only as needed to establish actual behavior.
6. Ground every finding in exact implementation and spec locations.

For unmapped implementation files, determine whether they introduce or change
material current behavior. Add them to an existing spec's `code_paths`, create a
new spec only when a distinct current-behavior boundary exists, or record that no
Living Spec coverage is needed.

## Correct drift

For clear drift:

- rewrite the Living Spec to describe reachable current behavior;
- repair `code_paths`;
- update `last_verified_at`;
- increment `spec_version` and add a changelog entry when behavior text changes;
- delete or consolidate a stale spec rather than adding freshness/status flags; and
- create a focused pull request containing documentation corrections only.

Do not modify Requirements, accepted ADRs, implemented Designs, or implementation.
Read those documents only for terminology or historical context.

If reachable behavior is unambiguously defective, do not encode the defect as product
behavior. Preserve the existing correct Spec contract, or correct it only when the
intended behavior is established by reliable product evidence. Create a GitHub issue
for the implementation defect before completing the audit.

If competing implementation paths make the actual behavior uncertain, do not invent
spec text; report the ambiguity and create a verification issue when durable handoff
is required.

## Report

Use this concise structure:

```markdown
## Living Spec Audit

- Mode: full | incremental
- Target commit: `<sha>`
- Ranges checked: `<ranges>`
- Changed implementation files checked: `<count>`

### Drift corrected
- `<spec path>` — <implemented behavior reflected>

### Unresolved verification
- `<implementation/spec locations>` — <why behavior is not yet provable>

### Result
<spec PR, issues, no-drift result, and remaining coverage>
```

State explicitly when no drift was found. Do not create placeholder changes or
issues.

## Complete the checkpoint

Advance the checkpoint only after:

- every item represented by the plan was inspected;
- the result was successfully reported;
- every required verification issue was created; and
- every intended spec correction pull request was created.

Completion means the range was inspected, not that every finding was fixed. A
confirmed unresolved finding may advance after durable handoff succeeds.

```bash
python .agents/skills/living-spec-audit/scripts/audit_state.py complete \
  --plan /tmp/living-spec-audit-plan.json
rm /tmp/living-spec-audit-plan.json
```

The completion command rejects a dirty audit checkout, a modified or incomplete
plan, a changed HEAD, a changed state file, changed Living Spec scope, or changed
required work. It verifies plan integrity, not whether the inspection actually
occurred; the auditor remains responsible for completing the planned review.

After completion writes the state file, submit that checkpoint through the normal
pull request workflow. Include it in the spec correction PR or use a state-only PR
when no documentation correction exists.

## State boundaries

`.claude/living-spec-audit-state.json` is a bounded checkpoint snapshot, not a run
log. It retains the historical change checkpoint and each range's latest checked
commit, time, and scope revision. Incremental completion updates only the selected
range; it does not claim the older unchecked changes were reviewed.
