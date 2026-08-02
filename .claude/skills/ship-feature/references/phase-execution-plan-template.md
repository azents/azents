# Phase Execution Plan Template

Read this reference immediately before creating a phased implementation branch.
Store the completed plan under the project-approved plans directory and keep it on
the phase branch.

```markdown
## Phase Execution Plan

- Phase: `<number and name>`
- Branch/base: `<branch>` → `<base>`
- PR boundary: `<deliverable>`
- Inputs: `<completed dependencies>`
- Deliverables: `<observable outcomes>`
- Non-goals: `<explicit exclusions>`
- Interfaces: `<contracts fixed before implementation>`
- Approved Design mechanisms: `<material mechanism IDs>`
- Authority references: `<REQ, ADR, current Spec or project constraint>`
- Design delta: `None`
- Removal obligations: `<Design removal items owned by this phase, or None>`
- Absence verification: `<proof that removed units are no longer referenced or authoritative>`

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... | ... |

- Integration order: `<sequence>`
- Independent review: `<exact reviewer, scope, criteria, inputs, output>`
- Final validation: `<commands>`
- Scope-drift check: `<approved coverage, unauthorized additions, non-goals>`
- Context checkpoint: `<completed behavior, changed interfaces, evidence, remaining scope, paths, risks>`
```

A chat summary, task prompt, PR body, or multi-phase plan is not a substitute for
this tracked phase plan. If `Design delta` is not `None`, return to feature design
and reapprove the Design before implementation.
