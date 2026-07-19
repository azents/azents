---
title: "Subscription Provider Usage Implementation Plan"
created: 2026-07-19
updated: 2026-07-19
tags: [plan, backend, frontend, api, llm, oauth, billing, security, testing, testenv]
---

# Subscription Provider Usage Implementation Plan

## Feature Summary

Implement the live subscription-usage design in
[`subscription-provider-usage.md`](./subscription-provider-usage.md) and ADR-0168.
Workspace LLM Settings will read provider-reported ChatGPT OAuth and xAI OAuth quota snapshots per
integration, normalize operational usage, restrict financial details to integration managers, and
contain every failure inside the affected integration card.

Subscription usage remains separate from AgentRun token/context usage, API-key billing, model catalog
synchronization, execution entitlement, and integration enabled state. The implementation stores no
usage history and performs no automatic polling.

## Stack Prefix

`Subscription provider usage`

## Delivery and Review Protocol

The stack is delivered sequentially. Parallel implementation is not used unless a later phase reveals
a file-independent prerequisite that cannot affect another phase's contract.

For every implementation phase:

1. The root agent writes and commits a phase-specific plan before implementation begins.
2. One implementation subagent receives that plan and implements only its stated scope.
3. A different verification subagent reviews the completed diff, runs the planned checks, and reports
   design, security, isolation, and test gaps.
4. The root agent independently checks the verifier's findings, applies any required review fixes, and
   performs the final phase validation before creating the PR.
5. Review feedback fixes remain owned by the root agent.

An implementation subagent must not be treated as the independent verifier of its own work.

## PR Stack and Boundaries

| Order | PR | Base | Scope |
| --- | --- | --- | --- |
| 1/8 | Design | `main` | ADR-0168 and approved feature design |
| 2/8 | Implementation plan | PR 1 branch | This multi-phase plan and delivery protocol |
| 3/8 | Phase 1 — Backend contract and ChatGPT | PR 2 branch | Normalized contract, child endpoint, permission projection, ChatGPT adapter, forced refresh, OpenAPI and generated clients |
| 4/8 | Phase 2 — xAI adapter parity | PR 3 branch | xAI settings/billing/auto-top-up adapter, trusted redirect, refresh-window drift correction |
| 5/8 | Phase 3 — Frontend usage cards and isolation | PR 4 branch | Card-local query containers, ADT states, error boundary, Owner detail, stories, translations, responsive behavior |
| 6/8 | Validation | PR 5 branch | Deterministic provider fixture, API/E2E failure injection, evidence report, strict implementation/spec comparison |
| 7/8 | Spec promotion | PR 6 branch | `/spec-review`, living spec updates, design `implemented` date |
| 8/8 | Cleanup | PR 7 branch | Remove this plan and phase-specific plans after specs are current |

Every branch is stacked on the immediately preceding branch. All eight PRs are created before CI
monitoring begins.

## Cross-Phase Isolation Invariants

These invariants are release blockers and must be verified in every phase that touches them.

- One integration usage read uses one child endpoint request and one card-local frontend query.
- Integration list, provider capability, model catalog, and management controls never await usage.
- One integration failure never cancels, invalidates, hides, or changes another integration's usage.
- Provider HTTP errors, timeouts, rate limits, malformed payloads, and private-contract drift are
  normalized inside the owning adapter without exposing raw payloads or exception serialization.
- Unexpected server failures remain non-success responses, but the frontend contains them inside the
  affected card rather than promoting them to the LLM Settings page error state.
- Initial failure renders card-local unavailable state. Refresh failure preserves the last successful
  client snapshot and marks it stale.
- Usage reads never disable integrations or update execution entitlement. Only an existing shared OAuth
  refresh operation may mark refresh required when the credential refresh itself is rejected.
- xAI usage permission or billing failures never mutate xAI inference entitlement state.
- Existing card enable, edit, reconnect, and delete actions remain usable when usage is unavailable.
- Raw credentials, account identifiers, provider bodies, billing values, redirect query values, and
  request headers never enter logs or error text.

## Phase 1 — Backend Contract and ChatGPT Adapter

### Phase goal

Establish the normalized public contract and complete ChatGPT OAuth usage reads without adding UI.
The generated clients produced by this phase become the typed dependency for later frontend work.

### Data and API changes

- Add a closed normalized subscription-usage outcome union with `available`, `external`, and
  `unavailable` variants.
- Add normalized quota windows, freshness metadata, safe action hints, optional plan metadata, and a
  separate management-only financial detail union.
- Add the integration child endpoint:
  `GET /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/{integration_id}/subscription-usage`.
- Require `LLM_INTEGRATIONS_READ` for the endpoint and project financial fields only when the member
  also has `LLM_INTEGRATIONS_WRITE`.
- Return 404 for missing or cross-workspace integrations, 409 for unsupported providers, and a typed
  disabled outcome for eligible disabled integrations without provider calls.
- Keep list/detail integration responses free of usage fields and provider calls.

### Runtime and provider changes

