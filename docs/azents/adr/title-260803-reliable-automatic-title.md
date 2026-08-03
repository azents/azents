---
title: "Reliable Automatic Session Titles"
created: 2026-08-03
tags: [session, title, llm, external-channel, architecture]
document_role: primary
document_type: adr
snapshot_id: title-260803
---

# Reliable Automatic Session Titles

- Snapshot: `title-260803`
- Document reference: `title-260803/ADR`
- Requirements: [`title-260803/REQ`](../requirements/title-260803-reliable-automatic-title.md)
- Mode: Collaborative
- Decision owner: requester

## Context

Automatic title generation currently invokes the Agent's saved lightweight-model selection through a plain-text Responses request and cleans the first non-empty output line. Each saved model selection already snapshots `normalized_capabilities.tool_calling.strict_json_schema` as `true`, `false`, or `null`.

The shared provider-failure taxonomy distinguishes authentication, permission, quota, rate limit, invalid request, model availability, context limit, policy, provider availability, transport, and unknown outcomes. It does not currently distinguish an unsupported Structured Output contract from every other invalid request.

External Channel title input may include provider markup used to address the connected Bot or App. Deterministic removal would require additional reference evidence or would risk removing other request-relevant mentions. The requester accepted prompt-only handling and the residual possibility that a model may not follow that instruction.

## Fixed Outcomes

- The Agent's saved lightweight provider integration and model remain unchanged throughout title generation.
- Saved `strict_json_schema=true` uses only Structured Output.
- Saved `strict_json_schema=false` uses only plain text.
- Saved `strict_json_schema=null` tries Structured Output before any plain-text compatibility mode.
- Capability metadata selects the title invocation mode but never restricts the lightweight-model picker.
- The title prompt removes its summary-rule contradiction, meta `user prompt` wrapper, and overbroad prohibition on user-mentioned tools.
- Existing language behavior and examples remain unchanged solely with respect to language bias.
- No semantic title validator or prohibited-phrase catalog is added.
- Title instructions tell the model to ignore invocation-only Bot or App markup while preserving request-relevant references.
- No invocation-reference state, canonical-body rewrite, deterministic mention removal, or semantic title validator is added.
- Existing automatic-title authority, provider retry policy, failure isolation, and Discord projection ownership remain unchanged.
- The implemented `title-260802` snapshot remains immutable.

## Decision Backlog

- [x] D1. Source of truth and tri-state selection for the title invocation mode.
- [x] D2. Failure boundary and retry interaction for unknown-capability output-mode fallback.

## Accepted Decisions

### title-260803/ADR-D1 — The saved model capability selects the title invocation mode

The effective lightweight `AgentModelSelection` snapshot is the source of truth for title invocation mode. Its `normalized_capabilities.tool_calling.strict_json_schema` value selects one of three branches:

- `true`: use only the Structured Output title contract;
- `false`: use only the existing plain-text title contract; and
- `null`: start with the Structured Output title contract and follow the separately decided compatibility-fallback boundary.

Every branch retains the exact saved provider integration ID and model identifier. No branch re-resolves the live catalog, restricts model selection, or selects another fallback model. A later catalog capability change does not silently mutate an existing Agent snapshot.

Rejected alternatives:

- Restricting lightweight-model selection would exclude compatible models whose capability is unknown and would couple all lightweight work to the title feature.
- Re-resolving the current catalog at title-generation time would violate saved-snapshot execution semantics and make existing Agents change behavior without an Agent update.
- Trying Structured Output for an explicitly unsupported model or plain text after a failure from an explicitly supported model would disregard the accepted tri-state policy.

Affected requirements: `title-260803/REQ-1`, `title-260803/REQ-2`.

### title-260803/ADR-D2 — Unknown capability falls back only on output-contract incompatibility

When the saved capability is `null`, the title operation starts in Structured Output mode. It transitions once to plain-text mode only when one of these bounded observations proves that the requested output contract is unavailable or was not honored:

- the provider explicitly identifies the response format or JSON Schema contract as unsupported;
- the routed provider reports that no endpoint can satisfy the requested output parameters; or
- the provider returns a successful response that cannot be decoded through the requested title schema.

Authentication, permission, billing, rate limiting, model availability, context limit, content policy, timeout, cancellation, transport, provider-unavailable, and unclassified failures do not change output mode. They retain the existing title provider-failure and retry behavior.

The output-mode transition is operation-local and non-durable. Once incompatibility is observed, the remainder of that title operation uses plain text; the existing provider retry policy may retry the active mode but cannot transition modes again. A failed plain-text phase preserves the deterministic initial title.

ChatGPT OAuth remains `null` unless its own catalog path supplies verified capability evidence. Public OpenAI model capability is not copied into the ChatGPT OAuth snapshot. Its private Codex backend therefore follows the unknown branch and may fall back on explicit contract rejection or schema-decode failure without changing OAuth integration or model.

Rejected alternatives:

- Falling back on every Structured Output failure would duplicate calls during authentication, rate limit, timeout, transport, or provider incidents and would misclassify operational failure as format incompatibility.
- Requiring only a provider-authored unsupported error would miss endpoints that accept but ignore the Structured Output parameter and return undecodable plain text.
- Re-probing Structured Output after the operation has already observed incompatibility would add redundant calls without new evidence.

Affected requirements: `title-260803/REQ-1`, `title-260803/REQ-2`.

## Closed Without Decision

Invocation-reference persistence and deterministic removal require no ADR decision
because the confirmed Requirements explicitly exclude them. Prompt-only handling is
required by `title-260803/REQ-3`.
