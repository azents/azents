---
name: spec-review
description: "Review a diff's semantic impact on the Azents Spec Wiki. Use for '/spec-review', '/spec-review staged', '/spec-review last', '/spec-review PR #N', or requests to check spec impact."
---
# Spec Wiki Impact Review

Find changed contracts through behavior and ownership, then maintain the connected
wiki. Read `docs/azents/spec/AGENTS.md` and start at `docs/azents/spec/index.md`.
Requirements, ADRs, Designs and code are references outside the wiki.

## Workflow

1. Select the requested diff and read it, not just the filenames.
   - Default or `staged`: `git diff --cached --name-only`, `git diff --cached`.
   - `last`: `git diff HEAD~1 --name-only`, `git diff HEAD~1`.
   - `PR #N`: `gh pr diff N --name-only`, `gh pr diff N`.
   - If empty, report `No changes to analyze`.
2. Identify changed concepts, actors, APIs, state transitions, authority,
   persistence, failure/recovery, user-visible behavior and removed contracts.
   Trace production callers and tests where the diff alone is insufficient.
3. Use the wiki index, connections and ordinary text/symbol search to find the
   owning pages. Follow cross-cutting effects into adjacent topics even if no
   changed file was previously referenced. No code-path matching or generated
   catalog is needed.
4. Read the relevant page bodies. A page modified in the same diff still needs
   review: its edit may omit part of the change or contradict another page.
5. Ingest verified changes into the owning contract, update affected connections
   and index entries, and lint the touched subgraph under the wiki guide. Avoid
   duplicated contracts, speculative additions and history-style patch notes.
   If the invocation requests analysis only, report the required edits instead.
6. For a behavior-preserving refactor, repair broken reference links if needed;
   do not create version or freshness-only edits. Delete or consolidate obsolete
   pages only after preserving remaining contracts and repairing current links.

## Output

```markdown
## Spec Wiki Impact

- Diff: <scope>
- Behavior examined: <contracts and evidence>
- Pages: <owning page links and affected neighbors>
- Updated / required edits: <specific changes, or no update needed and why>
- Verification: <references checked and remaining uncertainty>
```

Do not mistake source links for exhaustive coverage. When implementation and
confirmed intent conflict, report the discrepancy rather than documenting an
obvious bug as the intended contract. This review does not authorize product
changes or rewriting immutable reference snapshots.
