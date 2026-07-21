---
title: "Generalize Client Tool Wire Variant Selection Historical Decision Reconstruction"
created: 2026-07-21
tags: [architecture, backend, engine, llm, tools]
document_role: primary
document_type: adr
snapshot_id: client-260721
historical_reconstruction: true
migration_source: "docs/azents/adr/0181-generalize-client-tool-wire-variants.md"
---

# client-260721/ADR: Generalize Client Tool Wire Variant Selection Historical Decision Reconstruction

## Context

The first dual-dialect client tool introduced three coupled concepts under one profile enum:
model semantic eligibility, provider-adapter wire support, and the selected tool declaration.
Catalog projection then recognized the literal `apply_patch` name to retain the tool and replace its
wire dialect. Runtime prompt selection repeated the same function-versus-custom distinction.

This makes the generic client-tool preparation boundary depend on one tool's identity. A future tool
with multiple provider declarations would require another name check and another transport-specific
profile, rather than declaring its variants through the existing tool abstraction.

## Decision

Separate client-tool preparation into three independent configuration layers:

1. **Model profiles** determine semantic eligibility. The existing OpenAI GPT-family rule grants one
   V4A patch semantic profile. It does not select a wire format or identify a tool by name.
2. **Adapter profiles** declare a default wire-dialect preference for ordinary tools plus optional
   model-profile-specific preferences for a normalized provider/adapter/native-format route. Native
   OpenAI Responses keeps JSON function as its ordinary-tool default and prefers plaintext custom
   before JSON function for the V4A semantic profile. Generic LiteLLM Responses keeps the ordinary
   JSON-function default, while the existing OpenRouter route additionally enables JSON function for
   the V4A semantic profile.
3. **Tool variants** are declared on `FunctionTool`. Each variant identifies its wire dialect and may
   provide dialect-specific model guidance. Ordinary function tools implicitly declare only the JSON
   function variant. A dual-dialect tool explicitly declares both.

Prepared-call projection intersects the resolved model profiles, the adapter preference selected for
the tool's required model profile, and tool-declared variants. It selects the first compatible
variant, freezes its dialect, and includes that variant's prompt. A tool without a required model
profile uses the adapter's default preference. If semantic eligibility fails or no declared variant
is supported, the tool is omitted. Selection never branches on a model-visible tool name.

Historical dialect lowering uses the resolved adapter profile's supported dialect set. It does not
call an apply-patch-specific route predicate.

## Consequences

- `apply_patch` keeps its existing model eligibility and route exposure behavior.
- Native OpenAI Responses selects its plaintext-custom variant; other existing eligible transports
  retain JSON function.
- Catalog projection, prompt projection, and historical dialect capability become reusable for any
  future multi-variant client tool.
- Tool-specific parsing and execution remain owned by the tool handler; the generic catalog only
  selects and freezes declared variants.
- The earlier provider-specific dialect and rollout snapshots remain immutable historical records.
  This ADR supersedes their preparation
  mechanics where they require apply-patch-specific profile or route handling.

## Migration provenance

- Historical source filename: `0181-generalize-client-tool-wire-variants.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is recorded.
