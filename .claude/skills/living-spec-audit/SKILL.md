---
name: living-spec-audit
description: Audit current implementation against `docs/azents/spec/**/*.md`, update Living Specs to match reachable implementation behavior, and maintain bounded recurring coverage checkpoints. Use for full or recurring spec-drift audits, periodic Living Spec synchronization, stale `code_paths` checks, or requests to make specs reflect the implementation without changing code.
---

# Living Spec Audit

Compare Living Specs with reachable current implementation behavior. Treat the
implementation as authoritative and correct only `docs/azents/spec/**/*.md`.
Never change implementation as an audit correction.

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

1. every current implementation file changed since the last successful change
   checkpoint;
2. deleted implementation paths and changed or deleted Living Specs;
3. every current `code_paths` entry that matches no tracked file; and
4. enough bounded legacy ranges to target one complete rotation every 14 days.

```bash
python .agents/skills/living-spec-audit/scripts/audit_state.py plan \
  --mode incremental \
  --rotation-days 14 \
  --output /tmp/living-spec-audit-plan.json
```

Incremental mode may bootstrap from an empty checkpoint. The first completed plan
establishes the change checkpoint while uninspected ranges remain visibly
unchecked. Never invent or manually advance a starting commit.

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
- `rotation_ranges` contains bounded legacy work for incremental mode.
- Each range contains exact files, matched specs, per-file spec mappings, and
  unmapped implementation files.

New implementation files receive a deterministic path-based range automatically.
Unmapped files are findings to classify, not files to silently discard.

For every planned range or changed check:

1. Read `docs/azents/AGENTS.md` and the applicable path instructions.
2. Run mechanical checks first: missing paths, moved symbols, routes, models,
   configuration keys, state values, and deleted behavior.
3. Inspect reachable production call paths. Use tests as evidence, not as authority.
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

If reachable behavior is clear but appears defective, document the actual behavior
and report the suspected defect separately. If competing implementation paths make
the actual behavior uncertain, do not invent spec text; report the ambiguity and
create a verification issue when durable handoff is required.

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
required work.

After completion writes the state file, submit that checkpoint through the normal
pull request workflow. Include it in the spec correction PR or use a state-only PR
when no documentation correction exists.

## State boundaries

`.claude/living-spec-audit-state.json` is a bounded checkpoint snapshot, not a run
log. It stores only the latest changed-file checkpoint and each current range's
latest checked commit, time, and scope revision. It reconciles new or removed ranges
and replaces checkpoints in place.
