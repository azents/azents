---
title: "Automatic Session Default Projects Phase 5 Validation"
created: 2026-07-24
tags: [agent, projects, validation, testenv, e2e, documentation]
---
# Automatic Session Default Projects — Phase 5 Validation

## Phase Execution Plan

- Phase: `5 — E2E/testenv validation and living-spec drift comparison`
- Branch/base: `feat/agent-default-projects-validation` → `feat/agent-default-projects-web`
- PR boundary: Execute and record the approved backend, TypeScript, deterministic E2E, Runtime Provider, and Web Surface regression validation matrix; compare the implemented behavior strictly with current living specs; and correct only implementation defects discovered by validation.
- Inputs: [`agent-260724/REQ`](../requirements/agent-260724-automatic-session-default-projects.md), [`agent-260724/ADR`](../adr/agent-260724-automatic-session-default-projects.md), [`agent-260724/DESIGN`](../design/agent-260724-automatic-session-default-projects.md), the [multi-phase implementation plan](agent-260724-automatic-session-default-projects-implementation-plan.md), completed phase plans 1–4, and the implementation stack through `feat/agent-default-projects-web`.
- Deliverables:
  - A design-scoped validation report at `docs/azents/design/agent-260724-automatic-session-default-projects-validation-report.md` recording commands, environment, fixture readiness, evidence, failures, and fixes.
  - A requirement-to-validation matrix covering policy management, team-primary and explicit root creation, External Channel Allow and already-granted binding creation, old/new snapshots, subagent shared projection, Runtime-unavailable clear, missing path, revision conflict, and Web add/reorder/remove behavior as covered by existing `azents-web` unit/component tests, build, Storybook, and the repository Web Surface regression lane.
  - Recorded backend, TypeScript, deterministic E2E, Runtime Provider, and Web Surface regression lane results. When a local substrate is unavailable, record the exact blocker and use the corresponding GitHub Actions result as primary executable evidence after the stack exists.
  - A strict implementation-versus-current-spec comparison listing aligned behavior, implementation missing from specs, stale spec language, and any implementation defect. Spec edits remain deferred to Phase 6.
  - A temporary PR7 focused Runtime Provider lane attempt for the five feature tests. If the tests reach Runtime startup but the repository lacks a supported accepted-contract fixture prerequisite, record them as executed/blocked and do not expand Runtime Provider management or use direct product DB writes.
  - Focused implementation corrections only when validation exposes behavior that violates the approved snapshot. Every correction receives focused regression coverage.
- Non-goals: Living-spec edits or snapshot `implemented` dates; new product decisions; accepted ADR changes; plan cleanup; generated-client edits without an OpenAPI source change; provider/live-credential scenarios; unrelated refactors.
- Interfaces:
  - Feature-specific product assertions use generated Public API clients, supported HTTP paths, fake Slack, and Runtime/runner boundaries. UI behavior is covered by existing `azents-web` unit/component tests, build, Storybook, and the repository Web Surface regression lane; this phase does not add a new runtime-coupled browser journey. Validation never mutates product tables directly.
  - Session Project APIs remain the authoritative snapshot assertion surface.
  - The GitHub Actions run for PR 6/PR 7 may supply deterministic, Runtime Provider, or Web Surface regression evidence that cannot execute in the local agent runtime because `/var/run/docker.sock` is absent.
  - The validation report distinguishes locally executed evidence, CI-executed evidence, collection/static evidence, and unavailable optional evidence.
  - Current living specs are compared read-only in this phase. Drift is documented precisely for Phase 6 rather than silently corrected here.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Validation execution, evidence, and drift report | `validation-readiness (continued)` | `docs/azents/design/agent-260724-automatic-session-default-projects-validation-report.md`; read-only validation of implementation/spec/test paths; narrowly required test fixes only after primary-agent approval | Complete implementation through PR 6 and the fixed validation matrix | Sanitized evidence, fixture readiness, requirement coverage, and strict spec drift table | Backend/TypeScript/testenv commands, focused E2E lane commands or exact substrate blocker, GitHub Actions evidence |
| Integration and accepted validation fixes | Primary agent | Phase plan, report integration, and any localized correction paths required by accepted findings | Validation owner report | Final scope audit, correction verification, commit, and PR | Affected quality checks, complete final matrix, `git diff --check` |
| Independent review | `frontend-readiness (continued)` | Read-only complete Phase 5 diff and validation evidence | Primary verification complete | Severity-ranked review of evidence accuracy, requirement coverage, test integrity, drift classification, and phase boundary | Exact file/line and command evidence; no implementation edits |

- Integration order:
  1. Run static and non-Docker quality gates across backend, TypeScript, and testenv.
  2. Attempt the deterministic, Runtime Provider, and Web Surface commands exactly as planned; classify unavailable local Docker substrate explicitly rather than substituting weaker tests.
  3. Inspect available GitHub Actions runs for the stacked implementation PRs and record lane results with run/job identity. If the focused Runtime Provider lane cannot execute the feature tests because the repository lacks a supported accepted-contract fixture prerequisite, record that blocker rather than expanding Runtime Provider management or using direct database writes.
  4. Compare Requirements/Design behavior, implementation, E2E coverage, and current living specs without editing specs.
  5. If validation finds an implementation defect, the primary agent assigns it to the continuing responsible implementation owner, verifies the correction, and updates evidence.
  6. The primary agent integrates the report, runs final checks, requests independent review, applies accepted findings, commits, and creates PR 7 before Phase 6 begins.
- Independent review: Verify every report claim against command output, CI run identity, implementation code, E2E assertions, and current specs. Prioritize false-positive evidence, missing matrix scenarios, Docker/substrate claims, direct-DB violations, requirement/spec misclassification, unrecorded defects, and Phase 6/7 scope leakage.
- Final validation:
  - `cd python/apps/azents && uv run ruff check .`
  - `cd python/apps/azents && uv run ruff format --check .`
  - `cd python/apps/azents && uv run pyright .`
  - focused and full `python/apps/azents` pytest evidence from the implementation phases or a fresh run
  - `cd python/apps/azents && uv run python src/cli/dump_openapi.py && git diff --exit-code -- specs`
  - `cd typescript && pnpm run format:check`
  - `cd typescript && pnpm run lint`
  - `cd typescript && pnpm run typecheck`
  - `cd typescript && pnpm run build`
  - `cd typescript && pnpm --dir apps/azents-web test`
  - `cd typescript && pnpm --dir apps/azents-web build-storybook`
  - `cd testenv/azents/e2e && uv run ruff check .`
  - `cd testenv/azents/e2e && uv run ruff format --check .`
  - `cd testenv/azents/e2e && uv run pyright .`
  - `cd testenv/azents/e2e && uv run pytest -vv -m "not live_external and not runtime_provider and not web_surface" ./src`
  - `cd testenv/azents/e2e && uv run pytest -vv -m "runtime_provider and not live_external" ./src/tests/azents/public/test_automatic_session_projects.py`
  - `cd testenv/azents/e2e && uv run pytest -vv -m "web_surface and not live_external and not runtime_provider" ./src`
  - `git diff --check`
- Scope-drift check: Compare the branch against `feat/agent-default-projects-web`. The expected tracked diff is only this phase plan and the validation report; only corrections proven necessary by recorded validation failures are allowed. Confirm there are no workflow changes, living-spec edits, Requirements/ADR/Design snapshot status changes, cleanup deletions, new migrations or API contracts, generated clients, provider credentials, live-provider tests, or unrelated refactors.
