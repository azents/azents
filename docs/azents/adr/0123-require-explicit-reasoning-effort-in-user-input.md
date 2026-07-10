---
title: "ADR-0123: Require an Explicit Reasoning Effort in User Input"
created: 2026-07-10
tags: [architecture, agent, frontend, engine]
---

# ADR-0123: Require an Explicit Reasoning Effort in User Input

## Context

ADR-0111 exposed the provider-default `null` value as a visible `Default` choice in the prompt composer. That representation preserves the runtime distinction between an explicit effort and no provider override, but it makes user intent ambiguous: a reasoning-capable model can be submitted without the user seeing which effort will be used.

LiteLLM publishes sparse reasoning capability flags rather than one ordered effort array. Azents must reconstruct the selectable list consistently, and an empty reconstructed list cannot safely be interpreted as unrestricted support.

Agent settings also need a deterministic initial effort coupled to the Agent's default model. Workspace settings only seed model choices for new Agents and do not need a separate reasoning-effort default.

## Decision

Supersede ADR-0111's visible `Default` selection behavior.

For every user-facing model selection that advertises one or more explicit reasoning efforts:

- show only the explicit efforts supplied by the normalized model capability;
- always keep one concrete effort selected;
- preserve the current effort when supported after a model change;
- otherwise select the closest supported effort in the canonical order, using `medium` as the initial baseline and preferring the nearest lower effort before a higher effort.

The canonical order is `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.

When a model advertises no explicit effort levels, hide the control and use internal `null`. An empty effort list rejects every non-null effort; it is not unrestricted support. Runtime and persistence may continue to represent provider/model default as `null`, but normal user input must not expose `Default` as a selectable option when explicit efforts are available.

Derive normalized effort lists from LiteLLM's canonical provider model metadata type. `none`, `minimal`, `low`, `xhigh`, and `max` depend on their corresponding capability flags. OpenAI GPT-5-family models additionally use LiteLLM's baseline `medium` and `high` contract and opt-out `low` semantics; other reasoning providers receive only explicitly asserted levels. Preserve deterministic canonical ordering.

Store the Agent's configured effort with its default model settings and use it to initialize a new session when supported. Workspace model defaults do not store a separate reasoning effort.

## Rejected options

### Keep a visible Default option

This exposes an implementation-level no-override state instead of a concrete user choice and leaves actual inference behavior implicit.

### Treat an empty effort list as unrestricted

Missing metadata would then authorize every enum value, including levels the provider may reject.

### Maintain a frontend fallback effort list

The frontend would diverge from normalized backend capabilities and could present unsupported choices.

### Add a Workspace reasoning-effort default

Reasoning effort is coupled to the selected Agent default model. A separate Workspace value introduces another precedence layer without improving runtime behavior.

## Consequences

- Composer and Agent settings share capability-aware normalization.
- Model changes can automatically select another concrete effort, and the resulting control remains visible to the user.
- Models with no advertised explicit levels submit `null` and show no effort control.
- Backend validation is strict for every non-null effort at configuration and run resolution boundaries.
- Existing persisted `null` values remain valid as provider/model-default state, including non-user execution paths.
