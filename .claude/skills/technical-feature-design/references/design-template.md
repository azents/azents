# Primary Design Required Sections

Read this reference immediately before writing or revising an Azents primary Design.
Follow `docs/azents/AGENTS.md` for frontmatter, naming, lifecycle, and Test Strategy
requirements.

Use the sections that apply to the feature, including:

- current behavior and requirement gaps;
- requirement and ADR traceability;
- architecture, ownership, and source-of-truth boundaries;
- APIs, events, data models, runtime behavior, and state transitions;
- security and permissions;
- migration, rollout, rollback, failure, retry, and recovery behavior;
- observability and operational risks;
- Test Strategy and fixtures;
- alternatives, assumptions, and non-blocking risks;
- Design Authority;
- Removal and Replacement; and
- Design Approval.

## Design Authority

```markdown
## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | ... | ... | `required | decided | existing | derived` |
```

Include only material mechanisms. Authority is limited to confirmed Requirements,
accepted ADR decisions, unchanged current Specs, and project constraints.

Classifications:

- `required`: directly required by confirmed Requirements;
- `decided`: selected by an accepted ADR decision;
- `existing`: retained from an unchanged current Spec or project constraint; and
- `derived`: necessary synthesis of multiple approved sources with no remaining
  material choice.

Use stable document-local IDs. Keep an unchanged mechanism's ID across revisions,
allocate a new ID for a new mechanism, and never reuse a removed ID. Increment the
Design revision whenever a material mechanism or its authority changes.

When a mechanism combines approved sources, cite each source. Design synthesis and
approval do not create authority or replace Requirements or ADR decisions.

## Removal and Replacement

```markdown
## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... |
```

Cover obsolete code, contracts, state, tests, fixtures, configuration,
documentation, and generated surfaces as applicable. A replacement may be `None`
when the behavior disappears entirely. Use an explicit `None` finding only after
repository-grounded analysis finds no removal obligation.

Removing an authoritative behavior, contract, persisted state, source-of-truth
path, or operational mode requires confirmed authority. When viable alternatives
remain, the removal choice is a material decision; when approved authority already
determines removal, treat it as a fixed outcome. Ordinary behavior-preserving
cleanup remains agent-owned but still belongs in this section when required to
complete an approved replacement.

## Design Approval

```markdown
## Design Approval

- Mode: `Collaborative | Autonomous`
- Decision owner: `<requester or interviewee>`
- Approved on: `YYYY-MM-DD`
- Approved Design revision: `<revision>`
- Approved authority IDs: `<exact ID set>`
- Approved scope: `<material Design summary>`
```

Record approval only after authority and feasibility checks pass. Approval is valid
only while the revision and exact authority ID set match the current Design
Authority section. Any material change invalidates the approval.
