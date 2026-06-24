---
title: "azents documentation structure"
created: 2026-02-25
updated: 2026-05-13
tags: [documentation, process]
---
# azents Documentation Structure

This directory contains all azents project documentation.

## Living Spec Overview

Azents is an AI agent platform, so much of the system behavior lives outside the public API contract: runtime decisions, memory policy, tool selection, and similar behavior cannot be fully described by OpenAPI alone. The project therefore uses a three-layer documentation model.

- **ADR** (`adr/`) — why a decision was made. Append-only decision log.
- **Design** (`design/`) — what was designed at development time and why. Design documents are not continuously updated as living specs after implementation.
- **SPEC.md** (`spec/domain/`, `spec/flow/`) — how the current system actually behaves. These are living documents linked to code through `code_paths`.

Always read `spec/domain/` and `spec/flow/` first for current behavior. Read ADRs and design documents only when you need decision rationale, historical context, rejected options, or implementation-time background behind the current spec.

SPEC documents use the `code_paths` frontmatter field to link the spec to source files. When code changes, update the related spec's `last_verified_at` so drift can be detected.

Automation tool: `/spec-review`.

ADR and design documents use their location and content as their state model; they do not need a separate status field.

- **ADR**: records hard-to-reverse decisions. Keep ADRs append-only. If a decision changes, do not edit the old ADR; add a new ADR instead.
- **Design**: records design decisions from development time. It is not guaranteed to reflect the current system. Subsequent changes should be recorded in spec documents, new design documents, or ADRs. The only exception is an unimplemented design that is still moving through stacked PR phases.
- **Spec**: records current system behavior. Delete stale specs or merge them into the current spec instead of adding freshness/status flags.

## Directory Classification

| Directory | Use When | Examples | Required Frontmatter |
| --- | --- | --- | --- |
| `adr/` | Decision record for one decision, including context, options, chosen path, and consequences. Append-only. | `NNNN-{slug}.md` | `title`, `created`, `tags` |
| `spec/domain/` | Current domain model specs such as Agent, Session, Team, Memory. | `agent.md`, `workspace.md` | plus `spec_type: domain`, `domain`, `code_paths`, `last_verified_at`, `spec_version` |
| `spec/flow/` | Current flow specs such as the ReAct loop or message routing. | `agent-execution-loop.md`, `message-routing.md` | plus `spec_type: flow`, `code_paths`, `last_verified_at`, `spec_version` |
| `design/` | Development-time design or implementation decision records. A design may temporarily be unimplemented only while stacked PR work is in progress. | `architecture.md`, `agent-sandbox.md`, `agent-session-sandbox-scenarios/oncall-agent.md` | `title`, `created`, `updated`, `implemented`, `tags` |
| `notes/` | Pre-design product/architecture blueprints, unresolved model exploration, or discussion summaries. | `agent-thread-session-blueprint.md` | `title`, `created`, `tags` |
| `issues/` | Bug or operational issue tracking. | `2026-05-01-agent-stuck.md` | `title`, `created`, `tags` |

`INDEX.md` is generated from frontmatter by `scripts/gen_docs_index.py --docs-root docs/azents --project-name azents` through the pre-commit hook.

### Removed Legacy Directories

| Old Directory | Destination |
| --- | --- |
| `implementation/` | Keep implemented records in `design/`; current behavior belongs in `spec/`. |
| `misc`, `discussion/` | Decisions go to `adr/`, designs to `design/`, current behavior to `spec/`. |
| `research/`, `reference/`, `runbook/`, `testenv/`, `testing/` | Move only useful content into `design/`, `spec/`, or `issues/`. |
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

### Additional Rules for `design/`

- `design/` documents are development-time design decision records. Do not keep overwriting them as living documents after implementation.
- Current system behavior always belongs in `spec/`. Changes to design rationale should be recorded in a new `design/` or `adr/` document when needed.
- `implemented` is the date when the design was implemented.
- After `implemented` is set, do not modify the design document. Record later changes in `spec/` or a new `design`/`adr` document.
- azents feature designs must include a `## Test Strategy` section. Product behavior verification should be E2E-first. Use testenv only as fallback/diagnostic support when E2E is difficult or spot diagnosis is needed.
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

The pre-commit hook runs `scripts/gen_docs_index.py --docs-root docs/azents --project-name azents`, validates frontmatter for `docs/azents/**/*.md`, and regenerates indexes. It also validates spec-only fields such as `spec_type`, `code_paths`, `last_verified_at`, and `spec_version`.

## New Document Flow

Decision tree:

1. Decision record? → `adr/NNNN-{slug}.md` with the next zero-padded number.
2. Feature design? → `design/{name}.md`.
3. Current behavior spec? → `spec/domain/{domain}.md` or `spec/flow/{flow}.md`.
4. Bug or operational issue? → `issues/{name}.md`.
5. Pre-design blueprint or discussion summary? → `notes/{name}.md`.
6. Unresolved discussion? → keep discussion in GitHub Issue/Discussion, optionally summarize in `notes/`, then move decisions into ADR/design/spec when settled.

Writing order:

1. Choose the directory using the decision tree above.
2. Write required frontmatter, including spec-only fields when applicable.
3. Record decisions and rationale in the Decision section of an ADR or design document.
4. Validate locally with `scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`.

## Deletion and Move Rules

- **`design/`**: keep documents in place after implementation. Do not use status fields to express freshness. After `implemented` is set, do not edit the document; record later changes in `spec/` or new documents.
- **`spec/`**: keep only current behavior specs. Delete stale specs or merge them into the current spec rather than changing status.

## Frontmatter Examples

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
title: "ADR-0001: Adopt the Living Spec Three-Layer Model"
created: 2026-05-01
tags: [architecture, process]
---
```
