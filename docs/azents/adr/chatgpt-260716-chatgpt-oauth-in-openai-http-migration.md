---
title: "Include ChatGPT OAuth in the OpenAI-Native HTTP Migration"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, oauth, transport, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: chatgpt-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0152-include-chatgpt-oauth-in-openai-native-http-migration.md"
---

# chatgpt-260716/ADR: Include ChatGPT OAuth in the OpenAI-Native HTTP Migration

## Status

Accepted. Implementation has not started.

## Context

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-107) and [http-260716/ADR](./http-260716-openai-http-migration-by-semantic-parity.md) scoped the first OpenAI-native HTTP migration to `LLMProvider.OPENAI` and retained `LLMProvider.CHATGPT_OAUTH` on LiteLLM HTTP. That scope does not match the intended migration boundary.

Both integrations use a Responses-compatible HTTP protocol and must move through the generic native adapter pipeline established by [generic-260716/ADR](./generic-260716-generic-adapter-request-types.md). ChatGPT OAuth has a distinct Responses Lite request dialect and storage requirement, but those differences do not justify retaining a second LiteLLM-owned request and transport path inside the OpenAI-compatible provider family.

The current provider contracts differ in one important respect:

- OpenAI API-key requests do not need an explicit `store` value and may use stored-response continuation when otherwise eligible;
- ChatGPT OAuth requires `store=false`, provider-specific Responses Lite headers and input items, encrypted reasoning continuation data, and complete logical input on every request.

## Decision

### Migrate both OpenAI-compatible providers

Phase 1 migrates both `LLMProvider.OPENAI` and `LLMProvider.CHATGPT_OAUTH` to the official OpenAI SDK HTTP streaming transport. The scope includes primary Agent sampling, context-compaction summary generation, and automatic Session title generation for both providers.

Non-OpenAI-compatible providers remain on LiteLLM. LiteLLM may remain a pricing utility where separately decided, but it does not lower or transport requests for either migrated provider.

This decision supersedes only the ChatGPT OAuth exclusions in [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-108) and [http-260716/ADR](./http-260716-openai-http-migration-by-semantic-parity.md). Their HTTP-first sequencing, semantic-parity contract, and later WebSocket deferral remain unchanged.

### Preserve provider-specific storage semantics

`LLMProvider.OPENAI` does not force a `store` request field. Its canonical request omits `store`, preserving the provider default and the existing eligibility for in-memory `previous_response_id` continuation.

`LLMProvider.CHATGPT_OAUTH` always sends `store=false`. It never sends `previous_response_id` and always sends the complete logical input produced before physical transport optimization.

The complete logical request is still materialized and checked by `NativeRequestSizeGuard` for both providers before any OpenAI continuation reduces the physical HTTP input.

### Keep ChatGPT OAuth request dialect explicit

The OpenAI-native lowerer and request types represent ChatGPT OAuth's Responses Lite requirements explicitly, including:

- the Responses Lite protocol headers and Session affinity headers;
- the developer `additional_tools` input item;
- developer instructions in the input sequence;
- `reasoning.context="all_turns"`;
- `reasoning.encrypted_content` inclusion;
- `parallel_tool_calls=false`;
- the Session-scoped prompt cache key;
- full-context replay with response item IDs masked as required for unstored responses.

These are provider request semantics, not LiteLLM compatibility behavior. The OpenAI SDK supplies the HTTP client and event parsing but does not erase the dialect distinction.

## Consequences

- The Phase 1 migration has one SDK transport owner for both OpenAI API-key and ChatGPT OAuth Responses calls.
- ChatGPT OAuth no longer depends on LiteLLM request lowering, stream normalization, or HTTP transport behavior.
- The OpenAI-native request boundary must support the Responses Lite extensions and custom endpoint headers in addition to the public OpenAI request shape.
- OpenAI continuation behavior remains available without weakening ChatGPT OAuth's mandatory full-context, `store=false` contract.
- Deterministic parity fixtures and live verification must cover both provider dialects at all three call sites.
- ChatGPT OAuth credential refresh remains outside the request body and must complete before constructing the SDK client configuration.

## Alternatives Considered

### Keep ChatGPT OAuth on LiteLLM HTTP

Rejected because it would leave an intended migration target on a separate request transformation, stream normalization, and transport path.

### Force `store=false` for both providers

Rejected because `store=false` is a ChatGPT OAuth requirement, not a general OpenAI migration requirement. Applying it to OpenAI would disable the existing stored-response continuation optimization and change request cost and latency semantics.

### Apply OpenAI continuation to ChatGPT OAuth

Rejected because ChatGPT OAuth requires full-context unstored requests and must not depend on `previous_response_id`.

## Migration provenance

- Historical source filename: `0152-include-chatgpt-oauth-in-openai-native-http-migration.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
