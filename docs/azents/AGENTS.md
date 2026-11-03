---
title: "azents documentation structure"
created: 2026-02-25
updated: 2026-11-04
tags: [documentation, process]
---
# azents Documentation Structure

This directory contains all azents project documentation.

## Spec Wiki and Reference Documents

Azents is an AI agent platform, so much of the system behavior lives outside the public API contract: runtime decisions, memory policy, tool selection, and similar behavior cannot be fully described by OpenAPI alone. The project therefore uses a four-layer documentation model.

- **Requirements** (`requirements/`) — confirmed user or system outcomes for one development snapshot.
- **ADR** (`adr/`) — why a material architecture or product-contract decision was made. Append-only decision log.
- **Design** (`design/`) — how the system was designed to satisfy the Requirements and ADR decisions at development time.
- **Spec Wiki** (`spec/`) — connected pages describing how the current system behaves.

Only `spec/` is the LLM Wiki. Requirements, ADRs, Designs, implementation and tests
remain references outside it. Begin at [the wiki index](spec/index.md) and follow
the [wiki maintenance guide](spec/AGENTS.md) for ingest, query and semantic lint.
References support claims; they are not exhaustive coverage declarations.

Automation tool: `/spec-review`.

Requirements, ADR, and design documents use their location and content as their state model; they do not need a separate status field.

- **Requirements**: records confirmed product intent and acceptance criteria. It is mutable until implementation is complete and verified. After `implemented` is set, keep the filename and content immutable. Later product work creates a new Requirements snapshot.
- **ADR**: records material architecture and product-contract decisions. Keep ADRs append-only. If an accepted decision changes, do not edit the old ADR; create a new development snapshot instead.
- **Design**: records development-time implementation design. It is not guaranteed to reflect the current system. Subsequent changes should be recorded in spec documents, new design documents, Requirements snapshots, or ADRs. The only exception is an unimplemented design that is still moving through stacked PR phases.
- **Spec**: records current system behavior. Delete stale specs or merge them into the current spec instead of adding freshness/status flags.

## Directory Classification

| Directory | Use When | Examples | Required Frontmatter |
| --- | --- | --- | --- |
| `requirements/` | Confirmed user needs, scope, constraints, and acceptance criteria for one development snapshot. | `slack-260721-channel-agent-conversation.md` | `title`, `created`, `tags`; add `implemented` after verified implementation |
| `adr/` | Material architecture or product-contract decisions for one development snapshot. Keep all snapshot decisions in one append-only ADR. | `slack-260721-channel-agent-conversation.md` | `title`, `created`, `tags` |
| `spec/` | LLM-maintained current-system wiki, organized by concepts and flows with an editorial index. | `index.md`, `domain/agent.md`, `flow/agent-execution-loop.md` | `title`; optional `created`, `tags` |
| `design/` | Primary development-snapshot Designs and supporting design-time records. | `slack-260721-channel-agent-conversation.md`, `feature-audit-report-YYYY-MM-DD.md` | `title`, `created`, `tags`; use `updated` while drafting and add `implemented` after verified implementation |
| `plans/` | Temporary multi-phase implementation plans and phase execution plans used while shipping a feature. Remove them in the feature cleanup phase. | `feature-implementation-plan.md`, `feature-phase-1.md` | `title`, `created`, `tags`; use `updated` while implementation is active |
| `notes/` | Pre-design product/architecture blueprints, unresolved model exploration, or discussion summaries. | `agent-thread-session-blueprint.md` | `title`, `created`, `tags` |
| `issues/` | Bug or operational issue tracking. | `2026-05-01-agent-stuck.md` | `title`, `created`, `tags` |

## Document Discovery

Start with `spec/index.md`, follow relevant page connections, and use ordinary text,
filename and symbol searches when needed. Agents determine relevance from behavior,
ownership and source evidence, not code-path matches. Keep the wiki's editorial
index and contextual links current; do not read the entire documentation tree.

Find a reference snapshot through a specific page link or search its shared
basename under `requirements/`, `adr/` and `design/`. Read Requirements for confirmed
intent, ADRs for decisions, and Designs for implementation-time context. Those
collections are not wiki pages and do not need a second catalog.

### Shared Development Snapshot Naming and References

Name newly created Requirements, ADR, and primary Design documents with one shared basename:

```text
requirements/{word}-{YYMMDD}-{slug}.md
adr/{word}-{YYMMDD}-{slug}.md
design/{word}-{YYMMDD}-{slug}.md
```

