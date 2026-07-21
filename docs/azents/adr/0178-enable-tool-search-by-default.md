---
title: "ADR-0178: Enable Tool Search by Default for New Agents"
created: 2026-07-21
tags: [architecture, backend, engine, toolkit, performance]
---
# ADR-0178: Enable Tool Search by Default for New Agents

## Context

ADR-0147 introduced Tool Search as an Agent-level opt-in capability with a default-disabled setting. The initial default prioritized compatibility while Azents validated deferred capability discovery, provider declaration budgets, prepared-call execution boundaries, and product-path behavior.

Those validations are complete. Models reliably recognize the direct Tool Search capability, discover deferred tools when needed, and show acceptable tool-selection performance. Keeping Tool Search disabled by default now preserves a larger legacy tool catalog without a corresponding product benefit.

The `agents.tool_search_enabled` column is a non-null persisted setting. Existing `false` values may represent deliberate administrator opt-outs, but the historical schema does not distinguish those from values created by the former default.

## Decision

Tool Search is enabled by default for newly created Agents.

The default changes consistently at every Agent creation boundary:

1. Python domain, service, repository, and public API create schemas default `tool_search_enabled` to `true`.
2. The Agent creation form initializes Tool Search as enabled.
3. The database column server default changes to `true` through a new forward migration.
4. Generated public API clients reflect the public API default.

Existing Agent rows are not bulk-updated. Their stored `tool_search_enabled` value remains authoritative, including `false`. Administrators can continue to explicitly disable Tool Search for an Agent through the existing API and UI.

## Rationale

- Deferred tool discovery is now understood and used effectively by supported models.
- Bounded model-visible tool projection improves request size and provider compatibility without requiring per-Agent setup.
- Preserving existing persisted values avoids overwriting an administrator's possible opt-out when historical default-created rows cannot be identified reliably.
- Updating the server default keeps direct database creation paths consistent with application-level creation paths.

## Consequences

- New Agents expose direct tools and `tool_search` rather than the complete deferred service catalog when deferred tools are attached.
- Existing Agents retain their current Tool Search behavior until an administrator updates the setting.
- A caller that requires the prior complete-catalog behavior must explicitly set `tool_search_enabled=false`.
- ADR-0147's default-disabled decision is superseded; its direct/deferred classification, budget, search, and execution-boundary decisions remain in effect.

## Alternatives Considered

### Keep Tool Search opt-in

Rejected because the validated default path now provides better bounded tool exposure and provider compatibility while models recognize the discovery capability reliably.

### Bulk-enable all existing Agents

Rejected because historical persisted `false` values cannot be distinguished from intentional administrator opt-outs.

### Remove the Agent-level setting

Rejected because explicit per-Agent opt-out remains useful for compatibility-sensitive or diagnostic workloads.