- Introduce a dedicated read-through subscription-usage service with closed provider dispatch.
- Isolate ChatGPT wire fields, endpoint selection, authentication headers, response parsing, and
  failure classification in the ChatGPT adapter.
- Extract a public forced-refresh operation from the existing ChatGPT OAuth runtime lifecycle without
  duplicating refresh persistence or race recovery.
- Ensure normal freshness before the usage request, then perform at most one forced-refresh retry after
  a provider 401.
- Normalize primary, secondary, and additional limits; plan metadata; credits; and spend-control data.
- Parse reset-credit compatibility fields without exposing reset-credit consumption controls.
- Clamp only presentation percentages while preserving an explicit malformed-response outcome for
  structurally invalid provider data.

### Generated artifacts

- Dump the public OpenAPI specification from backend models and routes.
- Regenerate Python and TypeScript public clients from the dumped OpenAPI document.
- Never edit generated client files manually.

### Phase tests

- Adapter contract tests use `httpx.MockTransport` or an equivalent injected transport and assert exact
  paths, safe required headers, response normalization, 401 single-retry behavior, 403/429/5xx/timeout
  classification, malformed payload handling, and secret-safe logs.
- Runtime tests prove forced refresh reuses the same persistence and concurrent-refresh recovery path.
- Service tests cover unsupported provider, disabled integration, missing/cross-workspace integration,
  and financial projection.
- Route tests cover read/write permission projection and public response discrimination.
- OpenAPI/client generation and backend Ruff, Pyright, and targeted Pytest checks pass.

### Phase-specific plan

Before implementation, add
`docs/azents/design/subscription-provider-usage-phase-1-plan.md` with concrete symbols, test cases,
commands, and explicit exclusions. The implementation subagent receives that document as its sole
phase scope.

## Phase 2 — xAI Adapter Parity

### Phase goal

Add xAI subscription billing parity behind the Phase 1 normalized contract without changing the public
shape or frontend.

### Provider changes

- Implement xAI CLI proxy identity, compatibility version, remote settings, billing, and optional
  auto-top-up reads in a dedicated adapter.
- Read remote settings first. A valid provider-directed usage URL returns `external` and short-circuits
  billing.
- Treat remote-settings failure as non-blocking when billing can still be read.
- Fetch auto top-up only when normalized billing indicates a positive prepaid balance and expose those
  details only in the management projection.
- Validate external URLs as HTTPS, without user info, and on exact or subdomains of `x.ai` or
  `grok.com`. Invalid URLs become an invalid-provider-response outcome and are never serialized.
- Keep usage 403, billing denial, malformed response, timeout, rate limit, and provider errors separate
  from inference entitlement and integration status.
- Correct the existing xAI OAuth refresh-window drift so runtime code matches the five-minute living
  spec, then reuse that shared lifecycle for usage freshness and one-retry-on-401 behavior.

### Phase tests

- Contract tests cover exact settings/billing/auto-top-up paths and required safe headers.
- Tests cover redirect short-circuit, trusted/untrusted hosts, remote-settings fallback, optional
  auto-top-up fetch, missing account metadata, all controlled provider failures, and financial
  projection.
- Runtime tests lock the corrected five-minute refresh threshold.
- Regression tests prove every xAI usage failure leaves inference entitlement and enabled state
  unchanged.
- Backend Ruff, Pyright, and targeted Pytest checks pass.

### Phase-specific plan

Before implementation, add
`docs/azents/design/subscription-provider-usage-phase-2-plan.md` with concrete adapter contracts,
trusted URL cases, refresh-drift correction steps, tests, commands, and exclusions.

## Phase 3 — Frontend Usage Cards and Isolation

### Phase goal

Render the normalized data in existing LLM Settings cards while preserving page and card management
behavior under every usage failure.

### Frontend changes

- Add a generated-client-backed tRPC subscription usage query for one integration.
- Give every eligible integration card its own container/query instance. Do not aggregate usage
  requests in the page container or page loading ADT.
- Enable queries only for enabled `chatgpt_oauth` and `xai_oauth` integrations.
- Configure a 60-second stale time, focus refetch only when stale, explicit refresh, no polling, and
  previous-success retention during refresh.
- Convert query state and normalized response into a closed card-local ADT covering idle, loading,
  available, external, unavailable, and stale-error states.
- Add a narrow usage-subtree error boundary. Its fallback replaces only the usage section and leaves
  card management controls mounted.
- Render at most two primary quota windows in the compact summary and place additional/provider-specific
  operational and Owner-only financial details behind disclosure.
- Provide accessible progress semantics, reset/freshness copy, warning/exhausted states, trusted external
  link attributes, mobile stacking, and no horizontal overflow.
- Add localized copy in every supported locale with natural Korean wording where applicable.

### Phase tests and stories

- Add pure component stories for loading, normal ChatGPT, exhausted, xAI financial detail, read-only,
  external, unavailable, stale refresh, disabled, and narrow layout states.
- Add TypeScript state-conversion tests for query eligibility, controlled outcomes, transport error,
  stale retention, and independent card state.