- Use the KST date on which the Requirements snapshot is created.
- Keep that date in the shared ADR and Design basename even when those documents are created later; their own `created` frontmatter records their actual creation date.
- Use a short lowercase feature word such as `slack`, `memory`, or `billing`.
- Use a slug for the specific user-visible capability, not an implementation technique or broad topic.
- Treat `{word}-{YYMMDD}` as the canonical short ID.
- Use exactly one Requirements, one ADR, and one primary Design per snapshot.
- Keep multiple material decisions in the snapshot ADR as `D1`, `D2`, and so on.
- If the same word and date collide, combine the same effort or choose a more precise feature word. Do not append an arbitrary ordinal.

Use snapshot-first typed references:

| Reference | Target |
| --- | --- |
| `<snapshot>` | Complete development snapshot |
| `<snapshot>/REQ` | Requirements document |
| `<snapshot>/REQ-N` | Individual requirement |
| `<snapshot>/ADR` | ADR document |
| `<snapshot>/ADR-DN` | Individual ADR decision |
| `<snapshot>/DESIGN` | Primary Design document |

Use a Markdown link on the first meaningful cross-document mention. Later mentions may use the short reference alone.

Requirements contain confirmed intent only: the problem or technical gap, one
primary actor and user scenario or one primary system outcome, supporting scenarios
or effects, goals, non-goals, requirements with acceptance criteria, fixed
constraints, open assumptions, and requester confirmation. Keep APIs, data models,
architecture, implementation choices, phases, and ADR decisions out of
Requirements.

The shared format applies to the core Requirements, ADR, and primary Design for every current development snapshot. Specs, Notes, Issues, Plans, audit reports, validation reports, and other supporting records retain descriptive naming rules only when explicitly classified as supporting. Legacy numbered ADRs, pre-migration Design filenames, and bare `ADR-NNNN-DN` references are historical inputs only; they are not valid current core documents after migration and may remain only in explicit provenance or ambiguity records.

### Development Snapshot Lifecycle

- Create the Requirements document after one primary user scenario or primary system outcome is established and before creating an ADR.
- Obtain explicit requester confirmation of Requirements before accepting design decisions.
- Create the same-basename ADR after Requirements confirmation, then create the same-basename Design after the ADR defines a coherent direction.
- Audit material Design mechanisms against confirmed authority, validate
  feasibility, and approve the complete Design before implementation. Autonomous
  approval belongs to the delegated interviewee; product scope remains with the
  requester.
- Before implementation, apply product-scope and design changes in this order: Requirements → ADR → Design.
- The valid progressive states are Requirements only, Requirements plus ADR, or the complete Requirements/ADR/Design trio.
- Add the same `implemented: YYYY-MM-DD` date to Requirements and Design only after implementation is complete and verified. An implemented new-format snapshot must contain the complete trio.
- After implementation, treat the Requirements, accepted ADR, and Design as one immutable historical snapshot.
- For later development on the same topic, create a new dated snapshot. Do not mark or rewrite the older snapshot.
- Keep current behavior only in living specs.

The [branding-260823 historical document migration](adr/branding-260823-historical-document-migration.md)
is a one-time exception that permits brand-only rewriting and canonical identifier
renaming across historical snapshots. Git history and the migration snapshot retain
the prior provenance. This exception is complete once the migration is verified;
all migrated and future implemented snapshots remain immutable afterward.

### Removed Legacy Directories

| Old Directory | Destination |
| --- | --- |
| `implementation/` | Keep implemented records in `design/`; current behavior belongs in `spec/`. |
| `misc`, `discussion/` | Confirmed intent goes to `requirements/`, decisions go to `adr/`, designs to `design/`, and current behavior to `spec/`. |
| `research/`, `reference/`, `runbook/`, `testenv/`, `testing/` | Move only useful content into `requirements/`, `design/`, `spec/`, or `issues/`. |

## Frontmatter Rules

### Common Required Fields

```yaml
---
title: "Document title"
created: 2026-04-20
tags: [backend, engine]
---
```

- `title` — document title
- `created` — initial creation date in `YYYY-MM-DD`
- `tags` — related area tags such as `architecture`, `backend`, `engine`, `api`, `infra`, `frontend`, `documentation`, `process`, `testenv`, `security`
- `updated` — last update date, optional when it equals `created`

### Additional Rules for `requirements/`

- The filename must match `{word}-{YYMMDD}-{slug}.md` and its date must match the KST `created` date.
- Keep one primary end-to-end user scenario for user-facing work or one primary
  system outcome for infrastructure, internal tooling, migration, performance,
  reliability, and other primarily technical work. Classify other scenarios or
  effects as supporting, secondary, or future scope.
- Write solution-neutral requirements with observable acceptance criteria.
- Use document-local `REQ-N` identifiers and qualify cross-document references with the canonical short ID.
- Do not create an ADR or design before the requester confirms the Requirements document.
- `implemented` is the date when implementation was completed and verified.
- After `implemented` is set, do not modify the document. Record later product intent in a new Requirements snapshot and current behavior in specs.

