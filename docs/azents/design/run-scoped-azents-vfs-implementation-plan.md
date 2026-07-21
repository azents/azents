---
title: "Run-Scoped Azents VFS Implementation Plan"
created: 2026-07-19
updated: 2026-07-21
tags: [backend, engine, toolkit, skill, storage, testing]
---

# Run-Scoped Azents VFS Implementation Plan

## Feature Summary

Implement the design in [Run-Scoped Azents Virtual Filesystem](./run-scoped-azents-vfs.md) and ADR-0168. The feature adds immutable per-run `azents://` projections, release/provider-managed Skills, dual-locator `load_skill`, and `azents://` materialization through `import_file` without changing filesystem Skill behavior.

## Stack and Phase Boundaries

### PR 1 — Design

- Finalize ADR-0168.
- Add the feature design and E2E-first test strategy.

### PR 2 — Implementation Plan

- Record implementation phases, dependencies, validation matrix, prerequisites, rollout, spec impact, and cleanup.

### PR 3 — Phase 1: VFS Core and Run Persistence

- Add canonical URI parsing and validation.
- Add immutable VFS source, entry, and projection models.
- Add package-resource release source loading with deterministic hashing, collision detection, size limits, and independent last-successful source slices.
- Add global and provider release resource registration.
- Add nullable `agent_runs.vfs_projection` through generated Alembic migration and repository/domain support.
- Add atomic projection set-if-empty behavior.
- Ensure RunExecutor creates or reuses the projection before input-buffer promotion.
- Add unit, repository, migration, run lifecycle, recovery, provider eligibility, package data, and subagent-path tests.

### PR 4 — Phase 2: Skill and Import Integration

- Merge managed Skill entries with existing filesystem Skill prompt/action views.
- Resolve managed SkillAction content from the active run projection.
- Extend `load_skill` to dispatch between absolute filesystem paths and canonical `azents://` Skill URIs.
- Add idle composer preview and active-run action projection behavior.
- Add the `azents` import resolver with run ownership, membership, size, and hash verification.
- Inject current run context into Runtime `import_file` construction.
- Add managed Skill body/resource fixtures and regression tests for all existing filesystem behavior.

### PR 5 — Validation and Spec Promotion

- Run backend Ruff, format, Pyright, full Pytest, migration checks, package build inspection, and applicable deterministic E2E.
- Record failures and fixes.
- Compare implementation against Toolkit and Agent Execution Loop specs.
- Update living specs and `last_verified_at`.
- Mark the design implemented only after verification.

### PR 6 — Cleanup

- Remove this implementation plan after specs and implemented design are authoritative.
- Keep behavior changes out of cleanup.

## Dependencies

- PR 2 depends on PR 1.
- Phase 1 depends on the accepted persistence and lifecycle decisions in PR 1.
- Phase 2 depends on Phase 1 domain/repository/service contracts.
- Validation/spec promotion depends on both implementation phases.
- Cleanup depends on complete validation and spec promotion.

## Data, API, and Runtime Changes

### Data

- Nullable JSONB `agent_runs.vfs_projection`.
- Projection JSON is schema-versioned and self-contained.
- No new public catalog or assignment tables in this feature.

### API

- No new public route or action schema.
- Existing `SkillAction.skill_path` accepts canonical managed Skill URIs.
- Input action list may contain both absolute filesystem paths and `azents://` URIs.

### Runtime

- RunExecutor freezes VFS before initial input promotion.
- Skill Toolkit queries the exact current run projection each turn.
- Runtime Toolkit injects current run ID into the `azents` import resolver.
- Ordinary file tools remain Runtime-path-only.

## Test Strategy by Phase

### Phase 1

- URI parser table tests for canonical and rejected forms.
- Source publication tests for ordering, hashes, media types, traversal, symlinks, empty sources, and size bounds.
- Projection tests for deterministic merge, identical content, cross-source collision, optional-source diagnostics, and enabled provider filtering.
- AgentRun repository tests for null, set-if-empty, idempotent recovery, and ownership validation.
- RunExecutor ordering test proving projection ensure precedes `poll_run_inputs`.
- Package build test proving release Markdown/resources are included.

