---
title: "Workspace-Owned Runtime Profiles Phase 8 Integrated Validation Plan"
created: 2026-07-31
updated: 2026-07-31
tags: [runtime, provider, workspace, profile, validation, migration, testenv]
---

# Workspace-Owned Runtime Profiles Phase 8 Integrated Validation Plan

## Phase Execution Plan

- Phase: `8 — Integrated validation`
- Branch/base: `feature/runtime-profiles-08-validation` →
  `feature/runtime-profiles-07-product-ui`
- PR boundary: add replacement E2E, migration, CI, and absence evidence; fix only defects
  discovered by that validation.
- Inputs: completed domain, resolution, Provider protocol, lifecycle/recreation, and product UI
  phases; `runtime-260730/REQ`, `runtime-260730/ADR`, and `runtime-260730/DESIGN`.
- Deliverables: deterministic product/API journeys, real Docker Provider execution evidence,
  migration equivalence and final-schema checks, legacy testenv/source absence checks, CI execution,
  and an implementation-versus-spec validation report.
- Non-goals: new Runtime Profile behavior, new configuration modules, rollout automation, future
  selection authorization, production deployment, live-cluster mutation, living-spec promotion, or
  plan cleanup.
- Interfaces: Workspace Runtime Profile CRUD/default/recreation APIs, nullable Agent
  `runtime_profile_id`, Agent Runtime configuration status and lifecycle APIs, Admin
  Provider-scoped infrastructure Profile and recreation APIs, authenticated current Provider
  capability advertisement, and exact desired/applied configuration evidence.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Product and Runtime E2E | `/root` | `testenv/azents/e2e/src/support/runtime_profiles.py`, `testenv/azents/e2e/src/tests/azents/public/test_runtime_profiles.py`, targeted `conftest.py` fixture support | Existing Docker Provider, generated Admin/Public clients, Phase 5 UI/API contract | Workspace default, explicit/unconfigured Agent selection, exact binding, desired/applied status, capability/provider unavailability recovery, and scoped recreation journeys | Focused runtime-provider E2E plus Ruff, Pyright, and deterministic E2E |
| Migration and authority absence | `/root` | `python/apps/azents/migration_tests/**`, validation-only repository search assertions | Phase 4 removal migrations and Phase 2 conversion migration | Legacy effective-selection equivalence, final-schema absence, and migration-only classification of residual legacy terms | Focused migration tests, full migration suite, and source/test search |
| Substrate and CI integration | `/root` | `.github/workflows/ci.yaml`, validation report under `docs/azents/design/` | Stable focused E2E node IDs and prerequisite behavior | Required CI execution for the new Runtime Profile journey and reproducible evidence/gap table | Workflow inspection, focused local run, required PR CI |
| Independent review | `hardtack` | Read-only review of the complete Phase 8 diff | Stable integrated diff and validation evidence | Review findings focused on authority fallback, security/data preservation, migration, and false-positive E2E assertions | GitHub review request and targeted re-review only for material findings |

- Integration order: store this plan; add focused API/Provider E2E and helpers; add migration and
  absence validation; wire stable E2E node IDs into CI; run the focused matrix; fix discovered
  defects without expanding product scope; record the final validation report and gap table; run
  final checks once on the stable diff.
- Independent review: `hardtack` reviews the final diff against `runtime-260730/REQ`,
  `runtime-260730/ADR`, `runtime-260730/DESIGN`, this phase plan, and the validation report. Review
  criteria are exact binding/no fallback, current-capability authority, desired/applied separation,
  explicit recreation, PVC/data preservation boundaries, migration equivalence, and complete legacy
  authority absence.
- Final validation:
  - `cd testenv/azents/e2e && uv run ruff check .`
  - `cd testenv/azents/e2e && uv run ruff format --check .`
  - `cd testenv/azents/e2e && uv run pyright .`
  - focused Runtime Profile E2E using the actual Docker Provider fixture;
  - deterministic non-Provider E2E for any credential-free API cases;
  - `cd python/apps/azents && uv run pytest -vv migration_tests`;
  - focused and full backend/provider tests whose evidence is cited by the matrix;
  - `git diff --check`;
  - repository searches for legacy execution-policy authority, Agent Provider overrides, Runtime
    policy snapshots, Apply paths, and obsolete testenv fixtures.
- Scope-drift check: compare the final handwritten diff separately from generated artifacts and
  immutable migrations. Every behavior change must be attributable to a validation-discovered
  defect in the approved replacement; otherwise remove it or return to feature design.
- Context checkpoint: Phase 1–5 behavior is implemented and Phase 4 CI is green. Phase 5 PR
  `#1051` is open with CI and independent review pending. The current phase begins with a clean
  branch. Existing E2E setup already authenticates and runs a real Docker Provider, creates one
  compatible Container Profile, and provides a Workspace Runtime Profile helper. Existing migration
  tests cover legacy effective-policy conversion, but integrated product journeys and final
  authority-absence evidence remain. The largest risk is keeping Provider E2E deterministic while
  proving asynchronous desired/applied and recreation states without direct database mutation.
