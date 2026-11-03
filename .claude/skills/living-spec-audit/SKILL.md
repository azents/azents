---
name: living-spec-audit
description: "Audit the Azents Spec Wiki against current implementation and its connected claims. Use for full or recurring spec-drift audits, wiki consistency checks, or requests to make the current-system wiki reflect verified behavior without changing implementation."
---
# Spec Wiki Audit

The existing `/living-spec-audit` invocation now audits the LLM-maintained wiki;
there is no separate Living Spec catalog or file-path planner. Read
`docs/azents/spec/AGENTS.md` and start at `docs/azents/spec/index.md`.
Only `spec/` is the wiki. Requirements, ADRs, Designs, code and tests remain
references and retain their independent lifecycles.

## Scope and continuity

Record the exact target commit, start time, selected page/topic and intended checks
in a temporary working note before inspection. Keep the audited source commit
fixed; make corrections in a separate worktree when necessary. Remove the working
note after consolidating the result into the normal audit report.

- **Full:** inspect every current topic/page reachable from the index, and search
  for unindexed pages and missing concepts. Do not claim completion for a partial
  traversal or merely checking links.
- **Incremental / recurring:** inspect one bounded semantic topic (normally one
  owning page and necessary neighbor claims), plus an independent review of
  implementation and wiki changes in the preceding 24 hours. Do not substitute
  one lane for the other or enlarge the window using an old global checkpoint.

Use the existing audit reporting destination's successful reports for continuity:
record exact checked pages/sections, source commit, completion time and remaining
coverage. Select an uninspected page before repeating recently checked pages, then
prefer the least recently checked topic. If prior coverage is unavailable, say so,
start from the first unverified topic in the index and claim only the inspected
scope. Old file-bucket checkpoints do not certify semantic wiki coverage.
Do not introduce a replacement planner, hash-bucket state or duplicate run log.

## Inspect the selected topic

1. Read its owning wiki page and relevant connections. Identify the contract:
   actors, authority, state, data, interfaces, lifecycle, failure and recovery.
2. Follow the selected references and search actual source symbols and callers.
   References are entrypoints, not an exhaustive map. Inspect adjacent unlinked
   implementation when it can affect the contract.
3. Compare reachable production behavior and relevant models/tests with the claims.
   Use mechanical evidence for moved symbols, routes, configuration and links;
   use agent reasoning for semantic relevance and consistency. Do not run product
   tests by default; use a focused test only to resolve a concrete uncertainty.
4. Check connected pages for contradictions, duplicated definitions, orphan concepts,
   missing links and stale historical statements presented as current behavior.
5. Ground findings in precise page sections and implementation locations. A
   verification of one claim does not mark an entire large page audited.

## Independently inspect recent changes

At the recorded target commit and audit start time, use ordinary Git tools to
identify commits in the preceding 24-hour window and inspect their actual diffs.
Include additions, removals, renames and merge-introduced changes; for a merge,
compare it to its first parent so old branch commits newly merged into the window
are not missed. Review the behavior of those diffs even when no wiki reference
mentions the file.

For each material change, navigate by concept and ownership to the affected wiki
pages. Determine whether current explanations, connections or references need
updates. Classify behavior-preserving and documentation-only changes explicitly;
do not turn every changed file into a new wiki page. State the exact time window
and any incomplete recent-change review in the result.

## Correct confirmed drift

- Integrate verified current behavior into the owning page; repair related links,
  references and the editorial index in the same focused documentation PR.
- Replace superseded claims instead of appending patch notes. Use Git history,
  not page versions, global verification dates or changelogs.
- Merge or remove obsolete pages only after preserving still-current contracts
  and updating current inbound links.
- Do not modify implementation, Requirements, accepted ADRs or implemented Designs
  as an audit correction. Read them for intent or rationale when relevant.
- If implementation is unambiguously defective, preserve the intended contract
  established by reliable evidence and create a verification/defect issue for
  durable handoff. Do not silently document the bug as desired behavior.
- If behavior is uncertain or evidence conflicts, report it precisely; do not
  invent a contract. Create a verification issue when a durable handoff is needed.

## Verify and report

Run the wiki guide's semantic lint and `python scripts/validate_docs.py`. Check
local links and report exactly which implementation claims were verified. Do not
create placeholder edits, issues or verification stamps when no drift exists.

```markdown
## Spec Wiki Audit

- Mode: full | incremental
- Target commit: <sha>
- Topic and exact pages/sections checked: <scope>
- Independent recent-change window: <start/end with timezone>
- Recent diffs checked: <commits and behavioral scope>

### Drift corrected
- <page/section> — <verified correction and source evidence>

### Unresolved verification
- <locations> — <uncertainty, defect or issue>

### Coverage and result
- <completed scope, no-drift finding or PRs, and uninspected remainder>
- Next topic: <next uninspected / least recently checked semantic topic>
```

Treat inspection as completed only after all selected checks were performed, the
report was successfully persisted/delivered, and every intended correction PR or
required handoff issue was created. A failed or partial investigation must retain
its incomplete scope in the report and must not advance coverage. A confirmed
unresolved finding may count as inspected after successful durable handoff.
There is no script that can certify semantic inspection on the Agent's behalf.
