---
title: "PR CI Wall-Clock Convergence Phase 1 Execution Plan"
created: 2026-08-06
tags: [ci, testing, testenv]
---

# Phase Execution Plan

- Phase: `1 — Module/application-image boundary correction`
- Branch/base:
  `perf/ci-five-minute-module-test-boundary` → `origin/main`
- PR boundary: Rename the test ownership category to module tests; move only the
  explicit fake/proxy/RustFS contracts; retain the Discord built-image assertion; and
  update required CI and test-strategy documentation.
- Inputs: Confirmed `ci-260806/REQ`, accepted `ci-260806/ADR`, approved
  `ci-260806/DESIGN`, current test strategy, and testenv rules.
- Deliverables: `src/module_tests`, module-local local-dependency fixtures, one
  retained Discord application-image assertion, renamed CI job/gate terminology, and
  updated living test strategy.
- Non-goals: A five-minute hard budget, CI sharding, REST contract rewrites, detailed
  application-image journey migration, backend/migration/Web Surface optimization, or
  any product behavior change.
- Interfaces: `module_tests` never builds an Azents application image;
  application-image tests continue under `src/tests`; the E2E terminal gate requires
  both applicable results.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`
- Authority references: `ci-260806/REQ-1` through `REQ-4`, `ci-260806/ADR-D1`
  through `ADR-D3`, `ci-260806/DESIGN`
- Design delta: `None`
- Removal obligations: Remove `unit_tests` path and affected unit ownership
  terminology.
- Absence verification: Repository search for `unit_tests` and unit CI result names;
  pytest collection confirms candidate ownership.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Module suite | `/root` | `testenv/azents/e2e/src/{module_tests,tests}` | M1–M3 | Moved contracts, local fixtures, retained image assertion | Collection and focused module/app tests |
| CI and documentation | `/root` | `.github/workflows/ci.yaml`, `testenv/azents/AGENTS.md`, `docs/azents/spec/flow/test-strategy-e2e-primary.md`, snapshot and plan docs | M4 | Explicit module/app ownership and current strategy | Workflow inspection, docs validation |
| Independent review | `/root/ci-boundary-reviewer` | Read-only complete diff | Completed implementation and validation | Coverage/boundary/scope findings | Review report |

- Integration order:
  1. Move the existing proxy-only checks and non-image contracts into the module suite.
  2. Add only the local fixtures necessary for RustFS and keep the image assertion in
     the application-image suite.
  3. Rename CI and testenv guidance to module terminology and preserve terminal gating.
  4. Update the living test strategy and generate docs indexes.
  5. Run focused and final validation, request independent review, correct any required
     findings, then open the focused PR.
- Independent review: `/root/ci-boundary-reviewer` reviews the final diff against the
  listed authority. Criteria: no coverage removal, no product-image build in module
  tests, retained Discord packaging assertion, correct CI gate behavior, no unrelated
  suite migration, and accurate current documentation.
- Final validation:
  - `cd testenv/azents/e2e && uv run pytest -vv ./src/module_tests`
  - retained Discord built-image assertion through `./src/tests`
  - `cd testenv/azents/e2e && uv run ruff format --check . && uv run ruff check . && uv run ty check --error-on-warning`
  - `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents`
  - `git diff --check`
- Scope-drift check: Confirm every moved test is one of the M2 files, only the M3
  Discord packaging assertion remains, and no duration budget, sharding, REST
  conversion, or product behavior is added.
- Context checkpoint: Base branch is `origin/main` at `b0fe8f6f6`. Final collection
  contains 81 module cases: 53 cases moved from application-image fake/proxy/RustFS
  contracts and 28 cases renamed from the former unit suite. One Discord packaging
  case remains application-image coverage. The next checkpoint records final paths,
  validation, review findings, and PR evidence.
