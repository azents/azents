---
title: "azents documentation structure"
created: 2026-02-25
updated: 2026-07-21
tags: [documentation, process]
---
# azents Documentation Structure

This directory contains all azents project documentation.

## Living Spec Overview

Azents is an AI agent platform, so much of the system behavior lives outside the public API contract: runtime decisions, memory policy, tool selection, and similar behavior cannot be fully described by OpenAPI alone. The project therefore uses a four-layer documentation model.

- **Requirements** (`requirements/`) — what users need for one confirmed development snapshot.
- **ADR** (`adr/`) — why a hard-to-reverse decision was made. Append-only decision log.
- **Design** (`design/`) — how the system was designed to satisfy the Requirements and ADR decisions at development time.
- **SPEC.md** (`spec/domain/`, `spec/flow/`) — how the current system actually behaves. These are living documents linked to code through `code_paths`.

Always read `spec/domain/` and `spec/flow/` first for current behavior. Read Requirements, ADRs, and design documents only when you need product intent, decision rationale, historical context, rejected options, or implementation-time background behind the current spec.

SPEC documents use the `code_paths` frontmatter field to link the spec to source files. When code changes, update the related spec's `last_verified_at` so drift can be detected.

Automation tool: `/spec-review`.

Requirements, ADR, and design documents use their location and content as their state model; they do not need a separate status field.

- **Requirements**: records confirmed product intent and acceptance criteria. It is mutable until implementation is complete and verified. After `implemented` is set, keep the filename and content immutable. Later product work creates a new Requirements snapshot.
- **ADR**: records hard-to-reverse decisions. Keep ADRs append-only. If an accepted decision changes, do not edit the old ADR; create a new development snapshot instead.
- **Design**: records development-time implementation design. It is not guaranteed to reflect the current system. Subsequent changes should be recorded in spec documents, new design documents, Requirements snapshots, or ADRs. The only exception is an unimplemented design that is still moving through stacked PR phases.
- **Spec**: records current system behavior. Delete stale specs or merge them into the current spec instead of adding freshness/status flags.

## Directory Classification

| Directory | Use When | Examples | Required Frontmatter |
| --- | --- | --- | --- |
| `requirements/` | Confirmed user needs, scope, constraints, and acceptance criteria for one development snapshot. | `slack-260721-channel-agent-conversation.md` | `title`, `created`, `tags`; add `implemented` after verified implementation |
| `adr/` | Hard-to-reverse decisions for one development snapshot. Keep all snapshot decisions in one append-only ADR. | `slack-260721-channel-agent-conversation.md`; legacy `NNNN-{slug}.md` remains valid | `title`, `created`, `tags` |
| `spec/domain/` | Current domain model specs such as Agent, Session, Team, Memory. | `agent.md`, `workspace.md` | plus `spec_type: domain`, `domain`, `code_paths`, `last_verified_at`, `spec_version` |
| `spec/flow/` | Current flow specs such as the ReAct loop or message routing. | `agent-execution-loop.md`, `message-routing.md` | plus `spec_type: flow`, `code_paths`, `last_verified_at`, `spec_version` |
| `design/` | Primary development-snapshot Designs and supporting design-time records. | `slack-260721-channel-agent-conversation.md`, `feature-audit-report-YYYY-MM-DD.md` | `title`, `created`, `tags`; use `updated` while drafting and add `implemented` after verified implementation |
| `notes/` | Pre-design product/architecture blueprints, unresolved model exploration, or discussion summaries. | `agent-thread-session-blueprint.md` | `title`, `created`, `tags` |
| `issues/` | Bug or operational issue tracking. | `2026-05-01-agent-stuck.md` | `title`, `created`, `tags` |

`INDEX.md` is generated from frontmatter by `scripts/gen_docs_index.py --docs-root docs/azents --project-name azents` through the pre-commit hook.

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
- Keep multiple hard-to-reverse decisions in the snapshot ADR as `D1`, `D2`, and so on.
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

Requirements contain product intent only: problem, actors, one primary scenario, supporting scenarios, goals, non-goals, requirements with acceptance criteria, fixed constraints, open assumptions, and requester confirmation. Keep APIs, data models, architecture, implementation choices, phases, and ADR decisions out of Requirements.

