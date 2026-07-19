---
title: "Session Subscription Usage Design"
created: 2026-07-19
updated: 2026-07-19
tags: [frontend, llm, oauth, billing, security, ux, testing]
---

# Session Subscription Usage Design

## Summary

Azents will project the selected composer model's OAuth subscription usage into the Agent session. A compact indicator beside the model selector provides immediate discoverability, while the existing desktop model popover and mobile model bottom sheet provide operational details and refresh actions.

Workspace LLM Settings remains the canonical integration-management and financial-detail surface. The session projection is read-only, operational, and non-blocking.

ADR-0170 records the durable placement, ownership, and visibility decisions.

## Problem

Subscription usage is currently available only inside Workspace LLM Settings integration cards. The surface is correct for management, but users working in a session must leave the chat, find the provider integration, inspect usage, and then navigate back before deciding whether to continue with the selected model.

The session already supports per-input model selection. Each selectable model option stores the provider and `llm_provider_integration_id`, so the composer knows which integration will serve the next request. The current UI does not use that provenance to project provider quota near the model decision.

## Goals

- Make subscription usage discoverable from the active session without navigation.
- Keep usage aligned with the model target selected for the next input.
- Show operational limits, reset metadata, freshness, and provider-directed external usage actions.
- Preserve model selection and message submission when usage is loading or unavailable.
- Keep financial values and integration management in Workspace LLM Settings.
- Reuse the existing subscription-usage endpoint, normalization, permissions, and browser query cache.
- Preserve the semantic distinction from run-scoped token and context-window usage.

## Non-goals

- Moving or removing the LLM Settings usage card.
- Showing credit balance, spend control, pay-as-you-go, or auto top-up in a session.
- Polling usage in the background.
- Persisting session-specific usage snapshots or history.
- Estimating remaining messages or changing model selection automatically.
- Blocking or warning before every message based on a local threshold.
- Showing API-key billing usage.

## Current Session Structure

The concrete Agent session renders:

1. `AgentSessionHeader`, including the run-scoped `TokenUsageIndicator`;
2. chat timeline and live state;
3. `ChatInput`, including the model/reasoning profile selector;
4. the docked or mobile runtime workspace panel.

`ChatInput` receives `selectable_model_options`. Each option contains a label and an `AgentModelSelection` snapshot with provider and integration ID. The selected `RequestedInferenceProfile.model_target_label` resolves directly to one option.

## User Experience

### Compact affordance

For a selected `chatgpt_oauth` or `xai_oauth` option, the composer control row shows a compact subscription indicator beside the model selector.

- Available: display the primary normalized limit's rounded used percentage with a small circular gauge.
- Loading: display a quiet loading indicator without changing control width substantially.
- Stale: retain the last percentage and add a stale marker.
- Unavailable: display a neutral warning icon with an accessible unavailable label.
- External: display an external-link indicator rather than a synthetic percentage.
- Unsupported/API-key provider: render no subscription indicator.

Desktop users can activate the indicator to open the same profile picker that owns the detail. The model selector and usage indicator behave as one related control group but retain separate accessible names.

### Desktop model picker

The profile picker keeps model and reasoning-effort navigation as its primary task. A selected-integration usage summary appears below the model/effort controls, separated by a subtle divider.

The summary includes at most two primary limits in its initial view, reset metadata, freshness, refresh action, and stale/unavailable handling. Additional normalized limits may remain collapsed or omitted from the compact session projection because the complete integration view remains available in LLM Settings.

A trusted `external` outcome shows the existing safe xAI action. It opens in a new tab with `noopener noreferrer`.

### Mobile model picker

The existing bottom sheet shows the selected integration usage summary after model options and before the completion action. The closed mobile composer does not add a persistent percentage beside the model trigger when horizontal space is constrained; warning severity can be reflected in the trigger through a small status dot.

The detail remains reachable in one tap through the model control.

### Visual severity

The display uses normalized percentage only as visual guidance:

| Used percentage | Presentation |
|---|---|
| below 70% | teal/neutral |
| 70–89% | yellow warning |
| 90–100% | red critical |

