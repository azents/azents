---
title: "Model Context Ranges"
created: 2026-08-27
updated: 2026-08-27
tags: [model, context, catalog, agent, frontend, backend, engine, api, architecture]
document_role: primary
document_type: adr
snapshot_id: context-260827
---

# Model Context Ranges

- Snapshot: `context-260827`
- Document reference: `context-260827/ADR`
- Requirements:
  [`context-260827/REQ`](../requirements/context-260827-model-context-ranges.md)

## Context

The normalized model capability currently contains `max_input_tokens` and
`max_output_tokens`. Runtime, Agent display, and UI use `max_input_tokens` as both
the model's ordinary context window and its hard ceiling.

Some provider metadata, including the ChatGPT Codex model catalog, publishes a
smaller default `context_window` and a larger `max_context_window` for explicit
long-context overrides. The raw provider metadata is retained, but normalization
selects the default value first and discards the larger maximum from the executable
capability.

Catalog snapshots and Agent model-selection snapshots store capabilities as JSON,
so an additive field can be read by new code while historical snapshots continue
to omit it.

## Decision Map

### Fixed or derived outcomes

- The capability model and runtime rule apply to every provider.
- An unset Agent option cap uses the model default.
- A configured Agent option cap is clamped to the model maximum.
- A missing default falls back to the maximum.
- Main and lightweight options continue to use the smaller resolved window for
  compaction.
- Historical JSON without a default field remains valid.

### Accepted material decisions

- [x] `context-260827/ADR-D1`: add a nullable default input-window capability while
  retaining the existing maximum input-window capability.
- [x] `context-260827/ADR-D2`: resolve one effective option window from provider
  capability, metadata fallback, and nullable user intent at every existing
  resolution boundary.

### Agent-owned implementation categories

- Exact helper, property, DTO, fixture, and localization identifiers.
- Source-file boundaries and local refactoring needed to remove duplicated
  resolution logic.
- Test case names, story fixture values, and generated-client mechanics.

## context-260827/ADR-D1. Represent a nullable default beside the maximum

The shared context-window capability adds a nullable default input-token value and
retains `max_input_tokens` as the hard provider/model ceiling.

The semantic invariant is:

```text
resolved default = default_input_tokens ?? max_input_tokens
```

When both values exist, the resolved default must not exceed the maximum. Provider
projection preserves both authoritative values when available. A provider with one
known input limit projects it as the maximum and may omit the default; the shared
fallback produces the required behavior.

The field is additive in JSON and OpenAPI. Historical capabilities that omit it
remain valid and preserve their current behavior because their maximum becomes the
resolved default. No compatibility alias or ChatGPT-specific field is introduced.

### Rejected alternatives

- **Replace `max_input_tokens` with the provider default:** this continues losing the
  maximum and prevents safe explicit long-context caps.
- **Replace `max_input_tokens` with the larger provider maximum only:** this makes
  long-context execution the default and changes normal runtime behavior.
- **Add ChatGPT-only metadata handling in runtime or UI:** this duplicates provider
  semantics outside the normalized capability and does not solve the shared model.

## context-260827/ADR-D2. Centralize effective-window resolution

Every Agent-facing and runtime resolution boundary uses one shared operation with
these inputs:

- nullable capability default;
- nullable capability maximum;
- provider/model metadata fallback;
- nullable user-configured option cap.

The operation resolves the maximum first, resolves the default with maximum
fallback, clamps an inconsistent default to the maximum, and then returns:

```text
effective = default                         when user cap is null
effective = min(user cap, maximum)          when user cap is set
```

The existing LiteLLM lookup and 128,000-token fallback remain the final source when
the normalized capability has no usable input limit. A known capability default is
never reduced by a smaller fallback-only metadata value.

Foreground Run preparation, Agent API effective-limit display, lightweight
compaction resolution, and explicit subagent override resolution use the same
operation. The downstream `RunRequest` continues to receive the already resolved
effective per-model input window, preserving provider adapter contracts.

### Rejected alternatives

- **Resolve only in the ChatGPT catalog projection:** stored Agent snapshots from
  other providers and historical data would still use divergent runtime rules.
- **Let UI compute fallback independently:** this creates a second semantic
  implementation that can disagree with runtime.
- **Persist a newly resolved effective value into every historical snapshot:** this
  requires unnecessary migration and freezes derived behavior into stored data.

## Consequences

- The public capability contract gains one nullable field and generated clients must
  be regenerated.
- Provider adapters can populate distinct values without adding provider-specific
  runtime branches.
- Existing snapshots and single-limit providers preserve behavior.
- UI copy can distinguish default behavior from the configurable maximum.
- The rollout requires catalog refresh only to obtain newly available provider
  distinctions; it does not require a relational data migration.
