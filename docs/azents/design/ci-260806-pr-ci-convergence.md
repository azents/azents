---
title: "PR CI Wall-Clock Convergence Design"
created: 2026-08-06
implemented: 2026-08-06
tags: [ci, testing, testenv]
document_role: primary
document_type: design
snapshot_id: ci-260806
---

# ci-260806/DESIGN: PR CI Wall-Clock Convergence

## Inputs

- Confirmed [`ci-260806/REQ`](../requirements/ci-260806-pr-ci-convergence.md)
- Accepted [`ci-260806/ADR`](../adr/ci-260806-pr-ci-convergence.md)
- Current [`E2E Primary Test Strategy`](../spec/flow/test-strategy-e2e-primary.md)
- `testenv/azents/AGENTS.md`
- `.github/workflows/ci.yaml`

## Summary

This first, single-PR slice corrects test ownership without changing product behavior.
The test environment will expose two execution-boundary suites:

- `src/module_tests`: tests that import and exercise Azents modules or their local
  dependency contracts without building the Azents application image.
- `src/tests`: application-image tests that build the Azents image and validate it
  through the resulting container boundary.

The existing module checks and clearly non-image Discord, Slack, GitHub, and RustFS
contracts move to `src/module_tests`. The sole Discord assertion that verifies
the fake is present inside the built Azents server image remains in `src/tests`.

## Current Behavior and Gap

The required job named `ci-testenv-unit-run` runs only `src/unit_tests`, whose project
rule forbids listeners, Docker, browser state, and Runtime Provider state. The
deterministic application-image job runs every test in `src/tests`, including fake,
proxy, and RustFS contracts that do not build the Azents image. This makes
application-image timing include contracts whose exercised boundary is module-level.

## Traceability

| Requirement | Design mechanisms |
| --- | --- |
| `ci-260806/REQ-1` | M1, M4 |
| `ci-260806/REQ-2` | M1, M2 |
| `ci-260806/REQ-3` | M2, M3 |
| `ci-260806/REQ-4` | M4 |

## Test Suite Layout

### M1 — Replace the separate unit suite name with the module suite

Rename `src/unit_tests` to `src/module_tests`. Its existing checks retain their
assertions and become module tests. Add module-local fixtures for tests that
need a local server or RustFS Testcontainer.

`src/module_tests` may use local Docker, HTTP, WebSocket, and storage dependencies.
It must not build the Azents application image, start an Azents application container,
or use browser, Runtime Provider, or external prerequisite state.

### M2 — Move non-image protocol and storage contracts to module tests

Move these test modules from `src/tests` to `src/module_tests`:

- `test_discord_provider_fake.py`, except its image-packaging assertion;
- `test_slack_provider_fake.py`;
- `test_github_validation_proxy.py`;
- `test_runtime_transfer_storage.py`.

Their fixture ownership follows the suite: standalone fake and proxy fixtures remain
local to their test modules, while RustFS fixtures live in the module suite
`conftest.py`. The RustFS fixtures use an isolated local Testcontainers network,
ephemeral S3 credentials, and an isolated bucket. No fixture starts a built Azents
container.

### M3 — Retain the Discord image-packaging assertion as application-image coverage

Keep `test_discord_fake_container_uses_the_azents_server_image` under `src/tests` in
a focused module containing only the built-image assertion. It may use the existing
application-image fixture because it verifies a property unavailable to module tests:
the fake executable is packaged into the built Azents server image.

### M4 — Make module and application-image CI ownership explicit

Rename the required testenv CI job and terminal-gate variable from `unit` to `module`.
The module job runs `pytest -vv ./src/module_tests`; the deterministic job continues
to run `pytest` only for `./src/tests` with the existing deterministic marker
selection and observability artifact flow.

The changed-scope condition remains `python_e2e`, so a change in either suite runs both
required test boundaries. The E2E terminal gate requires the module result and the
deterministic application-image result when that scope changes.

## Failure and Isolation Behavior

- Fixture cleanup must shut down local servers, join their threads, and close
  Testcontainers resources.
- Module tests preserve their existing bounded request timeouts, redaction assertions,
  and per-test isolated state.
- The suite path determines CI ownership; pytest markers remain responsible only for
  special application-image lane selection such as Web Surface or Runtime Provider.

## Test Strategy

| Behavior | Primary verification |
| --- | --- |
| Provider fake and proxy protocol contracts | Module tests with local servers |
| RustFS S3 transfer contract | Module tests with local RustFS Testcontainer |
| Provider fake included in built server image | One deterministic application-image test |
| Module/application-image CI dispatch and terminal gating | Workflow inspection plus affected CI-equivalent commands |

## Removal and Replacement

| Removed or replaced unit | Replacement | Absence evidence |
| --- | --- | --- |
| `src/unit_tests` test ownership category | `src/module_tests` | No `unit_tests` path or unit CI result remains in workflow, testenv guidance, or selected test configuration |
| Non-image contracts in `src/tests` | Equivalent unchanged modules in `src/module_tests` | Deterministic collection contains only the retained Discord image assertion from this candidate group |

## Feasibility Validation

Final collection identifies 81 module pytest cases: 53 cases moved from the
application-image fake/proxy/RustFS contracts and 28 existing `unit_tests` cases
renamed into the module ownership category. One Discord built-image packaging case
remains an application-image test. The moved contracts import support modules or use
local dependencies; none requires an Azents application image.

## Design Authority

Revision: `initial`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- |
| M1 | `module_tests` replaces the separate unit suite name | `ci-260806/REQ-2`, ADR-D1 | Required |
| M2 | Move explicit non-image fake/proxy/RustFS contracts | `ci-260806/REQ-3`, ADR-D3 | Required |
| M3 | Retain the Discord image-packaging assertion in app tests | `ci-260806/REQ-3`, ADR-D3 | Required |
| M4 | Rename required CI ownership and preserve terminal gate | `ci-260806/REQ-4`, ADR-D1 | Required |

## Non-Blocking Risks

- This slice reduces deterministic application-image work but does not make a
  five-minute critical path feasible on its own.
- More costly application-image cases require coverage mapping before any move.
- The full critical path also includes backend, migration, and Web Surface work that
  are outside this slice.

## Design Approval

- Mode: Autonomous approval after repository-grounded feasibility validation
- Decision owner: `/root`
- Approved on: `2026-08-06`
- Approved Design revision: `initial`
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`
- Approved scope: Replace the unit ownership category with module tests, move only
  explicit non-image fake/proxy/RustFS contracts, retain the Discord image-packaging
  assertion, and rename the required CI ownership boundary.