- Add a component-level error-boundary test that throws from the usage subtree and asserts header and
  management actions remain rendered.
- Run frontend unit tests, format, lint, typecheck, build, and Storybook build.

### Phase-specific plan

Before implementation, add
`docs/azents/design/subscription-provider-usage-phase-3-plan.md` with component boundaries, ADT
mapping, query options, translation keys, stories, tests, commands, and explicit no-page-coupling rules.

## Validation Phase

### Phase goal

Validate the completed stack independently through deterministic provider behavior and browser-visible
product behavior before promoting living specs.

### Fixture and prerequisite support

Add one credential-free deterministic subscription-usage provider fixture that can be configured per
integration/test case to return:

- ChatGPT normal, exhausted, unauthorized-then-refresh, timeout, 429, 5xx, and malformed responses;
- xAI normal billing, trusted redirect, invalid redirect, billing denial, settings failure with billing
  success, timeout, and malformed responses;
- success followed by refresh failure for stale snapshot coverage;
- safe request journals that record only paths and required-header presence, never values or tokens.

E2E setup creates OAuth integrations through the product API using deterministic non-live credentials.
It must not write directly to the product database. Provider fixture base URL/configuration overrides
must be explicit test/development dependencies and must not alter production endpoint defaults.

Live provider credentials are optional and excluded from required CI. If live verification is
explicitly requested, it uses prerequisite snapshots and fails when requested credentials are missing;
otherwise absence is reported without weakening required deterministic checks.

### E2E primary validation matrix

| Scenario | Required assertion |
| --- | --- |
| ChatGPT Owner normal | Two compact windows, reset/freshness, financial detail, manual refresh |
| ChatGPT Member normal | Operational windows visible and every financial field absent from API/UI |
| ChatGPT exhausted | 100% danger presentation without remaining-request claim |
| ChatGPT initial timeout/5xx | Only affected usage section is unavailable; card controls and page remain usable |
| ChatGPT stale refresh | Previous values remain visible with stale warning and retry |
| xAI Owner normal | Normalized period plus collapsed prepaid/PAYG/auto-top-up detail |
| xAI trusted external | Trusted external action shown and billing detail omitted |
| xAI invalid external | No link rendered; card-local invalid-response state |
| xAI billing 403 | Usage unavailable while inference status, enabled state, and management controls remain unchanged |
| Two eligible integrations, one broken | Healthy card remains available and refreshable; broken card does not cancel or hide it |
| Unexpected endpoint 500 | Only affected card fallback renders; integration list page stays ready |
| Usage component render throw | Card header/actions remain mounted through narrow error boundary |
| Disabled integration | No provider request and explicit disabled usage state |
| Narrow viewport | No horizontal overflow; progress labels and actions remain reachable |

### Validation evidence

Create `docs/azents/design/subscription-provider-usage-validation-2026-07-19.md` containing:

- commands and environment details;
- deterministic fixture readiness and safe-journal evidence;
- backend, generated-client, frontend, Storybook, and E2E results;
- failures discovered and fixes applied;
- a strict table comparing implementation with ADR, design, and current living specs;
- optional live-test results separately from required CI.

The validation subagent must be independent from the phase implementation subagents. The root agent
rechecks all release-blocking findings and the final command results.

## Spec Impact Candidates

The spec-promotion phase runs `/spec-review` and is expected to update:

- `docs/azents/spec/flow/chatgpt-oauth.md`;
- `docs/azents/spec/flow/xai-oauth.md`;
- an existing or new workspace/integration domain spec if permission projection and usage ownership need
  a canonical domain home.

AgentRun token/context usage specs remain behaviorally unchanged. If cross-referenced, they explicitly
state that provider subscription quota is a separate integration-scoped contract.

The xAI OAuth spec remains authoritative at a five-minute runtime refresh window; Phase 2 corrects the
current one-hour implementation drift.

## Blockers and External Actions

No product-decision blocker remains.

Known implementation risks:

- ChatGPT and xAI usage endpoints are private implementation-backed contracts and can change without
  notice. Adapter isolation, fixture fingerprints, safe malformed-response telemetry, and card-local
  degradation are mandatory rather than optional hardening.
- Exact xAI compatibility headers and remote-settings fields must be verified against the pinned
  source evidence during Phase 2. A missing live credential does not block deterministic delivery.
- Local browser E2E may require the worktree devserver/browser fixture. If local infrastructure is
  unavailable, record the exact blocker and rely on required CI only after deterministic non-browser
  checks have passed; do not silently skip the web-surface matrix.

## Rollout and Cleanup

- No database migration, history retention, scheduler, background polling, global usage dashboard,
  alerting, or chat warning is introduced.
- Unsupported and API-key providers render no synthetic subscription usage.
- Provider endpoint defaults remain production constants; deterministic overrides are test/development
  dependencies only.
- The feature ships additively through the child endpoint and card subtree.
- After validation and living spec promotion, set the design `implemented` date and stop modifying it.
- The final cleanup PR deletes this implementation plan and all three phase-specific plans. The
  validation report, implemented design, ADR, living specs, and code remain as the durable record.
