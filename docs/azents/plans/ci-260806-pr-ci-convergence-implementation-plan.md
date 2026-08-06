---
title: "PR CI Wall-Clock Convergence Implementation Plan"
created: 2026-08-06
tags: [ci, testing, testenv]
---

# PR CI Wall-Clock Convergence Implementation Plan

## Source of truth

- Requirements:
  `docs/azents/requirements/ci-260806-pr-ci-convergence.md`
- ADR: `docs/azents/adr/ci-260806-pr-ci-convergence.md`
- Design: `docs/azents/design/ci-260806-pr-ci-convergence.md`
- Current specs:
  - `docs/azents/spec/flow/test-strategy-e2e-primary.md`
  - `testenv/azents/AGENTS.md`

## Delivery Shape

One focused PR delivers the first boundary-correction slice. It preserves all listed
test assertions, replaces the unit ownership category with module tests, keeps the
single Discord built-image packaging assertion as application-image coverage, updates
CI and current test strategy documentation, and does not impose a duration gate.

## Approved Design Mechanisms

`M1`, `M2`, `M3`, `M4` from `ci-260806/DESIGN`.

## Ownership and Review

| Role | Owner | Scope |
| --- | --- | --- |
| Implementation and integration | `/root` | Test layout, module fixtures, CI, living specs, validation |
| Independent review | `/root/ci-boundary-reviewer` | Read-only review against `ci-260806` Requirements, ADR, Design, current strategy, and final diff |

## One-PR Phase

| Phase | Boundary | Dependencies | Completion evidence |
| --- | --- | --- | --- |
| 1 | Module/app test-boundary correction | Approved `ci-260806` snapshot | Collection, focused module tests, retained application-image assertion, static quality checks, docs validation, independent review |

## Interfaces and Constraints

- `src/module_tests` owns all non-image contracts in this first slice.
- `src/tests` owns the retained built-image packaging assertion.
- `ci-testenv-module-run` executes the module path; deterministic application-image
  invocation remains marker-compatible and retains observability artifacts.
- `ci-python-e2e` continues to require both changed test-boundary results.
- No direct product database writes are added.
- No app-image case outside Design M2/M3 changes ownership.

## Removal Obligations

- Remove the `src/unit_tests` directory by renaming its checks into
  `src/module_tests`.
- Remove `unit` test-boundary terminology from affected CI and testenv guidance.
- Prove absence with repository search and pytest collection.

## Validation

1. Collect and run affected module tests.
2. Run the retained deterministic built-image assertion.
3. Run testenv Ruff format/check and `ty --error-on-warning`.
4. Validate documentation indexes and current spec metadata.
5. Review the final scope for coverage loss or unapproved application-image changes.
6. Request independent read-only review from `/root/ci-boundary-reviewer`.

## Design delta

None.
