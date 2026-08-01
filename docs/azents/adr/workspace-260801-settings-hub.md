---
title: "Workspace Settings Hub"
created: 2026-08-01
tags: [workspace, settings, frontend, architecture]
document_role: primary
document_type: adr
snapshot_id: workspace-260801
---

# workspace-260801/ADR: Workspace Settings Hub

## Requirements

- [workspace-260801/REQ](../requirements/workspace-260801-settings-hub.md)

## Context

Workspace settings currently render `LlmSettingsPage` directly at `/w/{handle}/settings`. The page combines Workspace default model settings and LLM provider integration management in one state container and one scrolling surface. Agent settings already use a settings overview with focused detail routes, an identity header, and explicit return navigation.

The approved Requirements preserve current Workspace shell ownership, settings authorization, backend contracts, stored data, and unrelated Workspace navigation. The design therefore needs stable detail routes, a clear UI reuse boundary, and a state ownership split that does not create a second configuration authority.

## Decision Backlog

- [x] D1. Choose the Workspace settings detail route structure and the transition of `/w/{handle}/settings` from the existing combined page to the overview.
- [x] D2. Choose whether to generalize Agent settings layout components or introduce Workspace-specific settings layout components built from shared visual primitives.
- [x] D3. Choose whether the current combined LLM settings container remains the state owner for both detail pages or is replaced by focused containers with shared query-derived helpers.

The following behavior is fixed by the confirmed Requirements and is not part of the decision backlog:

- all current Workspace members retain settings visibility;
- existing Owner-only management behavior remains unchanged;
- `/w/{handle}/settings` becomes the settings overview;
- default model settings and LLM provider integrations become separate detail destinations;
- unrelated Workspace navigation remains outside the settings overview;
- backend APIs, persistence, and credential behavior remain unchanged for this work.

## Decisions

### workspace-260801/ADR-D1. Use explicit settings-area URLs behind one validated section route

The Workspace settings routes are:

- `/w/{handle}/settings` — settings overview
- `/w/{handle}/settings/models` — Workspace default model settings
- `/w/{handle}/settings/llm-integrations` — LLM provider integration management

The two detail destinations use one validated `/settings/[section]` route entry. Only `models` and
`llm-integrations` are accepted; any other section returns 404. The former combined settings page is
not retained as a compatibility fallback because `/settings` becomes the single overview authority.

This naming keeps LLM provider integrations distinct from the existing Workspace
`/integrations` destination for external channels and describes each destination as a settings area
rather than one record.

### workspace-260801/ADR-D2. Share a domain-independent settings page layout primitive

Extract a prop-driven `SettingsPageLayout` primitive that owns only the common settings page shell:

- a header slot;
- return-link href and label;
- return-bar maximum width; and
- the full-height content and scrolling boundary.

`AgentSettingsLayout` remains the Agent-domain wrapper and continues to own `AgentResponse`,
Agent translations, `AgentSettingsHeader`, and Agent-focused mobile navigation. A new
`WorkspaceSettingsLayout` owns Workspace identity, Workspace translations, and the
Workspace-specific header.

The shared primitive must not accept Agent-or-Workspace unions or import either feature domain. This
keeps Workspace settings inside `WorkspaceShell`, preserves Agent settings behavior, and makes the
spacing and return bar one visual authority.

### workspace-260801/ADR-D3. Replace the combined settings owner with two focused containers

Replace the existing combined `useLlmSettingsContainer` ownership with:

- `useWorkspaceModelSettingsContainer`, which owns Workspace model settings query and update state,
  integration-derived provider options, and catalog synchronization; and
- `useLlmIntegrationsContainer`, which owns integration list and provider-capability queries,
  create/edit/delete/enable actions, modal state, and subscription-usage composition.

Each detail page owns an independent discriminated-union loading/error/ready state and independent
mutation state. Sharing is limited to query-independent types and pure mapping helpers. tRPC remains
the server-state cache across route navigation; no settings-wide client context is introduced.

The former `LlmSettingsPage`, combined `LlmSettings` component, and
`useLlmSettingsContainer` are removed rather than retained as a second composition authority.

## Consequences

### Positive

- Workspace settings has one discoverable overview and two focused task surfaces.
- Stable URLs distinguish LLM credentials from external-channel integrations.
- Agent and Workspace settings share layout rules without sharing domain state.
- A failure in model settings no longer blocks integration management, and an unrelated provider
  capability failure no longer blocks model settings beyond the data that model selection actually
  requires.
- Existing server data, permissions, and mutations remain authoritative.

### Negative

- Workspace identity adds one frontend tRPC wrapper and one server read per settings entry when the
  value is not already cached.
- Some provider-option derivation is needed by both focused containers.
- Refactoring the Agent settings wrapper to use the shared primitive slightly expands the regression
  surface even though its public behavior is preserved.
- Existing combined-page Storybook coverage must be replaced with focused stories.

## Alternatives

| Alternative | Reason rejected |
| --- | --- |
| `/settings/model` and `/settings/integrations` | The generic `integrations` segment conflicts semantically with the existing Workspace external-channel destination, and the singular model name understates that the surface manages an option set and defaults. |
| Separate explicit route directories for both detail pages | The public URLs are equivalent, but duplicated route entrypoints add no ownership or loading benefit for two sections with the same Workspace boundary. |
| Keep the old combined page as a fallback | It would preserve a second UI authority that contradicts the approved settings overview contract. |
| Duplicate the Agent settings shell in a Workspace-only layout | Two copies of the return bar, widths, and spacing would drift while claiming to provide one settings experience. |
| Turn `AgentSettingsLayout` into an Agent-or-Workspace component | A cross-domain union would mix shell ownership, identity data, translations, and mobile navigation responsibilities. |
| Keep the combined container and pass different prop subsets to each page | Each task would still wait on and expose errors from unrelated queries and share one ambiguous mutation state. |
| Add a settings-wide client provider across detail routes | It adds a new cross-route lifecycle and client state authority where tRPC cache and focused containers are sufficient. |