### Phase 2

- Combined Skill prompt ordering and duplicate-slug coexistence tests.
- `load_skill` filesystem regression and managed URI success/failure tests.
- SkillAction promotion tests for filesystem and managed entries using the active run ID.
- Composer preview tests for idle and active run behavior.
- `AzentsImportResolver` tests for success, invalid URI, missing membership, ownership mismatch, Base64 corruption, size mismatch, and hash mismatch.
- Runtime `import_file` tests for managed resource default naming and destination collision behavior.

### Validation

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pyright`
- targeted tests after each phase
- `uv run pytest` before spec promotion
- Alembic current-head/revision validation
- wheel build and archive inspection for release resources
- deterministic backend/E2E managed Skill flow

## E2E Primary Validation Matrix

| User-visible behavior | Setup | Action | Assertion |
| --- | --- | --- | --- |
| Global managed Skill discovery | Agent session, no provider Toolkit | Fetch input actions | `azents://skills/azents/.../SKILL.md` appears. |
| Provider managed Skill discovery | Enabled GitHub Toolkit attachment | Fetch input actions | GitHub namespace Skill appears. |
| Disabled provider filtering | Disabled ToolkitConfig | Fetch input actions | Provider Skill is absent. |
| Managed Skill action | Select managed action with message | Run worker | `skill_loaded` precedes user message and hash matches run projection. |
| Managed `load_skill` | Active run projection | Call tool with URI | Returned body and revision metadata match projection. |
| Adjacent import | Runtime-enabled Agent | Import resource URI | Local bytes and hash match projected entry. |
| Run immutability | Change release catalog fixture after run freeze | Load/import again | Existing run returns original bytes; new run receives new revision. |
| Filesystem coexistence | Register Project filesystem Skill with same slug | Fetch/load both | Both locators remain separately available and exact resolution succeeds. |
| Subagent independence | Spawn child with differing attachment eligibility | Inspect child run | Child projection is independently selected and persisted. |

## Fixtures and Prerequisites

- Package-data fixtures: one global Skill with an adjacent reference and one GitHub Provider Skill with an adjacent template.
- Database fixtures: AgentRun with null/set projection; enabled and disabled AgentToolkit/ToolkitConfig combinations.
- Worker fixture: deterministic pending run and SkillAction input buffer.
- Runtime fixture: in-memory or test Runner FileStorage for import materialization.
- No third-party network, OAuth connection, or live provider credentials are required.
- If deterministic model E2E cannot guarantee both `load_skill` and `import_file` calls, backend integration tests are the blocking verification and the E2E limitation is recorded rather than silently skipped.

## Blockers and Manual Actions

No known external blockers. CI must provide PostgreSQL for repository/migration tests and the existing Runtime test prerequisite for materialization E2E.

## Spec Impact Candidates

- `docs/azents/spec/domain/toolkit.md`
  - managed release resources;
  - combined Skill source behavior;
  - `azents://` import support and Runtime boundary.
- `docs/azents/spec/flow/agent-execution-loop.md`
  - pre-promotion VFS freeze;
  - SkillAction and `load_skill` run snapshot semantics;
  - retry/recovery/subagent behavior.

## Rollout and Observability

- The migration is additive and nullable.
- Log projection construction duration, source count, entry count, decoded bytes, projection hash, and bounded diagnostics without logging content.
- Log resolver failures with run/session/agent identifiers and error code without logging file bodies.
- Package-build validation verifies required release resources; projection construction fails if an invalid required source has no retained successful in-process slice.
- Rollback leaves unused JSONB data and preserves existing filesystem Skills.

## Cleanup

After validation and spec promotion, delete this plan. The retained sources of truth are ADR-0168, the implemented design record, current specs, migrations, and code.
