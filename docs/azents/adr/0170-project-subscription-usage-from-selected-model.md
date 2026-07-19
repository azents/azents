---
title: "ADR-0170: Project Subscription Usage from the Selected Composer Model"
created: 2026-07-19
tags: [architecture, frontend, llm, oauth, billing, security, ux]
---

# ADR-0170: Project Subscription Usage from the Selected Composer Model

## Status

Accepted for implementation planning.

## Context

ADR-0169 established integration-scoped live subscription usage and made each Workspace LLM Settings integration card the canonical management surface. That placement keeps credentials, enabled state, aliases, financial details, and provider usage together, but it requires users to leave an active Agent session to inspect the quota that can affect their next request.

A session can expose several selectable model targets backed by different provider integrations. The composer already identifies the model target for the next input and each selectable option carries its `llm_provider_integration_id` and provider snapshot. The session header separately displays run-scoped token and context-window usage for the active or latest run.

Subscription usage and run context usage must remain distinct:

- context usage belongs to one applied run profile and explains local compaction pressure;
- subscription usage belongs to the provider integration selected for the next composer input and can be shared across sessions and external clients.

The session needs a discoverable, low-noise usage affordance without introducing a second source of financial management or implying that provider quota is session-owned.

## Decision

### ADR-0170-D1. Project usage from the currently selected composer model

The session usage projection resolves the currently selected composer model target to its stored selectable model option and reads subscription usage by that option's `llm_provider_integration_id`.

Changing the composer model target changes the projected integration. The projection describes the next input selection, not the previous run or the session's historical model usage.

### ADR-0170-D2. Place the compact affordance beside the composer model selector

Eligible OAuth selections show a compact subscription-usage affordance immediately beside the composer model selector. This location keeps the quota close to the control that changes the affected provider integration.

The compact affordance uses provider-neutral usage language and exposes a tooltip or accessible label that identifies subscription usage. It must not reuse the session header context-usage indicator or present the two percentages as one measure.

Desktop renders a compact percentage or status indicator. Mobile keeps the closed composer compact and places the detailed state inside the existing model-selection bottom sheet.

### ADR-0170-D3. Put operational details inside the model picker

The model picker shows the selected integration's operational usage details:

- plan label when available;
- normalized limit labels and used percentages;
- reset time or remaining reset duration;
- freshness and stale state;
- manual refresh;
- trusted xAI external usage action;
- fixed unavailable state and retry action.

The picker remains usable while usage is loading or unavailable. Usage failure never blocks model selection or message submission.

### ADR-0170-D4. Keep financial details in LLM Settings

The session projection never renders credit balances, spend-control values, pay-as-you-go values, or auto top-up configuration, even when the endpoint returns those fields to a caller with integration write permission.

Workspace LLM Settings remains the canonical management and financial-detail surface. The session projection is an operational decision aid only.

### ADR-0170-D5. Reuse the integration endpoint and client freshness policy

The session projection reuses the existing integration child endpoint and provider adapters. It adds no API schema, backend persistence, polling, entitlement mutation, or provider request path.

Queries are enabled only for supported OAuth providers, remain keyed by workspace and integration, use the existing 60-second freshness window, revalidate on focus, and support manual refresh. Multiple UI surfaces may share TanStack Query data for the same integration.

### ADR-0170-D6. Use severity only as presentation guidance

The compact indicator uses normalized used percentage to provide calm visual severity:

- below 70 percent: neutral or positive;
- 70 through 89 percent: warning;
- 90 percent or above: critical;
- stale or unavailable: explicit non-percent state.

These thresholds do not change execution, select a different model, estimate remaining requests, or create alerts.

## Rejected Alternatives

### Put subscription usage in the session header

Rejected because the header indicator already represents run-scoped context usage. The header can refer to the active or latest run while the composer can select a different model for the next request, making two adjacent percentages semantically ambiguous.

### Combine context and subscription usage into one popover

Rejected because the values have different ownership, freshness, denominators, and remediation. Combining them would imply a relationship that the provider does not guarantee.

### Show a persistent session banner

Rejected for normal operation because it consumes the primary chat workspace and overstates a provider-account metric. A compact composer affordance is sufficient; provider execution failures continue to use their existing run-level presentation.

### Repeat financial details in the session

Rejected because financial configuration is management data rather than a per-message decision aid and would increase accidental exposure in a frequently shared operational surface.

## Consequences

### Positive

- Users can inspect relevant quota without leaving the session.
- The selected model and projected integration stay aligned before message submission.
- Existing backend normalization, security, and caching contracts are reused.
- Session context usage and subscription usage remain visibly separate.

### Trade-offs

- Opening multiple sessions can trigger separate browser queries after cache freshness expires.
- The displayed provider quota can change independently through other sessions or external clients.
- Compact presentation cannot show every provider limit until the user opens the model picker.

## Related Decisions

- ADR-0169 remains authoritative for integration-scoped usage, provider adapters, permissions, and the canonical LLM Settings surface. This ADR extends ADR-0169-D6 with a contextual session projection.
- ADR-0114 remains authoritative for run-scoped context usage in the session header.
- ADR-0103 and ADR-0104 remain authoritative for per-prompt model and reasoning-effort selection in the composer.
