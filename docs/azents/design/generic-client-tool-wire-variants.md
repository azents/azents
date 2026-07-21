---
title: "Generic client tool wire variant selection"
created: 2026-07-21
updated: 2026-07-21
implemented: 2026-07-21
tags: [architecture, backend, engine, llm, testing]
---

# Generic client tool wire variant selection

## Problem

Client-tool preparation currently contains literal `apply_patch` checks because one profile enum
represents both model eligibility and selected provider transport. The catalog cannot select another
dual-dialect tool without adding another tool-name exception.

## Goals

- Preserve existing `apply_patch` semantic eligibility and exposure behavior.
- Select plaintext custom on native OpenAI Responses and JSON function on other existing eligible
  transports.
- Make variant selection independent of tool names.
- Freeze declaration, handler routing, prompt, and durable dialect from one prepared selection.

## Non-goals

- Change durable call/result dialect fields or Runtime apply-patch semantics.
- Add new dialects, providers, model eligibility, configuration flags, or fallback retries.
- Generalize provider event normalization beyond its existing dialect-based representation.

## Architecture

### Model profile registry

The model registry returns semantic profiles only. The V4A patch profile remains granted to the same
OpenAI GPT-family model snapshots as before. It does not identify a tool or select a wire format.
Exact-model precedence and conflict validation stay unchanged.

### Adapter profile registry

A separate registry resolves one adapter profile from provider, adapter, and native format. A profile
contains an ordinary-tool default preference plus optional model-profile-specific preferences:

- native OpenAI Responses: ordinary tools use `json_function`; the V4A semantic profile prefers
  `plaintext_custom`, then `json_function`;
- generic LiteLLM Responses: ordinary tools use `json_function`;
- OpenRouter LiteLLM Responses: ordinary tools use `json_function`; the V4A semantic profile uses
  `json_function`;
- unmatched routes: no supported client-tool variants.

Provider-specific rules override adapter-wide rules at a higher specificity. This preserves the
existing exposure set without coupling the registry to a tool name. The registry validates
duplicate/overlapping route rules and duplicate model-profile preferences before preparation.

### Tool-declared variants

`FunctionTool` carries an immutable tuple of variants. A variant contains:

- wire dialect;
- optional model guidance for that exact variant.

Ordinary tools default to one JSON-function variant. `apply_patch` declares JSON-function and
plaintext-custom variants and retains one semantic model-profile requirement. Prefixing a tool copies
its variants unchanged.

### Prepared projection

Projection performs the same algorithm for every tool:

1. reject the tool when its required semantic profile is absent;
2. resolve the adapter preference for the tool's required model profile, or the default preference
   for an unconditional tool;
3. walk that dialect preference in order;
4. choose the first dialect declared by the tool;
5. validate that the handler implements the selected dialect protocol;
6. freeze the selected dialect in the catalog;
7. include the selected variant prompt with source metadata.

No step checks a model-visible tool name. No provider failure can change the frozen variant.

### Historical compatibility

The Responses lowerer receives whether the resolved adapter profile supports plaintext custom. This
replaces the apply-patch-specific historical route predicate while preserving current durable history
behavior.

## Failure handling

- Missing model profile: omit the tool.
- No adapter rule or no compatible declared variant: omit the tool.
- Duplicate tool variants or conflicting adapter rules: fail preparation as invalid code-owned
  configuration.
- A selected plaintext-custom variant without the required handler protocol: fail preparation before
  provider I/O.

## Migration and rollout

All changed fields are process-local preparation metadata. There is no database or API migration.
Durable wire dialect values remain unchanged. The refactor can ship in one PR because candidate
catalog construction, selection, execution, and history lowering are verified together.

## Observability

Existing prepared-tool logs retain resolved model profiles and aggregate tool counts. Add the resolved
adapter profile ID and preferred dialect list without logging tool arguments or provider credentials.

## Test Strategy

Deterministic backend tests are primary because selection is a pure preparation boundary.

- Unit-test model and adapter registries, specificity, conflict rejection, unmatched routes, and
  default/profile-specific preference order.
- Catalog tests use a neutral dual-dialect tool name to prove selection has no `apply_patch` dependency.
- Adapter assembly tests cover native OpenAI Responses custom selection and OpenRouter JSON fallback.
- Existing apply-patch parsing, execution, persistence, continuation, cancellation, and lowering tests
  remain regression coverage.
- Run focused pytest, Ruff, Pyright, pre-commit, and required GitHub CI. Existing deterministic E2E is
  sufficient because the public run path and Runtime operation do not change; no new credentials or
  fixture state are required.

## Feasibility

| Boundary | Result | Evidence |
| --- | --- | --- |
| Model eligibility | feasible | Existing model compatibility registry already resolves immutable model profiles. |
| Adapter selection | feasible | `ClientToolRoute` already carries provider, adapter, and native format before catalog projection. |
| Tool metadata | feasible | `FunctionTool` is immutable process-local metadata and is copied during prefixing. |
| Prompt selection | feasible | Prepared catalog already projects toolkit prompt inputs before request construction. |
| Execution | feasible | Executor already dispatches by frozen durable dialect and handler protocol. |
| Persistence/API | feasible | No canonical event or schema change is required. |
| Verification | feasible | Existing focused projection, adapter, and lifecycle suites exercise the required boundaries. |