Unavailable and external states use status icons instead of percentage-derived color.

### Copy and scope

All session labels explicitly use `subscription usage` terminology. They do not use `context`, `tokens`, `remaining messages`, or `session usage` without qualification.

A settings link may be included as a secondary action for users who need the full integration card. The session never renders financial fields.

## State and Data Flow

1. `ChatInput` resolves the selected option from `inferenceProfile.model_target_label`.
2. The selected option supplies provider and integration ID to a subscription-usage container.
3. The container enables the existing tRPC usage query only for supported OAuth providers.
4. TanStack Query shares data by workspace and integration with other mounted usage surfaces.
5. A pure session summary component receives the projected discriminated state and emits refresh/open actions.
6. Changing the model target changes the integration query key and displayed state.

The existing endpoint may return financial fields for integration managers. The session component intentionally has no financial-detail rendering path.

## Failure Isolation

- Usage loading does not disable model selection or sending.
- Initial failure affects only the session usage affordance.
- Failed refresh retains the last successful snapshot as stale.
- A presentation failure is contained around the usage projection rather than the whole composer.
- Provider bodies, raw errors, account identifiers, emails, and credentials never render.

## Accessibility

- The compact indicator has an explicit accessible label naming provider subscription usage and current state.
- Percentage is not communicated by color alone.
- Tooltips supplement rather than replace accessible names.
- Refresh and external actions are keyboard reachable.
- The model picker preserves focus and dismissal behavior.
- Loading announcements remain polite and do not repeat during unrelated composer input.

## Responsive Behavior

- Desktop: model trigger and compact indicator remain on one row; detailed usage appears in the popover.
- Mobile: the trigger remains compact; details appear in the bottom sheet.
- Long model labels truncate before the usage affordance loses its minimum hit target.
- Localized labels and reset strings wrap inside the detail surface without increasing composer width.

## Test Strategy

### Deterministic UI validation matrix

| Scenario | Expected result |
|---|---|
| ChatGPT OAuth available | selected model shows compact percentage and operational detail |
| xAI OAuth available | selected model shows normalized limit detail |
| xAI external | trusted external action appears and no fake percentage is shown |
| unavailable | model picker and sending remain usable; fixed retry state appears |
| failed refresh after success | last successful percentage remains with stale state |
| API-key model | no subscription indicator or usage request |
| model changes between integrations | indicator and detail switch to the newly selected integration |
| read-only projection | operational detail is visible and financial detail is absent |
| desktop | compact indicator and popover detail are represented by desktop stories |
| mobile | compact indicator and bottom-sheet detail are represented by mobile stories |

### Unit and component coverage

- Pure projection tests cover selected-option resolution, provider eligibility, model switching, severity, stale snapshots, and non-percent states.
- Storybook stories cover available, warning, critical, loading, stale, unavailable, external, unsupported, desktop, and mobile states.
- Storybook interaction assertions verify refresh, trusted external navigation, accessible labels, and the absence of financial detail.
- The production and Storybook builds verify integration with the real composer components and responsive render paths.

### E2E scope

No new Web Surface E2E is required for this frontend-only projection. The existing subscription-usage feature stack already validates the public endpoint, provider adapters, permission projection, stale behavior, and deterministic proxy scenarios. This change reuses that shipped query contract without modifying backend behavior, persistence, authentication, or provider requests. Duplicating the same provider scenarios through a new browser fixture would add maintenance scope without increasing contract coverage.

### CI policy

The implementation must pass TypeScript formatting, cache-independent lint, typecheck, unit tests, the production web build, and the Storybook build. Optional live provider smoke tests remain excluded from required CI.

### Evidence

The validation phase records commands, CI run links, deterministic scenario coverage, implementation/spec comparison, and any corrected defects in a dated design validation report.

## Rollout and Cleanup

The feature has no schema migration, API change, or server rollout dependency. The web deployment activates the projection for existing eligible selectable model options.

After validation and spec promotion, remove the temporary implementation plan. Keep this design as implementation rationale and ADR-0170 as the durable decision record.
