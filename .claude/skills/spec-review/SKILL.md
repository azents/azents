---
name: spec-review
description: "Check whether a code diff requires updates to docs/azents/spec/**/*.md. Use for: '/spec-review', '/spec-review staged', '/spec-review last', '/spec-review PR #N', or requests such as 'check spec impact'."
---

# /spec-review

Compare code changes against the current spec `code_paths` and decide which specs need updates. Specs describe only the current system. If a spec is stale or superseded, do not change its status; delete or consolidate it instead.

## Workflow

1. Select the target diff.
   - Default or `staged`: `git diff --cached --name-only`, `git diff --cached`
   - `last`: `git diff HEAD~1 --name-only`, `git diff HEAD~1`
   - `PR #N`: `gh pr diff N --name-only`, `gh pr diff N`
2. If there are no changed files, exit with `No changes to analyze`.
3. Read `docs/azents/spec/**/*.md` and glob-match changed files against frontmatter `code_paths`.
4. For each matched spec, compare the diff with the spec body and decide whether behavior, APIs, data models, permissions, or error cases changed.
5. Print a short result grouped by spec.

## Output

When there is impact:

```markdown
## Spec Impact

### docs/azents/spec/domain/agent.md
- Matched files: `python/apps/azents/src/azents/services/agent_service.py`
- Update: reflect changed agent activation conditions in `## Behavior`
- Update: refresh `last_verified_at`
```

When there is no impact:

```markdown
## Spec Impact

No spec update needed.
```

## Notes

- If a spec file itself is included in the same diff, treat it as already being updated and exclude it from additional impact suggestions.
- For pure refactors, it may be enough to update only `code_paths` or `last_verified_at` without changing the body.
- If a spec no longer describes the current system, propose deleting or consolidating it instead of changing its status.
