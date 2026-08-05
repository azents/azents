---
title: "E2E CI Performance and Reliability Research"
created: 2026-08-03
tags: [testing, e2e, ci, reliability, performance, testenv]
status: research-note
---

# E2E CI Performance and Reliability Research

This note records a repository and GitHub Actions investigation into the current
Azents E2E suite. It captures the observed CI topology, test inventory, runtime and
failure evidence, layering problems, and a proposed migration direction.

This is not an approved design or implementation plan. Any material change to the
current E2E-primary strategy should be reconciled with the living test strategy spec
and, where required, developed through a new Requirements, ADR, and Design snapshot.

## Research Questions

The investigation addressed the following questions:

1. What do the current E2E CI jobs actually execute?
2. Are all tests meaningful as full-stack E2E tests?
3. Where does CI time go?
4. Which failures appear concentrated in unstable boundaries?
5. What structure would produce faster and more reliable required CI?

## Sources Inspected

Primary repository sources:

- `.github/workflows/ci.yaml`
- `testenv/azents/e2e/pyproject.toml`
- `testenv/azents/e2e/src/tests/conftest.py`
- `testenv/azents/e2e/src/tests/**`
- `docs/azents/spec/flow/test-strategy-e2e-primary.md`
- `testenv/azents/AGENTS.md`

Operational evidence:

- The latest 70 CI workflow runs available during the investigation.
- Job timing and conclusion data for the E2E jobs.
- Failed-job logs for recent deterministic, Web Surface, and focused Runtime
  Provider executions.
- Successful-job logs used to estimate setup and test execution concentration.
- Pytest collection results for all configured markers.

## Current CI Topology

### Deterministic E2E

Job: `ci-deterministic-e2e-run`

Selection:

```text
not live_external and not runtime_provider and not web_surface
```

Collected scope:

- 309 of 334 tests.
- Product API tests.
- Worker and model-stream journeys.
- External Channel fake-provider journeys.
- Test fake, proxy, readiness, and support-helper tests.

The name implies a homogeneous deterministic product suite, but the lane currently
contains several different test layers and environment requirements.

### Web Surface E2E

Job: `ci-web-surface-e2e-run`

Selection:

```text
web_surface and not live_external and not runtime_provider
```

Collected scope:

- 7 browser tests.
- Main Web and Admin Web images built from the tested worktree.
- TLS gateway and remote Chromium containers.
- Public and Admin API containers and their shared infrastructure.

### Focused Runtime Provider E2E

Job: `ci-tool-search-runtime-provider-e2e-run`

The repository contains 16 tests marked `runtime_provider`, but the required job does
not select the marker. It hardcodes four node IDs:

- Two Runtime Hooks tests.
- One provider-native External Channel progress test.
- One Runtime Profile recreation test.

The job name is a historical description rather than an accurate statement of its
current scope.

The PR path filter for this lane also focuses on the workflow and selected E2E support
or test files. It does not cover the full set of backend, Runtime Control, Runtime
Runner, and Runtime Provider product paths that can change the tested behavior. Main
branch pushes run all scopes, but a relevant product change may avoid this focused
lane during pull-request validation.

### Aggregate Gate

Job: `ci-python-e2e`

This job executes no tests. It aggregates the selected deterministic, focused Runtime
Provider, and Web Surface results into the stable required check.

### Live External

Pytest collection finds two `live_external` tests. Both validate prerequisite snapshot
availability rather than execute a live product journey.

The living strategy documents label-, manual-, and nightly-triggered live workflows,
but no corresponding live E2E workflow implementation was found in the current
workflow directory during this investigation.

## Test Inventory

Pytest collected 334 tests in total.

| Category | Collected tests | Notes |
| --- | ---: | --- |
| Deterministic selection | 309 | Mixed product E2E, API tests, and support tests |
| Web Surface | 7 | Real browser and worktree-built web images |
| Runtime Provider | 16 | Required CI executes only four |
| Live External | 2 | Prerequisite snapshot checks |

The source tree contains:

- 44 product test files under `src/tests/azents/`.
- 11 root support test files under `src/tests/test_*.py`.
- Approximately 26,769 lines in product test files.
- Approximately 3,440 lines in root support test files.

