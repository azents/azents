---
title: "Agent Default Projects Phase 1: Policy Persistence and Management API"
created: 2026-07-24
updated: 2026-07-24
tags: [agent, workspace, project, backend, api, database]
---

# Agent Default Projects Phase 1: Policy Persistence and Management API

## Phase Execution Plan

- Phase: `1 — Policy persistence and management API`
- Branch/base: `feat/agent-default-projects-policy` →
  `feat/agent-default-projects-plan`
- PR boundary: Persist one revisioned ordered automatic-Session Project policy
  per Agent, expose AgentAdmin-only GET/PUT management APIs, validate non-empty
  replacements through the ready Runtime Runner, and regenerate Public API
  artifacts.
- Inputs:
  - `docs/azents/requirements/agent-260724-automatic-session-default-projects.md`
  - `docs/azents/adr/agent-260724-automatic-session-default-projects.md`
  - `docs/azents/design/agent-260724-automatic-session-default-projects.md`
  - `docs/azents/plans/agent-260724-automatic-session-default-projects-implementation-plan.md`
- Deliverables:
  - additive settings/items schema and revision-1 backfill;
  - revision-1 empty policy row created with every new Agent;
  - ordered policy repository with atomic optimistic replacement;
  - AgentAdmin-only policy read and replacement service;
  - Runtime-backed validation for every non-empty submitted path before the
    replacing transaction;
  - Public GET/PUT routes with generated OpenAPI and Python/TypeScript clients;
  - stable error codes for revision conflict and Runtime-unavailable conflict;
  - focused migration, repository, service, route, and generated-contract
    tests.
- Non-goals:
  - no root Session Project initialization;
  - no changes to explicit Session creation, team-primary ensure, subagent
    creation, or External Channel binding;
  - no Agent Settings UI or tRPC router changes;
  - no worktree, Git ref, channel-specific mapping, Project-count limit, or
    compatibility fallback;
  - no living-spec promotion in this phase.
- Interfaces:
  - Settings table: `agent_automatic_project_settings`, keyed by `agent_id`,
    with integer `revision`, nullable `updated_by_workspace_user_id`, and
    timestamps.
  - Items table: `agent_automatic_project_items`, keyed independently and
    ordered by `(agent_id, position)`, with normalized absolute `path`.
  - Every Agent owns one settings row, including an empty policy. Initial
    revision is `1`.
  - Repository replacement input is `agent_id`, `expected_revision`, ordered
    normalized paths, and actor WorkspaceUser ID. A failed revision predicate
    changes no rows.
  - Public routes:
    - `GET /agent/v1/workspaces/{handle}/agents/{agent_id}/automatic-session-projects`
    - `PUT /agent/v1/workspaces/{handle}/agents/{agent_id}/automatic-session-projects`
  - GET/PUT response fields: `revision`, ordered `project_paths`, and
    `updated_at`.
  - PUT input fields: `expected_revision`, ordered `project_paths`.
  - Stable conflict codes:
    - `automatic_session_projects_revision_conflict`
    - `automatic_session_projects_runtime_unavailable`
  - Error responses expose a structured `detail` object containing `code` and
    user-safe `message`; tRPC consumption is deferred to Phase 4.
  - Non-empty writes normalize and de-duplicate paths preserving first
    occurrence order, reject Agent Workspace root/outside paths, validate real
    directories with `owner_session_id=None`, and perform Runtime I/O outside a
    held replacing transaction.
  - Empty replacement clears the policy without Runtime availability.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Persistence and repository | `policy-persistence-impl` | `python/apps/azents/src/azents/rdb/models/agent_automatic_project*.py`, model registry wiring, `python/apps/azents/src/azents/repos/agent_automatic_project/**`, generated Alembic revision, `db-schemas/rdb/revision`, focused repository/migration tests, required Agent-create persistence wiring | Approved documents and fixed schema interface | Schema, backfill, new-Agent row, repository snapshots and atomic replacement | Focused repository/model tests, migration upgrade/downgrade or project schema checks, Ruff, Pyright |
| Management service and Public API | `policy-management-impl` | New policy service/data modules, extracted reusable Runtime directory-validation boundary, `python/apps/azents/src/azents/api/public/agent/v1/**`, related dependency wiring and focused tests | Persistence workstream interfaces available | Authorization, normalization, two-stage revision check, Runtime validation, catalog update, GET/PUT API and structured errors | Focused service and route tests, Ruff, Pyright |
| OpenAPI and generated clients | `policy-clientgen-impl` | `python/apps/azents/specs/public/openapi.json`, generated Python Public client, generated TypeScript Public client according to repository generation workflow | Management API complete and route tests passing | Regenerated contract artifacts with no manual generated edits | OpenAPI drift check, client generation, Python client tests if selected, TypeScript public-client typecheck |

- Integration order:
  1. Persistence owner generates the migration through Alembic, implements
     models/repository, and establishes repository data contracts.
  2. The primary agent verifies those contracts and releases the management
     workstream.
  3. Management owner implements service/API behavior against the fixed
     repository and structured error interfaces.
  4. The primary agent verifies API tests and releases generated artifacts.
  5. Client-generation owner regenerates from the committed OpenAPI source.
  6. The primary agent resolves integration issues, runs all final checks, and
     performs the scope-drift comparison.
- Shared files reserved for the primary agent:
  - dependency-composition files touched by more than one workstream;
  - any conflict in `python/apps/azents/src/azents/services/agent/__init__.py`;
  - final generated-artifact reconciliation;
  - phase plan updates.
- Independent review:
  - Owner: `policy-independent-reviewer`, which must not implement any Phase 1
    workstream.
  - Scope: complete branch diff against the authoritative documents and this
    plan.
  - Criteria: schema correctness, migration/backfill safety, AgentAdmin-only
    authorization, path normalization, no Runtime I/O inside the replacing
    transaction, atomic optimistic replacement, stable structured errors,
    generated-artifact provenance, and absence of Session/UI scope.
  - Inputs: full diff, focused test results, migration evidence, OpenAPI drift
    result, and generated-client checks.
  - Output: severity-ranked findings with file/line evidence. The primary
    agent applies accepted localized fixes and asks the same reviewer to
    recheck them.
- Final validation:
  - `cd python/apps/azents && uv run ruff check .`
  - `cd python/apps/azents && uv run ruff format --check .`
  - `cd python/apps/azents && uv run pyright .`
  - focused repository, service, Agent route, and Agent creation tests;
  - migration/schema validation required by the current project workflow;
  - `cd python/apps/azents && uv run python src/cli/dump_openapi.py`
  - `git diff --exit-code -- python/apps/azents/specs`
  - approved Public client regeneration and affected Python/TypeScript client
    checks.
- Scope-drift check:
  - compare `git diff --name-status feat/agent-default-projects-plan...HEAD`
    with this plan;
  - reject changes to root Session creation, team-primary, subagent, External
    Channel, Agent Settings UI, testenv E2E, and living specs;
  - confirm no edits were made manually under generated client output paths;
  - confirm `agent_project_defaults` and `agent_project_presets` behavior is
    untouched;
  - confirm the diff contains no compatibility fallback or Project-count
    policy.