### Additional Rules for `adr/`

- New development-snapshot ADRs must use the exact basename of their confirmed Requirements document.
- Keep all material architecture or product-contract decisions for the snapshot in one ADR and identify them as `{snapshot}/ADR-D1`, `{snapshot}/ADR-D2`, and so on.
- Reference the affected `{snapshot}/REQ-N` items instead of duplicating Requirements text.
- A material decision has viable options with different product, architecture,
  security, persistence or source-of-truth, ownership or lifecycle, interface or
  configuration, operational, failure or recovery, migration, rollout,
  compatibility, fallback, or authoritative-removal outcomes.
- Keep identifiers, file layout, helper boundaries, equivalent local data
  structures, fixture names, and other non-material implementation details out of
  the ADR.
- Keep the ADR append-only after acceptance. If later development changes a decision, create a new snapshot rather than rewriting the accepted ADR.
- Legacy numbered ADR filenames and bare `ADR-NNNN-DN` references are historical provenance only and are not valid current ADR records after migration.

### Additional Rules for `design/`

- `design/` documents are development-time design decision records. Do not keep overwriting them as living documents after implementation.
- A new snapshot's primary Design must use the exact basename of its Requirements and ADR.
- New feature designs trace Requirements through ADR decisions to implementation
  mechanisms and trace every material mechanism back to confirmed Requirements,
  accepted ADRs, unchanged current Specs, or project constraints. Reference rather
  than duplicate the Requirements source of truth.
- Current system behavior always belongs in `spec/`. Changes to design rationale should be recorded in a new Requirements, design, or ADR document when needed.
- `implemented` is the date when the design was implemented.
- After `implemented` is set, do not modify the design document. Record later changes in `spec/` or a new Requirements/design/ADR document.
- Every new primary Design must include `## Design Authority` with a revision,
  stable material-mechanism IDs, confirmed authority, and `required`, `decided`,
  `existing`, or `derived` classification. Increment the revision for material
  changes, retain unchanged IDs, and never reuse removed IDs. Assumptions,
  approval, convention, feasibility, reversibility, and low risk do not create
  authority.
- Every new primary Design must include a `## Removal and Replacement` section that
  identifies obsolete implementation, contracts, state, tests, fixtures,
  configuration, documentation, and generated surfaces as applicable. Record
  each item's removal authority, replacement or remaining authority, removal
  boundary, and absence verification. Use an explicit `None` finding only after
  system-grounded analysis finds no removal obligations.
- Every new primary Design must include `## Design Approval` with the mode,
  decision owner, date, approved revision, exact authority ID set, and material
  scope. A material change invalidates approval and requires renewed authority,
  feasibility, and approval.
- Azents feature designs must include a `## Test Strategy` section. Product behavior verification should be E2E-first. Use testenv only as fallback/diagnostic support when E2E is difficult or spot diagnosis is needed.
- `Test Strategy` must describe the E2E primary verification matrix, E2E plan, whether testenv fixture/prerequisite support is needed and why, fixture/seed requirements, credential/prerequisite snapshot requirements, evidence format, CI execution policy, and skip/fail criteria for optional/live tests. If product behavior verification has no E2E coverage and only testenv support, explain why.

### `design/` Structure and Search Rules

- Do **not** list `design/` documents in an index. They accumulate over time, so use structure and naming conventions for discovery.
- Root `design/*.md` files hold feature designs, audit reports, QA reports, and
  similar feature-scoped design-time records.
- Add subdirectories only when a document family is large enough. Current examples include `design/agent-session-sandbox-scenarios/`.
- Keep filenames descriptive:
  - New primary snapshot Design: `{word}-{YYMMDD}-{slug}.md`, matching Requirements and ADR
  - Supporting Design record: descriptive filename with `document_role: supporting` and `document_type: supporting-*`
  - Audit/verification report: `{feature}-audit-report-YYYY-MM-DD.md`, `{feature}-spec-sync-YYYY-MM-DD.md`, `{feature}-testenv-report-YYYY-MM-DD.md`
- Search reference documents by filename prefix, slug, tags or relevant text
  rather than maintaining directory-wide reference indexes.

### Additional Rules for `plans/`

- Store the feature's high-level multi-phase implementation plan and every
  phase-specific execution plan under `plans/`.
- Create `plans/` when starting a feature if cleanup from earlier features left
  the directory absent.
- Use descriptive filenames such as `{feature}-implementation-plan.md` and
  `{feature}-phase-{number}-{slug}.md`.
- Keep plan ownership, interfaces, dependencies, validation, and scope current
  while implementation is active.