The root support tests expand to 87 collected cases because of parametrization. They
cover provider fakes, proxies, readiness helpers, Runtime Provider authentication, and
shared support utilities. These tests are useful, but they are component tests rather
than product E2E journeys.

## Fixture and Isolation Findings

`conftest.py` defines 49 fixtures:

- 45 session-scoped fixtures.
- 4 function-scoped fixtures.

The shared session environment can include:

- PostgreSQL.
- Valkey.
- RustFS.
- AIMock and the OpenAI proxy.
- GitHub validation proxy.
- Slack and Discord provider fakes.
- Public and Admin API servers.
- Engine worker.
- Runtime Control and Runtime Provider.
- Main Web and Admin Web.
- TLS gateway and Selenium.

The suite generally creates unique users and workspaces, but several asynchronous
boundaries retain session-wide fake state or background work. A reset request cannot
prevent work started by a previous test from arriving after that reset. This creates a
plausible cross-test contamination mechanism even without pytest process-level
parallelism.

The E2E source tree contains 74 explicit `sleep` calls. Some implement bounded polling,
but the amount of time-based synchronization indicates that many tests rely on timing
rather than an authoritative observable completion signal.

## CI Runtime Evidence

The latest 70 workflow runs produced the following executed-job sample:

| Job | Executions | Failures | Median | P90 | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| Deterministic E2E | 61 | 10 | 12.1 min | 14.7 min | 15.6 min |
| Focused Runtime Provider E2E | 39 | 2 | 6.8 min | 7.2 min | 9.1 min |
| Web Surface E2E | 63 | 1 | 8.0 min | 8.4 min | 21.6 min |
| Aggregate E2E gate | 68 | 14 | 0.1 min | 0.1 min | 0.1 min |

The aggregate gate failed in 14 of 68 observed executions, or 20.6 percent. This is a
failed-run rate, not a measured flake rate. Some failures may be valid product
regressions. The current workflow does not preserve enough structured longitudinal
data to calculate same-SHA failure-then-success behavior accurately.

### Successful Deterministic Timing Concentration

One successful deterministic execution showed the following approximate aggregate
inter-test completion time:

- Project Browser Manifest: 176 seconds.
- External Channel: 120 seconds.
- Agent Execution Persistence: 63 seconds.
- Subagents: 37 seconds.
- Initial System Admin tests: 35 seconds.
- Discord provider fake tests: 31 seconds.
- Model Stream Watchdog: 26 seconds.

The first Project Browser Manifest test alone took approximately 171 seconds between
the previous and current test completion. Its explicit fixtures are normal Public and
Admin API clients, but its product path can cause implicit Runtime preparation. This
makes its deterministic classification misleading and has already been associated
with Runtime startup instability.

### Setup Dominates Specialized Lanes

In one successful Web Surface execution, the seven browser tests completed in roughly
one minute after the environment was ready, while the job took approximately eight
minutes.

In one successful focused Runtime Provider execution, the four assertions completed
in roughly 30 seconds after the environment was ready, while the job took approximately
6.8 minutes.

The dominant cost in both cases is image build, dependency download, and environment
startup rather than test assertions.

## Failure Concentration

Recent failed logs were concentrated in a limited set of boundaries.

### External Channel

Observed failures included:

- Duplicate canonical Session links where exactly one was expected.
- Provider control counts not settling to an exact expected value.
- Slack approval and progress controls failing to reach a count barrier.
- Discord title and takeover barriers timing out.
- Provider-native progress blocks appearing more than once.

These tests frequently use intermediate provider call counts or ordering as the E2E
oracle. Such assertions are fragile when the production boundary is asynchronous,
retriable, or at-least-once.

### Model Stream and Subagents

Observed failures included:

- Compaction provider failure timing.
- Semantic transcript preservation across compaction.
- Interrupt delivery for a stopped subagent.

These tests exercise legitimate concurrency behavior but rely on several time-based
state transitions in a shared worker environment.

### Project Browser Runtime Startup

Three Project Browser Manifest tests failed together in multiple runs because their
shared setup could not obtain a ready Runtime-backed state. This is a boundary and
classification issue rather than three independent feature failures.

### Web Build Infrastructure

