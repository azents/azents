---
title: "Model Context Ranges Requirements"
created: 2026-08-27
updated: 2026-08-27
tags: [model, context, catalog, agent, frontend, backend, engine, api]
document_role: primary
document_type: requirements
snapshot_id: context-260827
---

# Model Context Ranges Requirements

- Snapshot: `context-260827`
- Document reference: `context-260827/REQ`

## Problem

Azents represents a model's context capability with one input-token value. Some
providers distinguish the context window used by default from a larger maximum
window available when a user explicitly requests long-context execution. Collapsing
those values causes the catalog, Agent settings, and runtime to expose only one of
the two behaviors.

## Primary Actor

A Workspace administrator selecting a model and configuring its context-window cap
for an Agent or Workspace default model option.

## Primary Scenario

The administrator selects a model whose provider advertises different default and
maximum input windows. The catalog shows both values. Leaving the Agent option cap
unset uses the provider's default window, while entering a larger cap uses that
requested value up to the provider's maximum.

## Supporting Scenarios

- A provider publishes only one context-window value, and Azents uses that value as
  both the default behavior and the maximum known limit.
- An existing catalog or Agent snapshot has no separate default value and continues
  to execute with its previously stored maximum value as the default.
- Main, lightweight, and explicit subagent model selections use the same context
  resolution rules.

## Goals

- Represent default and maximum input context windows independently in the shared
  model capability contract.
- Apply one provider-neutral resolution rule across catalog, Agent, Workspace,
  runtime, compaction, and subagent paths.
- Preserve current behavior when a provider or historical snapshot has no distinct
  default value.
- Make the user-visible catalog and Agent settings explain both values when they
  differ.

## Non-Goals

- Changing model output-token capability semantics.
- Inferring a larger maximum window when neither provider metadata nor the existing
  model metadata source supplies one.
- Adding provider-specific runtime modes or ChatGPT-only context configuration.
- Changing the persisted meaning of an explicitly configured Agent option context
  cap.

## Requirements

### REQ-1. Shared default and maximum context capability

Every model provider must project context-window information through one shared
capability that can independently represent the default input window and maximum
input window.

**Acceptance criteria**

- A provider with distinct values exposes both values without replacing either one.
- A provider with one known value remains representable without a provider-specific
  contract.
- Public catalog and model-selection snapshots expose the same shared capability
  shape for every provider.

### REQ-2. Default fallback

When a model has no distinct default input-window value, Azents must use the known
maximum input window as its default.

**Acceptance criteria**

- Existing snapshots that contain only the maximum value retain their previous
  effective behavior.
- Providers that expose only one context limit use that limit when no user cap is
  configured.
- The fallback is identical for foreground, lightweight, and subagent model
  resolution.

### REQ-3. Explicit cap and maximum enforcement

When a user configures an Agent option context cap, Azents must use the requested
value without exceeding the model's known maximum.

**Acceptance criteria**

- An unset option cap uses the resolved default.
- A positive option cap below the maximum uses the configured cap.
- A positive option cap above the maximum is clamped to the maximum.
- Main-model and lightweight-model limits still combine through the existing
  smaller-window compaction rule.

### REQ-4. User-visible distinction

The model catalog and Agent option settings must distinguish the default input
window from the maximum input window when both are known and different.

**Acceptance criteria**

- A catalog model with different values communicates both values.
- A model with one effective value remains concise and does not present a false
  distinction.
- The Agent context-cap setting identifies the default used when left blank and the
  maximum accepted by runtime.

### REQ-5. Compatible rollout

The change must be additive for persisted catalog and Agent model snapshots.

**Acceptance criteria**

- No relational database migration is required solely to add the default value.
- Old JSON snapshots without the new field remain readable and executable.
- Regenerated API clients include the new capability field.
- Catalog refreshes populate distinct values when a provider supplies them.

## Fixed Constraints

- Catalog provider metadata remains the source of provider-specific context values.
- Agent option `context_window_tokens` remains nullable user intent and may be
  stored above the current provider limit.
- Runtime remains the authority that clamps configured intent to the resolved model
  maximum.
- Model capability changes are delivered through generated OpenAPI clients.

## Open Assumptions

- Providers that expose one context value do not require Azents to distinguish
  whether that value is named "default" or "maximum"; Azents treats it as the known
  maximum and derives the default from it.

## Confirmation

Confirmed by the requester on 2026-08-27 before ADR and design decisions began. The
requester explicitly required a provider-neutral model with separate default and
maximum values and maximum-to-default fallback when no distinct default exists.
