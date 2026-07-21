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
- **ADR**: records hard-to-reverse decisions. Keep ADRs append-only. If a decision changes, do not edit the old ADR; add a new ADR instead.
- **Design**: records development-time implementation design. It is not guaranteed to reflect the current system. Subsequent changes should be recorded in spec documents, new design documents, Requirements snapshots, or ADRs. The only exception is an unimplemented design that is still moving through stacked PR phases.
- **Spec**: records current system behavior. Delete stale specs or merge them into the current spec instead of adding freshness/status flags.

## Directory Classification

| Directory | Use When | Examples | Required Frontmatter |
| --- | --- | --- | --- |
| `requirements/` | Confirmed user needs, scope, constraints, and acceptance criteria for one development snapshot. | `slack-260721-channel-agent-conversation.md` | `title`, `created`, `tags`; add `implemented` after verified implementation |
| `adr/` | Decision record for one decision, including context, options, chosen path, and consequences. Append-only. | `NNNN-{slug}.md` | `title`, `created`, `tags` |
| `spec/domain/` | Current domain model specs such as Agent, Session, Team, Memory. | `agent.md`, `workspace.md` | plus `spec_type: domain`, `domain`, `code_paths`, `last_verified_at`, `spec_version` |
| `spec/flow/` | Current flow specs such as the ReAct loop or message routing. | `agent-execution-loop.md`, `message-routing.md` | plus `spec_type: flow`, `code_paths`, `last_verified_at`, `spec_version` |
| `design/` | Development-time design or implementation decision records. A design may temporarily be unimplemented only while stacked PR work is in progress. | `architecture.md`, `agent-sandbox.md`, `agent-session-sandbox-scenarios/oncall-agent.md` | `title`, `created`, `updated`, `implemented`, `tags` |
| `notes/` | Pre-design product/architecture blueprints, unresolved model exploration, or discussion summaries. | `agent-thread-session-blueprint.md` | `title`, `created`, `tags` |
| `issues/` | Bug or operational issue tracking. | `2026-05-01-agent-stuck.md` | `title`, `created`, `tags` |

`INDEX.md` is generated from frontmatter by `scripts/gen_docs_index.py --docs-root docs/azents --project-name azents` through the pre-commit hook.

### Requirements Naming and References

Name Requirements snapshots:

```text
requirements/{word}-{YYMMDD}-{slug}.md
```

- Use the KST creation date.
- Use a short lowercase feature word such as `slack`, `memory`, or `billing`.
- Use a slug for the specific user-visible capability, not an implementation technique or broad topic.
- Treat `{word}-{YYMMDD}` as the canonical short ID.
- Number requirements locally as `REQ-1`, `REQ-2`, and so on.
- Reference individual requirements as `{word}-{YYMMDD}/REQ-N`.
- If the same word and date collide, combine the same effort or choose a more precise feature word. Do not append an arbitrary ordinal.

Requirements contain product intent only: problem, actors, one primary scenario, supporting scenarios, goals, non-goals, requirements with acceptance criteria, fixed constraints, open assumptions, and requester confirmation. Keep APIs, data models, architecture, implementation choices, phases, and ADR decisions out of Requirements.

### Requirements Lifecycle

- Create the Requirements document after one primary scenario is established and before creating an ADR.
- Obtain explicit requester confirmation before accepting design decisions, including in autonomous mode.
- Before implementation, apply product-scope changes in this order: Requirements → ADR → design.
- Add `implemented: YYYY-MM-DD` only after implementation is complete and verified.
- After `implemented` is set, never modify the Requirements filename or content.
- For later development on the same topic, create a new dated Requirements snapshot. Do not mark or rewrite the older snapshot.
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

### Additional Rules for `design/`

- `design/` documents are development-time design decision records. Do not keep overwriting them as living documents after implementation.
- New feature designs reference the confirmed Requirements snapshot and trace `{short-id}/REQ-N` through ADR decisions to design mechanisms. Do not duplicate the Requirements source of truth in the design.
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
  - Feature design: `{feature}.md`
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

The pre-commit hook runs `scripts/gen_docs_index.py --docs-root docs/azents --project-name azents`, validates frontmatter for `docs/azents/**/*.md`, and regenerates indexes. It validates Requirements filename/date rules and spec-only fields such as `spec_type`, `code_paths`, `last_verified_at`, and `spec_version`.

## New Document Flow

Decision tree:

1. Confirmed feature requirements? → `requirements/{word}-{YYMMDD}-{slug}.md`.
2. Decision record? → `adr/NNNN-{slug}.md` with the next zero-padded number.
3. Feature design? → `design/{name}.md`.
4. Current behavior spec? → `spec/domain/{domain}.md` or `spec/flow/{flow}.md`.
5. Bug or operational issue? → `issues/{name}.md`.
6. Pre-design blueprint or discussion summary? → `notes/{name}.md`.
7. Unresolved discussion? → keep discussion in GitHub Issue/Discussion, optionally summarize in `notes/`, then move confirmed intent and decisions into Requirements/ADR/design/spec when settled.

Writing order:

1. Choose the directory using the decision tree above.
2. Write required frontmatter, including requirements- or spec-specific fields when applicable.
3. For a new feature, confirm Requirements before recording ADR decisions or writing the design.
4. Record decisions and rationale in the Decision section of an ADR or design document.
5. Validate locally with `scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`.

## Deletion and Move Rules

- **`requirements/`**: keep implemented snapshots in place and immutable. Later changes create a new snapshot; current behavior belongs in `spec/`.
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
title: "ADR-0001: Adopt the Living Spec Model"
created: 2026-05-01
tags: [architecture, process]
---
```