The observed Web Surface failure was not a browser assertion. The Admin Web Docker
build failed because `pnpm install` timed out while downloading packages from the
registry. Pytest then reported setup errors for all seven tests.

This is an infrastructure/build failure represented as a product E2E failure.

## Test Value Assessment

### Meaningful Tests in the Wrong Layer

The 87 provider fake, proxy, readiness, and helper cases are valuable deterministic
component tests. They should run without building or starting the Azents product
stack.

Many CRUD, validation, permission, and error-code permutations are also meaningful,
but they primarily validate API or service contracts. Representative user journeys
may remain E2E, while broad status-code permutations should move to an API integration
layer.

Examples include:

- Health readiness and liveness permutations.
- User and user-email CRUD.
- Workspace CRUD.
- Invitation CRUD.
- Toolkit CRUD.
- Configuration validation and not-found cases.

### High-Value E2E Boundaries

The strongest E2E candidates are behaviors that require multiple real boundaries:

- Initial administrator bootstrap and final-admin invariants.
- Login through workspace creation.
- User message through worker, model stream, and persistence.
- Subagent creation and result delivery.
- File upload through model-visible attachment projection.
- Slack or Discord ingress through binding, Session execution, and provider response.
- Runtime Provider enrollment through Runner execution and persistence.
- Browser authentication, secure cookies, gateway routing, and reload behavior.
- Restart and recovery behavior that cannot be represented by an in-process test.

### Rewrite or Removal Candidates

Candidates requiring explicit review include:

- Permanently skipped tests for APIs that are not available.
- Duplicate health checks after a representative smoke check and lower-layer coverage
  exist.
- Tests whose only oracle is an exact transient provider call count.
- `live_external` tests that only check prerequisites and do not execute product
  behavior.
- Runtime Provider tests that are neither required nor scheduled.

Removal should occur only after confirming that the user risk is covered elsewhere.
Most current findings call for relocation or rewriting rather than immediate deletion.

## Large Journey Risk

Several E2E tests combine too many user risks and assertions into one function.
Examples found during the audit include:

- 482 lines and 53 assertions.
- 461 lines and 39 assertions.
- 421 lines and 51 assertions.
- 409 lines and 11 assertions.
- 374 lines and 20 assertions.

A single failure in one of these journeys is difficult to classify. The long sequence
also increases the number of synchronization points and retained intermediate states.

Large tests should be split by one user risk and one authoritative oracle while
reusing bounded setup helpers.

## Image Build Duplication

The Docker build matrix and E2E jobs build overlapping images independently. E2E can
build the following images inside pytest fixture setup:

- Azents server.
- Main Web.
- Admin Web.
- Runtime Runner.
- Docker Runtime Provider.

The fixture implementation already supports consuming prebuilt image names through
environment variables and includes optional local BuildKit cache inputs. The current
CI workflow does not connect its Docker build output or a shared cache to these E2E
hooks.

Consequences include:

- Repeated builds of the same commit.
- Package registry access during product E2E execution.
- Build failures reported as test failures.
- Specialized lanes spending most of their runtime before assertions begin.

## Strategy and Implementation Drift

The living E2E strategy and current workflow are not fully aligned.

Observed drift includes:

- The strategy describes focused Runtime Provider coverage including a file-transfer
  journey, but the current job hardcodes a different four-test set.
- The strategy describes live label, manual, and nightly workflows, but no live E2E
  workflow implementation was found.
- Testenv instructions describe two credential-free lanes, while the aggregate gate
  currently includes a third focused Runtime Provider lane.
- The required Runtime Provider PR path filter does not represent the complete product
  dependency surface.

Any implementation should update the living spec and operational instructions to
match the final CI topology.

## Recommended Target Test Portfolio

### Component Lane

Proposed name: `testenv-component`

Scope:

- Provider fake contract tests.
- Proxy tests.
- Readiness tests.
- Runtime Provider authentication helpers.
- Shared E2E support utilities.

Properties:

- No Azents image build.
- No full product stack.
- Safe process-level parallelism where local ports and state are isolated.
- Required on every relevant pull request.
- Target runtime below two minutes.

### API Integration Lane

Scope:

- CRUD and validation permutations.
- Permission and status-code matrices.
- Route, service, repository, and database interaction.

