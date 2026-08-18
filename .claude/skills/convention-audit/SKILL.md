---
name: convention-audit
description: Audit repository code against `.claude/conventions/` in full or incremental mode while maintaining bounded coverage checkpoints. Use when asked to inspect convention violations, establish a complete convention baseline, continue a recurring or daily convention audit, or report and safely fix convention drift.
---

# Convention Audit

Audit tracked repository files against the convention bodies referenced by
`.claude/rules/*-conventions.md`. Keep only coverage checkpoints in
`.claude/convention-audit-state.json`; keep findings and reasoning out of that file.

Run commands from the repository root.

Keep the audit checkout at the planned commit until checkpoint completion. If fixes
are needed, create them in a separate worktree so that opening a fix pull request does
not move or dirty the audit checkout.

## Select a mode

### Full audit

Use full mode when the requester asks for a complete audit, when establishing the
first baseline, or when the change checkpoint is absent.

Full mode checks every current audit range at one target commit. Do not complete the
plan unless every planned range was inspected.

```bash
python .agents/skills/convention-audit/scripts/audit_state.py plan \
  --mode full \
  --output /tmp/convention-audit-plan.json
```

### Incremental audit

Use incremental mode for recurring audits.

Incremental mode checks:

1. every tracked file changed since the last successful change checkpoint; and
2. a bounded number of full ranges whose convention revision is stale, that have
   never been checked, or that were checked least recently.

```bash
python .agents/skills/convention-audit/scripts/audit_state.py plan \
  --mode incremental \
  --range-limit 1 \
  --output /tmp/convention-audit-plan.json
```

Incremental mode requires a completed full audit checkpoint. Never invent or
manually advance the starting commit.

## Inspect the plan

The plan is disposable execution data and must stay outside the repository.

- `changed_checks` contains exact changed files grouped by automatically assigned
  repository range.
- `full_ranges` contains every range for full mode.
- `legacy_ranges` contains the bounded full-range work selected for incremental
  mode.
- Each range includes its exact tracked files and the convention body paths that may
  apply.

New files require no manual shard assignment. The planner derives a path-based base
range and a deterministic hash bucket from each tracked path. It reconciles added or
removed ranges automatically, and each bucket remains bounded as the repository
grows.

For each planned range:

1. Read the applicable `AGENTS.md` files and convention index.
2. Use convention titles to identify rules relevant to the files under inspection.
3. Read the relevant convention bodies before judging compliance. Do not bulk-read
   unrelated bodies.
4. Run deterministic checks first: existing linters, type checkers, tests, targeted
   grep, or AST-aware tools.
5. Perform semantic inspection only where automated evidence is insufficient.
6. Ground every finding in an exact convention and code location.

Inspect only the exact files listed for each changed-file or full-range check.

Do not treat generated, vendored, or explicitly excluded code as manually editable.
Follow the owning path's repository instructions when deciding whether a convention
applies.

## Report and fix

Report inspection details to the current conversation context. Use this structure:

```markdown
## Convention Audit

- Mode: full | incremental
- Target commit: `<sha>`
- Ranges checked: `<ranges>`
- Changed files checked: `<count>`

### Findings
- **<severity> — `<file>:<line>` — `<convention path>`**
  <grounded explanation and recommended correction>

### Result
<finding count, fixes created, and remaining uncertainty>
```

If there are no findings, state that explicitly. Do not create placeholder issues or
changes.

Create focused pull requests only for findings whose corrections are clear and
low-risk. Keep uncertain findings in the conversation report without editing code.
Never place findings, excerpts, reasoning, pull request identifiers, or conversation
identifiers in the audit state file.

## Complete the checkpoint

Advance the checkpoint only after:

- all work represented by the plan is complete;
- the result has been successfully reported to the current conversation; and
- any intended pull request has been created successfully.

The planner and completion command reject tracked working-tree or index changes.
After completion writes the state file, submit that checkpoint change through the
normal pull request workflow. It may be copied into a related focused fix pull
request, or submitted as a state-only pull request when there is no code correction.

```bash
python .agents/skills/convention-audit/scripts/audit_state.py complete \
  --plan /tmp/convention-audit-plan.json
rm /tmp/convention-audit-plan.json
```

Do not complete a partially executed or failed plan. The completion command rejects
plans when the repository HEAD, convention revision, or state file changed after
planning.

## State boundaries

`.claude/convention-audit-state.json` is a bounded snapshot, not a run log.

It stores only:

- the latest successfully checked commit and time for changed files;
- current repository ranges; and
- each range's latest checked commit, time, and convention revision.

It replaces checkpoints in place and prunes ranges that no longer exist. Inspection
content belongs in the current conversation, while code corrections belong in pull
requests.