- Plans decompose approved Design and never create product or Design authority.
  Every implementation and phase plan records approved mechanism IDs, authority
  references, and `Design delta: None`; material changes return to feature design.
- Remove the feature's multi-phase plan and all phase plans in its cleanup PR.
  The directory may disappear when no tracked plans remain.

### Wiki Page Format

Wiki pages require a title and ordinary Markdown content; `created` and `tags`
are optional aids. Give each page a clear scope, contextual connections, detailed
current contracts and selected reference links. Keep structured API inventories
in the body. See `spec/AGENTS.md` for complete guidance.

The wiki uses neither `code_paths` nor per-page version/freshness metadata.
Git records history. Agents own navigation, synthesis and consistency checks.

### CI Validation

The pre-commit hooks run `python scripts/validate_docs.py` and its unit tests.
This small validator checks frontmatter and development-snapshot relationships;
it does not select relevant wiki pages, infer coverage or validate behavior.

Validation requires canonical `{word}-{YYMMDD}-{slug}.md` filenames for
Requirements, ADRs, and primary Designs. It enforces the Requirements
filename/date relationship, ADR/Design `created` date formatting, per-type
short-ID uniqueness, same-basename siblings, and the progressive Requirements
→ ADR → Design lifecycle. Requirements-only and Requirements-plus-ADR states
are valid while design work is in progress. An implemented snapshot must contain
the full trio, and Requirements and Design must use the same implementation date.
Supporting Design records may use descriptive filenames when explicitly
classified with `document_role: supporting` and
`document_type: supporting-*`.

Wiki validation requires `title` only. Perform semantic lint and inspect local
links as described in `spec/AGENTS.md`.

## New Document Flow

Decision tree:

1. Confirmed feature requirements? → `requirements/{word}-{YYMMDD}-{slug}.md`.
2. Material architecture or product-contract decisions for that snapshot? → `adr/{same-basename}.md`.
3. Primary feature design? → `design/{same-basename}.md`.
4. Authority-audited, feasible, and approved feature ready for phased implementation? → create the high-level
   and phase-specific plans under `plans/`.
5. Current behavior? → update the owning wiki page, or add a distinct concept/flow page and link it from `spec/index.md`.
6. Bug or operational issue? → `issues/{name}.md`.
7. Pre-design blueprint or discussion summary? → `notes/{name}.md`.
8. Unresolved discussion? → keep discussion in GitHub Issue/Discussion, optionally summarize in `notes/`, then move confirmed intent and decisions into Requirements/ADR/design/spec when settled.

Writing order:

1. Choose the directory using the decision tree above.
2. Write required frontmatter, including requirements- or spec-specific fields when applicable.
3. For a new feature, choose the shared basename in Requirements and obtain requester confirmation.
4. Brief material decisions before discussing them, create the same-basename ADR
   before accepting decisions, then create the same-basename Design.
5. Audit Design authority and feasibility, then record complete Design approval.
6. For phased implementation, create `plans/` when absent, then store both the
   multi-phase implementation plan and each phase execution plan there.
7. Run wiki semantic lint and `python scripts/validate_docs.py`.

## Deletion and Move Rules

- **`requirements/`**: keep implemented snapshots in place and immutable. Later changes create a new snapshot; current behavior belongs in `spec/`.
- **`adr/`**: keep accepted ADRs in place and append-only. Later decisions create a new snapshot rather than rewriting accepted history.
- **`design/`**: keep documents in place after implementation. Do not use status fields to express freshness. After `implemented` is set, do not edit the document; record later changes in `spec/` or new Requirements/design/ADR documents.
- **`plans/`**: keep implementation plans only while the feature is active.
  Remove its multi-phase and phase execution plans in the cleanup PR. An empty
  `plans/` directory does not need to remain.
- **`spec/`**: keep only current behavior specs. Delete stale specs or merge them into the current spec rather than changing status.

## Frontmatter Examples

Requirements document:

```yaml
---
title: "Slack Channel Agent Conversation Requirements"
created: 2026-07-21
updated: 2026-07-21
tags: [slack, integration, agent]
---
```

Design document:

```yaml
---
title: "Agent Sandbox Design"
created: 2026-03-15
updated: 2026-04-10
implemented: 2026-04-10
tags: [engine, infra]
---
```

Spec document:

```yaml
---
title: "Agent"
created: 2026-05-01
tags: [backend, engine]
---
```

ADR document:

```yaml
---
title: "Slack Channel Agent Conversation"
created: 2026-07-21
tags: [slack, integration, architecture]
---
```

The current ADR filename is `slack-260721-channel-agent-conversation.md`. Legacy numbered ADR filenames are historical inputs only and are not valid current ADR files after migration.