Properties:

- In-process application or a lightweight isolated server.
- Isolated database state.
- No browser, Runtime Provider, or product image build.
- Parallel execution after fixture isolation.

### Core E2E Lane

Scope:

- Approximately 15 to 25 representative cross-process user journeys.
- Always-required backend safety net.

Properties:

- Prebuilt immutable server image.
- Strict runtime and reliability budget.
- One user risk and one primary oracle per test.
- Target runtime below five minutes after image availability.

### Web Surface Lane

Scope:

- Three to five presentation behaviors that only a browser can prove.
- Authentication cookies and routing.
- One representative settings mutation.
- One real-time activity or attachment presentation journey.
- Reload persistence.

Properties:

- Prebuilt server, Main Web, and Admin Web images.
- No package installation or image build inside pytest.
- Screenshots and page source retained on failure.

### Runtime Provider Lanes

Proposed markers:

- `runtime_provider_smoke`
- `runtime_provider_extended`

Smoke properties:

- Four to six representative journeys.
- Required for all relevant backend, Runtime Control, Runner, Provider, protocol, and
  image changes.
- Marker selection rather than hardcoded node IDs.

Extended properties:

- All Runtime Provider journeys.
- Relevant pull-request label or nightly execution.
- Eligible for required status only after reliability goals are met.

### Extended and Live Lanes

Extended hermetic E2E should contain broad but slower deterministic regression
coverage. It can run nightly or on explicit request while retaining artifacts and
ownership.

Live verification should separate prerequisite readiness from product behavior. A
live lane should only claim product verification after executing an actual provider
journey.

## Reliability Mechanisms

### Per-Test Generation and Correlation

Provider fakes should issue a generation identifier when reset or initialized. Every
received operation and emitted event should be associated with that generation and a
test correlation identifier.

Queries should return evidence for the active generation only. Work from an earlier
generation that arrives late should be isolated rather than counted in the next test.

### Domain Outcome Over Transient Call Count

E2E should prefer an authoritative user-visible or persisted outcome, for example:

- One durable Session response for a correlation ID.
- One final binding projection.
- One terminal Runtime operation.
- One user-visible attachment after reload.

Exact retries and provider call counts should be tested at a lower deterministic layer
unless they are themselves a public contract.

### Observable Readiness

Fixed sleep and log-substring polling should be replaced where possible with:

- Readiness endpoints.
- Persisted operation status.
- Monotonic event sequence or cursor state.
- Background work drain or idle evidence.
- Explicit WebSocket terminal events.
- Fake-provider acknowledgement for a correlation ID.

### Clock Injection

Timeout, retry, scheduler, and backoff permutations should use an injected clock in
backend integration tests. E2E should retain only a representative production-timer
journey when the real asynchronous wiring is the subject of the test.

### Quarantine Without Green-by-Retry

Known flaky tests should not become green solely through automatic reruns. Temporary
quarantine should require:

- An owner.
- A linked issue.
- A removal deadline.
- Continued execution in a nonblocking lane.
- Preservation of both the first failure and any rerun result.

## Observability Required Before Large Refactoring

The current workflow should first retain structured evidence:

- JUnit XML.
- Slowest-test durations.
- Environment and image setup durations.
- Sanitized container logs.
- Browser screenshots and page source.
- Test node ID, commit SHA, run attempt, and result.
- First-run and rerun results stored separately.

Without these records, ordinary product regressions and same-SHA flakes remain mixed
in the aggregate failed-run rate.

## Proposed Migration Sequence

### Phase 1: Measurement and Inventory

1. Add JUnit, duration, log, and browser artifacts.
2. Record test ownership, layer, capability, and expected runtime.
3. Establish a baseline for same-SHA failure-then-success behavior.
4. Remove or resolve permanent skips.

### Phase 2: Separate Component Tests

1. Move the 87 support cases into a Docker-free component lane.
2. Preserve their existing assertions.
3. Confirm that deterministic product E2E no longer collects them.
4. Add safe process-level parallelism to the component lane.

### Phase 3: Decouple Build and Test

1. Build test images once per commit using immutable tags.
2. Reuse BuildKit GitHub Actions cache.
3. Pass prebuilt image names through the existing E2E environment hooks.
4. Prevent pytest fixture setup from installing packages or building product images in
   CI.
