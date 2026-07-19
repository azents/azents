---
title: "Session Subscription Usage Implementation Plan"
created: 2026-07-19
updated: 2026-07-19
tags: [frontend, llm, oauth, ux, testing, process]
---

# Session Subscription Usage Implementation Plan

## Feature Summary

Project the OAuth subscription usage associated with the currently selected composer model into the Agent session. Add a compact, provider-neutral status beside the desktop model selector and operational details inside the existing desktop model popover and mobile bottom sheet.

Design: [`session-subscription-usage.md`](session-subscription-usage.md)

Decision: [`ADR-0170`](../adr/0170-project-subscription-usage-from-selected-model.md)

## Boundaries

### Included

- Resolve the selected composer option to provider and integration ID.
- Reuse the existing subscription-usage endpoint and query cache.
- Add pure compact and detailed session usage components.
- Support available, warning, critical, loading, stale, unavailable, external, and unsupported states.
- Preserve manual refresh and trusted xAI external navigation.
- Cover desktop and mobile model-picker presentation.
- Add deterministic component and web-surface validation.
- Promote the behavior into current ChatGPT OAuth and xAI OAuth specs.

### Excluded

- Backend or OpenAPI changes.
- Financial values in the session.
- API-key billing.
- Usage persistence, polling, alerts, enforcement, or automatic model changes.
- Changes to the session-header context-usage indicator.
- Changes to provider adapters or OAuth refresh behavior.

## PR Stack

1. **Design** — ADR-0170 and approved design.
2. **Implementation plan** — this phased plan and validation matrix.
3. **Session UI** — selected-integration query projection, compact affordance, picker details, localization, stories, and unit/component tests.
4. **Validation** — deterministic web E2E and a dated validation report; fix defects found during validation in this phase.
5. **Spec promotion** — mark the design implemented and update ChatGPT OAuth and xAI OAuth living specs.
6. **Cleanup** — remove this temporary implementation plan.

## Dependencies

- PR 2 depends on the approved design and ADR in PR 1.
- PR 3 depends on the existing subscription-usage public endpoint and generated client already shipped by ADR-0169.
- PR 4 depends on deterministic usage proxy scenarios and an Agent whose selectable model points at an API-created OAuth integration.
- PR 5 depends on passing implementation and validation evidence.
- PR 6 depends on current specs becoming authoritative.

## Phase 1: Session UI

### Data flow

- Extend the reusable subscription-usage state/query layer rather than making raw API calls from `ChatInput`.
- Resolve the selected `selectable_model_options` entry from `model_target_label`.
- Key the query by workspace handle and `llm_provider_integration_id`.
- Enable the query only for `chatgpt_oauth` and `xai_oauth`.
- Reuse the 60-second stale time, focus revalidation, no automatic retry, manual refresh, and last-successful stale projection.

### UI structure

- Keep `ChatInput` as the owner of model-selection interaction state.
- Render a compact usage trigger beside the desktop profile trigger.
- Add selected-integration operational detail below the model and effort controls in the desktop popover.
- Add the same detail below the model options in the mobile bottom sheet.
- Use a component-local error boundary so usage presentation cannot break the composer.
- Do not provide any financial-detail prop or render path in session components.

### Tests

- Pure selected-option and severity projection tests.
- Component stories for all meaningful discriminated states.
- Interaction coverage for refresh, external link safety, and model switching.
- Localization updates for all supported locales.

## Phase 2: Validation

### Deterministic prerequisites

Reuse the subscription usage proxy and backend overrides already used by the existing E2E suite. Create integrations and Agent model selections through public APIs. Do not add test-only product routes or live credentials.

### E2E primary validation matrix

| ID | Scenario | Expected result |
|---|---|---|
| `TC-SESSION-USAGE-001` | selected ChatGPT OAuth model, available usage | compact percentage and detail are visible |
| `TC-SESSION-USAGE-002` | selected xAI OAuth model, available usage | normalized limit and reset metadata are visible |
| `TC-SESSION-USAGE-003` | switch from API-key model to OAuth model | usage request and UI appear only after selection |
| `TC-SESSION-USAGE-004` | switch between two OAuth integrations | displayed usage follows the selected target |
| `TC-SESSION-USAGE-005` | xAI external outcome | trusted external action appears without synthetic usage |
| `TC-SESSION-USAGE-006` | initial unavailable outcome | model selection and send controls remain usable |
| `TC-SESSION-USAGE-007` | successful read followed by refresh failure | last percentage remains and is marked stale |
| `TC-SESSION-USAGE-008` | read-only workspace member | operational usage is visible and financial fields are absent |
| `TC-SESSION-USAGE-009` | mobile viewport | detail is reachable through the model bottom sheet |
| `TC-SESSION-USAGE-010` | keyboard interaction | compact trigger, refresh, and model options are keyboard reachable |

### Evidence

Record:

- commit and environment;
- commands and CI runs;
- deterministic scenario outcomes;
- desktop/mobile screenshots when useful;
- implementation-to-design and implementation-to-spec comparison;
- failures found and fixes applied.

## Phase 3: Spec Promotion

Update the ChatGPT OAuth and xAI OAuth flow specs to state:

- LLM Settings remains the canonical management surface;
- sessions project operational usage from the selected composer model integration;
- the projection never renders financial details;
- failures are composer-local and non-blocking;
- the query retains the existing freshness and refresh policy.

Set `implemented: 2026-07-19` on the design after validation succeeds. Regenerate documentation indexes through pre-commit.

## Phase 4: Cleanup

Delete this implementation plan after specs and the implemented design become authoritative. Do not mix behavior changes into cleanup.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Subscription percentage confused with context usage | Keep it beside the model selector and label it explicitly as subscription usage |
| Model switch shows previous integration briefly | Use integration-specific query keys and loading projection on key change |
| Financial values leak into session | Define session-specific props without financial fields and assert absence in tests |
| Usage fetch affects sending | Keep query and error boundary independent from composer disable/send state |
| Mobile control crowding | Keep persistent detail inside the existing bottom sheet and use only a compact status marker when closed |
| Duplicate upstream calls | Share TanStack Query keys and retain the 60-second stale window |

## Blockers and External Actions

None. Existing endpoint, generated clients, permissions, proxy fixtures, and OAuth integration setup are sufficient.

## Rollout

No migration or backend rollout ordering is required. The frontend activates for existing eligible Agent model options after deployment.
