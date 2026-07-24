---
title: "Team Session execution boundaries phase 4: Session-owned resource authority"
created: 2026-07-24
tags: [session, authorization, resources, files, migration, security]
---

# Team Session execution boundaries phase 4: Session-owned resource authority

## Phase Execution Plan

- Phase: `4 — Session-owned resources and output`
- Branch/base: `feature/team-session-resource-authority` → `feature/team-session-userless-engine` (`52a1db9d`)
- PR boundary: typed ExchangeFile provenance, exact ModelFile Run lineage, and Session/Run-authorized internal resource operations
- Requirements: [session-260724/REQ](../requirements/session-260724-team-session-execution-boundaries.md)
- ADR: [session-260724/ADR](../adr/session-260724-team-session-execution-boundaries.md)
- Design: [session-260724/DESIGN](../design/session-260724-team-session-execution-boundaries.md)
- Multi-phase plan: [Team Session execution boundaries implementation plan](./team-session-execution-boundaries-implementation-plan.md)

## Deliverables

- Generate forward Alembic revision(s) for typed ExchangeFile creation provenance and exact ModelFile `created_run_id` lineage, then update `db-schemas/rdb/revision`.
- Preserve requester-authorized public Exchange upload, list, download, and delete boundaries while adding validated Session/Run authority for internal create, resolve, import, materialize, and output paths.
- Bind accepted-input and generated ExchangeFiles to canonical root retention ownership and record Human, Agent, Tool, provider, system, or migration provenance without treating provenance as authority.
- Make ModelFile creation, promotion, retrieval, and materialization validate the exact canonical Workspace, Agent, Session, Run, and root lineage; backfill only deterministic historical Run identity.
- Restore Runtime `import_file`, `present_file`, and `read_image` only after each is supplied the necessary Session/Run authority.
- Make Artifact/MCP output, provider-hosted files, and client-generated images use canonical Session/Run authority while preserving existing deterministic output identity, transaction, compensation, retention, recovery, and cleanup behavior.
- Add resource authorization, provenance constraint, lineage, retry, recovery, cleanup, and requester-versus-execution boundary tests.

## Non-goals

- Historical migration classification/replay tooling, old broker rejection, coordinated cutover procedures, or mixed-version compatibility; those belong to Phase 5.
- New User Session persistence, User-brought Tools, personal credentials, or User capability projection.
- External Channel UX or new External Channel resource flows.
- E2E/testenv expansion, living-spec promotion, convention changes, cleanup, PR creation, or commits.
- Kubernetes, database, object-storage, or other external destructive operations.

## Boundary Contract

A current requester authorizes one public resource operation. A stored uploader or typed source describes provenance only. Internal resource operations instead receive validated canonical Session/Run authority and revalidate the resource's Workspace, Agent, exact Session, root retention owner, Run, and owner generation as applicable. No internal path supplies an empty, borrowed, inferred, or fallback User.

## Workstreams

| Workstream | Owned paths | Output | Validation |
| --- | --- | --- | --- |
| Schema and models | `rdb/models/exchange_file.py`, `rdb/models/model_file.py`, `db-schemas/rdb/migrations/**` | typed Exchange provenance and exact ModelFile Run lineage | generated revision, migration pointer/head, model/repository tests |
| Internal authority | `services/exchange_file/**`, `services/model_file.py`, `services/artifact.py`, resource repositories | explicit Session/Run authority and public/internal separation | cross-root/cross-run negative tests |
| Engine and Runtime output | `engine/events/**`, `engine/tools/{builtin,import_file,present_file,read_image,mcp_base}.py`, provider output paths | Userless promotion/import/present/image/MCP/provider output | resource lifecycle, Runtime, provider-output tests |
| Retention and regression | cleanup/purge paths and affected tests | preserved root/exact-session/exact-run retention and deterministic retries | purge, compensation, recovery, focused Python suite |

## Validation

- Run generated migration validation and revision-head checks without applying migrations to a shared database.
- Run focused Ruff, Pyright, and pytest from `python/apps/azents` for RDB models, migrations, ExchangeFile, ModelFile, Artifact, Runtime file tools, MCP output, provider output, input promotion, and archival cleanup.
- Run `git diff --check` and inspect every internal resource callsite for explicit Session/Run authority and absence of User fallback.
- Regenerate API clients only if public schemas change; do not manually edit generated clients.