The shared format applies to the core Requirements, ADR, and primary Design for every current development snapshot. Specs, Notes, Issues, Plans, audit reports, validation reports, and other supporting records retain descriptive naming rules only when explicitly classified as supporting. Legacy numbered ADRs, pre-migration Design filenames, and bare `ADR-NNNN-DN` references are historical inputs only; they are not valid current core documents after migration and may remain only in explicit provenance or ambiguity records.

### Development Snapshot Lifecycle

- Create the Requirements document after one primary scenario is established and before creating an ADR.
- Obtain explicit requester confirmation before accepting design decisions, including in autonomous mode.
- Create the same-basename ADR after Requirements confirmation, then create the same-basename Design after the ADR defines a coherent direction.
- Before implementation, apply product-scope and design changes in this order: Requirements → ADR → Design.
- The valid progressive states are Requirements only, Requirements plus ADR, or the complete Requirements/ADR/Design trio.
- Add the same `implemented: YYYY-MM-DD` date to Requirements and Design only after implementation is complete and verified. An implemented new-format snapshot must contain the complete trio.
- After implementation, treat the Requirements, accepted ADR, and Design as one immutable historical snapshot.
- For later development on the same topic, create a new dated snapshot. Do not mark or rewrite the older snapshot.
- Keep current behavior only in living specs.

### Removed Legacy Directories

| Old Directory | Destination |
| --- | --- |
| `implementation/` | Keep implemented records in `design/`; current behavior belongs in `spec/`. |
| `misc`, `discussion/` | Confirmed intent goes to `requirements/`, decisions go to `adr/`, designs to `design/`, and current behavior to `spec/`. |
| `research/`, `reference/`, `runbook/`, `testenv/`, `testing/` | Move only useful content into `requirements/`, `design/`, `spec/`, or `issues/`. |
| `plans/` | Temporary implementation plans belong in PRs/issues and are deleted after completion. |

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
- Keep one primary end-to-end scenario. Classify other scenarios as supporting, secondary, or future scope.
- Write solution-neutral requirements with observable acceptance criteria.
- Use document-local `REQ-N` identifiers and qualify cross-document references with the canonical short ID.
- Do not create an ADR or design before the requester confirms the Requirements document.
- `implemented` is the date when implementation was completed and verified.
- After `implemented` is set, do not modify the document. Record later product intent in a new Requirements snapshot and current behavior in specs.

### Additional Rules for `adr/`

- New development-snapshot ADRs must use the exact basename of their confirmed Requirements document.
- Keep all hard-to-reverse decisions for the snapshot in one ADR and identify them as `{snapshot}/ADR-D1`, `{snapshot}/ADR-D2`, and so on.
- Reference the affected `{snapshot}/REQ-N` items instead of duplicating Requirements text.
- Keep the ADR append-only after acceptance. If later development changes a decision, create a new snapshot rather than rewriting the accepted ADR.
- Legacy numbered ADR filenames and bare `ADR-NNNN-DN` references are historical provenance only and are not valid current ADR records after migration.

### Additional Rules for `design/`

- `design/` documents are development-time design decision records. Do not keep overwriting them as living documents after implementation.
- A new snapshot's primary Design must use the exact basename of its Requirements and ADR.
- New feature designs reference the confirmed Requirements snapshot and trace `{snapshot}/REQ-N` through `{snapshot}/ADR-DN` to design mechanisms. Do not duplicate the Requirements source of truth in the design.
- Current system behavior always belongs in `spec/`. Changes to design rationale should be recorded in a new Requirements, design, or ADR document when needed.
- `implemented` is the date when the design was implemented.
- After `implemented` is set, do not modify the design document. Record later changes in `spec/` or a new Requirements/design/ADR document.
- Azents feature designs must include a `## Test Strategy` section. Product behavior verification should be E2E-first. Use testenv only as fallback/diagnostic support when E2E is difficult or spot diagnosis is needed.
- `Test Strategy` must describe the E2E primary verification matrix, E2E plan, whether testenv fixture/prerequisite support is needed and why, fixture/seed requirements, credential/prerequisite snapshot requirements, evidence format, CI execution policy, and skip/fail criteria for optional/live tests. If product behavior verification has no E2E coverage and only testenv support, explain why.

### `design/` Structure and Search Rules

