---
title: "PR CI Wall-Clock Convergence Requirements"
created: 2026-08-06
updated: 2026-08-06
implemented: 2026-08-06
tags: [ci, testing, developer-experience]
document_role: primary
document_type: requirements
snapshot_id: ci-260806
---

# PR CI Wall-Clock Convergence Requirements

- Snapshot: `ci-260806`
- Document reference: `ci-260806/REQ`

## Problem

Required CI for an Azents pull request can keep contributors waiting substantially
longer than five minutes. Some tests that do not validate a built Azents application
image currently wait in the application-image lane, extending its wall-clock time and
obscuring the purpose of each test boundary.

## Primary Actor

An Azents contributor waiting for required pull-request CI feedback.

## Primary Scenario

A contributor opens a pull request. Required CI runs the appropriate module and
application-image test coverage, reports failures at the boundary that owns the
behavior, and progressively converges the pull request's critical-path wait toward
five minutes without removing required coverage.

## Supporting Scenarios

- A maintainer can tell whether a test imports and exercises modules or validates a
  built application container.
- A protocol fake, proxy, or storage contract test can run with its required local
  dependency without being treated as application-image coverage.
- A representative application-image assertion remains when it specifically verifies
  that a required test asset is packaged into the built image.

## Goals

- Progressively converge required pull-request CI critical-path wall-clock time to five
  minutes or less.
- Retain coverage while assigning each test to its correct execution boundary.
- Use one clear test taxonomy for contributor-facing CI feedback.

## Non-Goals

- Immediately make five minutes a required CI failure threshold.
- Remove behavior coverage solely to reduce CI duration.
- Require every module test to be Docker-free or network-free.
- Parallelize or shard the existing application-image suite in this first slice.
- Reclassify detailed application-image behavior without explicit equivalent module
  coverage and a retained representative application-image journey.

## Requirements

### REQ-1. Progressive pull-request CI convergence

Required pull-request CI must be optimized toward a five-minute critical path through
incremental, coverage-preserving changes.

**Acceptance criteria**

- The five-minute target is recorded as the direction and final SLO, not an immediate
  pass/fail threshold.
- Each optimization preserves the behavior coverage previously owned by required CI.
- CI duration is evaluated by the full required critical path for affected pull-request
  scopes, not only by one pytest command.

### REQ-2. Two execution-boundary test taxonomy

Test ownership must use exactly two execution-boundary categories: module test and
application-image test.

**Acceptance criteria**

- A module test imports and exercises Azents code or its directly required local
  dependencies without building the Azents application image.
- An application-image test builds the Azents application image and validates behavior
  through the resulting container boundary.
- Repository naming and required CI commands use the module/application-image
  distinction rather than maintaining a separate unit-test category.

### REQ-3. First coverage-preserving boundary correction

Clearly non-application-image fake, proxy, and RustFS transfer-storage tests must run
as module tests.

**Acceptance criteria**

- Discord and Slack fake contracts, the GitHub validation proxy contract, RustFS
  transfer-storage contracts, and existing proxy-only module checks run in the module
  test suite.
- These tests do not cause the application-image test command to build or execute them.
- The Discord assertion that verifies the provider fake is packaged into the Azents
  application image remains in application-image coverage.

### REQ-4. CI failure ownership and observability

Required CI must continue to fail when either changed test boundary fails and must make
the module and application-image boundary visible to contributors.

**Acceptance criteria**

- The module test command and application-image test command are independently
  executable in CI.
- The required E2E gate checks both applicable results.
- Existing deterministic application-image observability remains available for the
  application-image lane.

## Fixed Constraints

- Preserve all current test assertions in scope; changing the execution boundary does
  not authorize behavior removal.
- Module tests may use Testcontainers, local HTTP, local WebSocket, or local storage
  dependencies when they do not build the Azents application image.
- Application-image tests retain representative built-container and user-journey
  coverage.
- The initial scope is limited to the explicit fake, proxy, RustFS, and existing
  proxy-only module checks.

## Open Assumptions

- Later slices will map costly detailed application-image cases to explicit equivalent
  module coverage before moving them.
- Later slices may address other critical-path contributors such as backend,
  migration, and Web Surface CI.

## Confirmation

Confirmed by the requester on 2026-08-06. The requester defined the two categories
by execution boundary and confirmed the gradual five-minute pull-request CI target.