5. Report image build failures separately from E2E failures.

### Phase 4: Repair Runtime Provider Selection

1. Rename the historical Tool Search lane.
2. Introduce smoke and extended markers.
3. Select by marker instead of node ID.
4. Correct the pull-request path filter.
5. Ensure every Runtime Provider test has an intentional execution policy.

### Phase 5: Stabilize External Channel and Runtime Boundaries

1. Add per-test fake generations and correlation IDs.
2. Add background work drain or idle evidence.
3. Replace exact transient counts with domain convergence assertions.
4. Split large journeys by user risk.
5. Reclassify implicit Runtime-dependent tests.

### Phase 6: Reduce the Required Portfolio

1. Keep representative cross-process journeys in core E2E.
2. Move CRUD and validation permutations to API integration.
3. Move broad hermetic regression to the extended lane.
4. Establish and enforce runtime and reliability budgets.
5. Update the living strategy spec and operational instructions.

## Proposed Success Criteria

A future approved implementation should consider targets such as:

- Required E2E wall-clock time below five to seven minutes.
- Known-flake failure rate below one percent for the required core suite.
- No permanent skipped required tests.
- Every test assigned to an explicit layer and capability.
- No hardcoded Runtime Provider node-ID selection.
- No product image build or package installation inside pytest in CI.
- Same-SHA rerun evidence retained without hiding the initial failure.
- Clear separation between required core, extended hermetic, and live verification.

## Summary

The primary issue is not that the suite has too many tests in absolute terms. The
suite mixes component, API integration, cross-process E2E, browser, Runtime Provider,
and prerequisite checks under one E2E project and then divides them with historical
markers and hardcoded selections.

The fastest safe path is:

1. Measure failures and durations reliably.
2. Remove non-E2E tests from the full-stack lane.
3. Build images once and reuse them.
4. Isolate asynchronous fake state by generation and correlation.
5. Retain a small required portfolio of representative user journeys.

Additional sharding or automatic retries before these changes would increase build
duplication and state contention without solving the underlying reliability problem.

## Follow-up Implementation

The first observability phase was implemented after this research:

- Every executed required E2E lane produces JUnit XML.
- Pytest output and the 30 slowest test phases are retained.
- Docker process, resource, and storage diagnostics are uploaded after success or
  failure.
- Failed browser calls capture a screenshot and page HTML when WebDriver is available.
- A bounded JUnit-derived Markdown summary is generated without publishing assertion
  messages or tracebacks.
- Same-repository pull requests receive one sticky comment that is updated for each CI
  run and links to the complete artifacts.
- Test jobs remain read-only; only the dedicated comment job receives pull-request
  comment write permission.
- Fork pull requests remain read-only and skip comment publication.

### Unit Test Separation

The second implementation phase moves 24 server-free support tests from the E2E
collection into `src/unit_tests/` and runs them in a required Docker-free Testenv unit
job. The moved tests directly verify helper behavior with function calls, mocks,
monkeypatches, temporary files, or injected clocks.

Provider fake and proxy tests that start HTTP/WebSocket servers remain under
`src/tests/` as E2E verification. The same boundary retains the real RustFS container
tests and the Discord Azents-server image contract. The stable aggregate gate includes
the unit result, while the sticky E2E observability comment continues to report only
the three E2E lanes.

### Sticky Comment Action Selection

The implementation evaluated three maintained approaches:

- `marocchino/sticky-pull-request-comment` provides a dedicated header-keyed sticky
  comment action and can publish a generated Markdown file.
- `peter-evans/find-comment` plus `peter-evans/create-or-update-comment` provides a
  composable two-action lookup and update flow.
- `actions/github-script` can implement the lookup and update directly through the
  GitHub API but requires repository-owned JavaScript in the workflow.

The implementation uses `marocchino/sticky-pull-request-comment` because the required
behavior is exactly one header-keyed comment updated from one Markdown file. The
action is pinned to a full commit SHA. The write-authorized job does not check out the
repository or execute test binaries; it only downloads bounded summary artifacts,
assembles static Markdown, and publishes the comment for same-repository pull requests.