- Do **not** list `design/` documents in an index. They accumulate over time, so use structure and naming conventions for discovery.
- Root `design/*.md` files hold feature designs, implementation plans, audit reports, QA reports, and similar feature-scoped documents.
- Add subdirectories only when a document family is large enough. Current examples include `design/agent-session-sandbox-scenarios/`.
- Keep filenames descriptive:
  - New primary snapshot Design: `{word}-{YYMMDD}-{slug}.md`, matching Requirements and ADR
  - Existing legacy Design: keep its current descriptive filename unchanged
  - Implementation plan: `{feature}-plan.md`, `{feature}-implementation-plan.md`
  - Audit/verification report: `{feature}-audit-report-YYYY-MM-DD.md`, `{feature}-spec-sync-YYYY-MM-DD.md`, `{feature}-testenv-report-YYYY-MM-DD.md`
- When searching for a document, prefer filename prefix/slug and `tags` frontmatter over directory indexes.

### Additional Fields for `spec/`

All `spec/domain/` and `spec/flow/` documents require these fields:

```yaml
spec_type: domain       # or flow
domain: agent           # domain name, only for spec/domain/
code_paths:
  - python/apps/azents/src/azents/services/agent_service.py
  - python/apps/azents/src/azents/repos/agent_repo.py
last_verified_at: 2026-04-20
spec_version: 1
```

- `spec_type` — `domain` or `flow`
- `domain` — domain name such as `agent`, `session`, `team`, `memory`, `user`, `toolkit`, or `trigger`
- `code_paths` — repository-root-relative source file paths covered by this spec
- `last_verified_at` — last date the spec was checked against code
- `spec_version` — spec schema version, currently `1`

### CI Validation

The pre-commit hooks run snapshot validator tests and `scripts/gen_docs_index.py --docs-root docs/azents --project-name azents`, validate frontmatter for `docs/azents/**/*.md`, and regenerate indexes.

For new-format snapshot documents, validation enforces the Requirements filename/date relationship, valid ADR/Design `created` dates, per-type short-ID uniqueness, same-basename siblings, and the progressive Requirements → ADR → Design lifecycle. Requirements-only and Requirements-plus-ADR states are valid while design work is in progress. An implemented snapshot must contain the full trio, and Requirements and Design must use the same implementation date. Legacy ADR and Design filenames continue through the existing common-frontmatter validation.

Spec validation continues to enforce `spec_type`, `code_paths`, `last_verified_at`, and `spec_version`.

## New Document Flow

Decision tree:

1. Confirmed feature requirements? → `requirements/{word}-{YYMMDD}-{slug}.md`.
2. Hard-to-reverse decisions for that snapshot? → `adr/{same-basename}.md`.
3. Primary feature design? → `design/{same-basename}.md`.
4. Current behavior spec? → `spec/domain/{domain}.md` or `spec/flow/{flow}.md`.
5. Bug or operational issue? → `issues/{name}.md`.
6. Pre-design blueprint or discussion summary? → `notes/{name}.md`.
7. Unresolved discussion? → keep discussion in GitHub Issue/Discussion, optionally summarize in `notes/`, then move confirmed intent and decisions into Requirements/ADR/design/spec when settled.

Writing order:

1. Choose the directory using the decision tree above.
2. Write required frontmatter, including requirements- or spec-specific fields when applicable.
3. For a new feature, choose the shared basename in Requirements and obtain requester confirmation.
4. Create the same-basename ADR before accepting decisions, then create the same-basename Design.
5. Validate locally with `scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`.

## Deletion and Move Rules

- **`requirements/`**: keep implemented snapshots in place and immutable. Later changes create a new snapshot; current behavior belongs in `spec/`.
- **`adr/`**: keep accepted ADRs in place and append-only. Later decisions create a new snapshot rather than rewriting accepted history.
- **`design/`**: keep documents in place after implementation. Do not use status fields to express freshness. After `implemented` is set, do not edit the document; record later changes in `spec/` or new Requirements/design/ADR documents.
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
title: "Agent Domain Spec"
created: 2026-05-01
tags: [backend, engine]
spec_type: domain
domain: agent
code_paths:
  - python/apps/azents/src/azents/services/agent_service.py
  - python/apps/azents/src/azents/repos/agent_repo.py
  - python/apps/azents/src/azents/rdb/models/agent.py
last_verified_at: 2026-05-01
spec_version: 1
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
