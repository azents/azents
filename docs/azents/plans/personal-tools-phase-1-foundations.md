---
title: "Personal Tools Phase 1: Ownership and Permission Foundations"
created: 2026-10-17
updated: 2026-10-17
tags: [toolkit, implementation, database, security]
---

# Phase Execution Plan

> Historical revision 1 execution record. Its User-global scope is superseded by the requester-
> confirmed Workspace boundary and approved Design revision 2. Continue under the
> [Workspace foundation correction plan](personal-tools-workspace-foundation-correction.md), not the
> global ownership or cross-Workspace selection described below. Prior evidence proves only its
> original diff; it is not corrected-scope acceptance.

- Phase: 1/4, ownership and permission foundations.
- Branch/base: `design/personal-tool-access-261017` -> `main` at 4fffac913.
- PR boundary: constrained owner/policy persistence, safe existing shared projections, personal
  permission operations and tests, with approved design baseline and implementation plans.
- Inputs: confirmed Requirements, accepted D1-D3, approved Design r1 M1-M11; existing Toolkit and
  namespace, User/Workspace/Agent model and repository conventions.
- Deliverables: canonical ownership types; User-owned Toolkit schema and migration; All/Selected
  positive permission persistence and atomic intent mutation; existing shared readers stay narrow.
- Non-goals: public personal routes, OAuth adaptation, personal execution projection, Web UI, live
  Provider use or deployment. No new feature flag/relay/versioning mechanism.
- Interfaces: one Toolkit ID, legal mutually exclusive owners, User-global no Workspace; personal
  mode All/Selected; positive memberships keyed by canonical Agent; existing Workspace DTOs unchanged.
- Approved Design mechanisms: M1, M2, M10, M11 (foundation scope).
- Authority: REQ-1/2/4/6/7/8/9, ADR-D1/D2/D3, Design sections 3/4/8/9/10.
- Design delta: None.
- Removal obligations: replace universal owning-Workspace storage assumption and null-Agent-only
  shared predicates in touched readers; preserve existing shared/Agent resources and contracts.
- Absence verification: owner-shape and foreign-personal tests; search touched shared predicates;
  existing Toolkit tests and metadata/migration assertions.

| Workstream | Owner | Paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Owner schema/domain | /root | core Toolkit ownership, rdb Toolkit model and new migration | approved D1 | legal owner/policy variants | parsing/model/schema and migration tests |
| Repository guard/policy | /root | repos/toolkit and new personal operations/data | owner schema | owner-safe shared reads and atomic policy intent | existing repo regression and isolated DB tests |
| Authority/evidence | /root | snapshot docs and phase plans | completed code | unchanged r1 approval plus checkpoint | docs catalog, diff check |

- Integration order: dependency setup -> schema/types -> forward migration -> existing shared
  predicates -> personal persistence/policy -> focused checks -> stable integrated reviewer request.
- Independent reviewer: `/root/personal-tools-reviewer`; read-only review requested by root after
  implementation and integrated validation. Root applies corrections and runs all verification.
- Final validation: Ruff format/check, configured ty, focused pytest with isolated DB fixture when
  required, migration assertions, docs validation and git diff check. Record actual commands/results.
- Scope drift: do not expose a partial personal API, bypass Provider auth, add owner fallbacks, or
  broaden personal source into shared execution. Later phases consume these foundations explicitly.
- Context checkpoint: foundation implementation complete and independently reviewing; schema remains
  unapplied to any production system. No public personal route or runtime/UI capability is activated.

## Integrated Checkpoint

- Implemented legal Workspace/Agent/User storage, explicit detached owner types, PostgreSQL ownership
  and policy enums, positive membership with exact parent/owner composite FK, and preserving forward
  migration with predecessor owner classification.
- Shared CRUD/attachment/effective projections reject personal IDs; existing Workspace and Agent
  projections retain their wire fields. Personal CRUD shares canonical configuration and encryption.
- Both editor entry points can consume one completed transaction composition: sorted parent locks,
  server-side cross-Workspace ordinary eligibility, atomic All-to-Selected and delta preservation,
  and all-or-none multi-connection mutation. Expected-mode conflicts reject stale editor assumptions
  under the parent lock. No caller-supplied replacement baseline is accepted.
- Removal evidence: shared null-Agent-only predicates are replaced by an explicit Workspace-owner
  predicate; no synthetic Workspace, alternate personal aggregate, feature flag or new version field.
- Integrated validation on Python 3.14 with isolated Docker PostgreSQL 17 (2026-10-17):
  - `uv run ty check --error-on-warning`: passed.
  - Backend-wide `uv run ruff check .` and `uv run ruff format --check .`: passed
    (2528 files formatted).
  - `uv run pytest -q src/azents/core/toolkit_ownership_test.py src/azents/repos/toolkit
    src/azents/repos/toolkit_namespace_test.py src/azents/repos/toolkit_oauth_operations_test.py
    src/azents/repos/toolkit_operations src/azents/repos/mcp_oauth_connection/operation_boundary_test.py
    src/azents/repos/agent_github_cleanup_boundary_test.py
    src/azents/repos/github_user_oauth src/azents/repos/google_oauth
    src/azents/services/toolkit`: 320 passed in 17.34s.
  - `uv run pytest -q migration_tests`: 48 passed in 69.25s, including head/upgrade/metadata
    alignment, preservation/classification, invalid-owner failure and guarded downgrade.
  - `python scripts/docs_catalog.py validate` and `git diff --check`: passed.
- Initial validation fixes: explicit Agent-before-Workspace fixture cleanup; realistic migration seed
  constraints/defaults; update duplicate-attachment unit fake for its new guarded lookup. No gate,
  assertion, timeout or product behavior was relaxed.
- Existing testcontainers deprecations and metadata-cycle warning remain visible; no feature test
  was skipped. Runtime, full E2E and live Providers are later-phase/unverified scope.
- Independent review by `/root/personal-tools-reviewer`: identified missing persisted owner-kind and
  stale-mode protection required by Design sections 3.1/3.3. Root added both, updated affected raw SQL
  fixtures to the explicit owner contract, and reran expanded regressions and the complete migration
  suite. The same reviewer completed targeted material re-review with no remaining findings.
  PR/CI checkpoint follows the phase commit.
- Additional full backend regression is running. An earlier pre-correction full run was deliberately
  interrupted for the material fixes (6919 passed before interruption); this is not full-suite
  acceptance evidence. Design delta: None.
