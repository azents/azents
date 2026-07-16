---
title: "ADR-0162: Use Standard Responses for ChatGPT OAuth"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, oauth, transport, tools]
---

# ADR-0162: Use Standard Responses for ChatGPT OAuth

## Status

Accepted. Implemented by the same change.

## Context

ChatGPT's account model catalog exposes a `use_responses_lite` metadata field. Azents previously normalized that field into saved model capabilities and used it to select a private Responses Lite request dialect. That dialect moved tools into a developer `additional_tools` input item, moved instructions into developer input, added private compatibility and affinity headers, and changed reasoning and parallel-tool behavior.

Direct device-auth validation against the ChatGPT OAuth backend tested GPT-5.6 Sol, Terra, and Luna. All three models completed standard Responses requests and executed the provider-hosted `web_search` tool. The Responses Lite `additional_tools` dialect completed requests but did not execute hosted web search for any of the three models. Client function calls remained available in both dialects.

Supporting provider-hosted capabilities through Responses Lite would therefore require Azents to implement separate client-side executors coupled to private Codex endpoints and behavior. Responses WebSocket transport is a separate transport concern and does not require the Lite request dialect.

## Decision

ChatGPT OAuth always uses the standard Responses request contract for sampling, compaction, and automatic Session title generation.

- Tools remain in the top-level `tools` field.
- Instructions remain in the top-level `instructions` field.
- Azents does not select a request dialect from `use_responses_lite`, model names, or saved model capabilities.
- The model catalog does not normalize, persist, or expose a Responses Lite compatibility capability.
- The generic LiteLLM Responses lowerer and the OpenAI-native request model do not contain Responses Lite branches or extensions.
- Future Responses WebSocket work uses the standard Responses contract and remains independent of this decision.

ChatGPT OAuth retains its provider requirements that are independent of Responses Lite: `store=false`, complete logical input, encrypted reasoning content for stateless replay, no `previous_response_id`, the ChatGPT backend base URL, OAuth bearer credential, account header, and Azents client identity.

This decision supersedes only the Responses Lite dialect portions of ADR-0152. ADR-0152's OpenAI-native transport ownership and stateless ChatGPT storage semantics remain in force.

## Consequences

- Provider-hosted web search uses the standard Responses provider tool path for ChatGPT OAuth models.
- Azents avoids private Codex tool executors and private Responses Lite request extensions.
- Existing stored capability JSON that contains `responses_lite` remains readable because capability models ignore unknown fields; no data migration or compatibility fallback is required.
- Catalog refreshes stop copying the backend hint into model snapshots, source metadata, projection metadata, and public capability schemas.
- The standard request contract is covered for both the generic lowerer and the official OpenAI SDK request boundary.

## Alternatives Considered

### Keep Responses Lite and implement separate tool executors

Rejected because hosted web search did not execute through the Lite dialect, and reproducing Codex-specific search or image paths would couple Azents to private endpoints instead of the provider's standard Responses tool contract.

### Retry Lite requests with the standard contract

Rejected because dual request dialects create fallback-dependent behavior and duplicate transport semantics. Azents uses one explicit standard contract.

### Select Lite by model name

Rejected because model names and rollout cohorts are not protocol guarantees, and live validation showed the same standard behavior across Sol, Terra, and Luna.
