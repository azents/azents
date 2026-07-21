---
title: "ADR-0180: Remove Percentage Rollout from Apply-Patch Custom Selection"
created: 2026-07-21
tags: [architecture, backend, engine, llm, openai, runtime, tools]
---

# ADR-0180: Remove Percentage Rollout from Apply-Patch Custom Selection

## Context

ADR-0179 introduced a provider-specific plaintext-custom transport for the logical
`apply_patch` tool. Its initial implementation added a percentage-based cohort selector
and adapter configuration to control exposure. That selector is a feature flag and is
not part of the required provider-dialect behavior.

The supported transport boundary is already an exact code-owned conjunction of provider,
authentication mode, adapter, endpoint class, model identifier, and semantic profile.
Adding a session- or tenant-derived percentage decision makes identical supported routes
present different client-tool contracts for reasons unrelated to provider compatibility.

## Decision

Supersede ADR-0179-D5 and ADR-0179-D6 only with respect to percentage rollout and
cohort selection:

1. Remove the percentage configuration, cohort key, deterministic hash calculation, and
   any global or profile-specific rollout control for plaintext-custom `apply_patch`.
2. On the exact reviewed official OpenAI API-key Responses route for the exact reviewed
   model, select the plaintext-custom dialect directly. This selection remains code-owned
   and cannot be widened by runtime or administrator configuration.
3. All other routes retain their independently verified JSON-function fallback or omit
   `apply_patch` when neither transport is verified.
4. The prepared call still has exactly one dialect. Retry, continuation, cancellation,
   recovery, persistence, replay, and historical projection must not switch it.
5. Existing durable plaintext-custom lifecycle support remains required after a custom
   record exists. Removing the selector must not relabel or discard durable records.

## Consequences

- Identical reviewed routes receive the same dialect; session and tenant identity no
  longer affect provider-tool declaration selection.
- Expanding plaintext-custom support to another route or model requires a reviewed
  code change and full lifecycle evidence, not a configuration change.
- The immutable ADR-0179 and its implementation audit remain historical records. Current
  behavior is defined by this ADR and the living specs.
