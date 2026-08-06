---
title: "PR CI Wall-Clock Convergence"
created: 2026-08-06
tags: [ci, testing, architecture]
document_role: primary
document_type: adr
snapshot_id: ci-260806
---

# ci-260806/ADR: PR CI Wall-Clock Convergence

- Requirements:
  [`ci-260806/REQ`](../requirements/ci-260806-pr-ci-convergence.md)

## Context

Required pull-request CI currently has application-image work on its critical path
that is not always application-image coverage. The confirmed Requirements define two
test categories by execution boundary and require gradual convergence of the full
required critical path toward five minutes while retaining coverage.

## Decision Backlog

| Order | Decision point | Status |
| --- | --- | --- |
| D1 | Test execution-boundary taxonomy | Accepted |
| D2 | Five-minute enforcement posture | Accepted |
| D3 | First boundary-correction scope | Accepted |

## Decisions

### ci-260806/ADR-D1 — Classify tests by whether they build the Azents application image

A **module test** imports and exercises Azents modules, possibly using directly
required local dependencies such as Testcontainers, HTTP, WebSocket, or storage. It
does not build the Azents application image. An **application-image test** builds the
Azents application image and validates behavior through the resulting container
boundary.

The repository does not retain a separate CI ownership category for “unit tests.”
Existing Docker-free checks become module tests, and module tests may use local
dependencies when their behavior does not require a built application image.

This decision implements `ci-260806/REQ-2` and `ci-260806/REQ-4`.

Classifying by dependency weight, test speed, or whether a test opens a listener is
rejected because none of those criteria establishes whether the Azents image boundary
is under test.

### ci-260806/ADR-D2 — Treat five minutes as a progressive critical-path SLO

Five minutes is the target for the required pull-request CI critical path, not an
immediate CI budget that fails a pull request. Each focused optimization retains
coverage, measures the affected required path, and creates a basis for a later,
evidence-backed budget ratchet.

This decision implements `ci-260806/REQ-1`.

An immediate hard duration gate is rejected because the currently required backend,
application-image, migration, and Web Surface paths exceed that target; a premature
gate would fail correct pull requests without proving a coverage-preserving path to
compliance.

### ci-260806/ADR-D3 — Move only clearly non-image contracts in the first slice

The first slice moves the Discord and Slack provider-fake contracts, GitHub validation
proxy contract, RustFS transfer-storage contracts, and existing proxy-only checks to
the module suite. It retains the Discord assertion that verifies the fake is packaged
into the built Azents application image as an application-image test.

The slice does not move direct REST application-image contracts, detailed application
journeys, or any test lacking explicit equivalent module coverage.

This decision implements `ci-260806/REQ-3`.

Moving the entire deterministic suite is rejected because representative built-image
and user-journey coverage must remain at the application-image boundary.

## Consequences

- Required CI has distinct module and application-image test commands and gate results.
- Module coverage may exercise local services without paying the Azents image-build
  cost.
- The first slice improves the application-image lane incrementally but does not by
  itself establish five-minute feasibility.

## Risks to Resolve

- Renaming the existing test path and CI job must preserve path-filter and terminal
  gate behavior.
- A test moved from the application-image suite must not accidentally retain a hidden
  fixture dependency on a built Azents container.
- Later application-image reductions require explicit coverage mapping, not duration
  estimates alone.
