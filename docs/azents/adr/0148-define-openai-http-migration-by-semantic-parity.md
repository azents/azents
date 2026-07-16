---
title: "ADR-0148: Define the OpenAI HTTP Migration by Semantic Parity"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, testing]
---

# ADR-0148: Define the OpenAI HTTP Migration by Semantic Parity

## Status

Accepted. Implementation has not started.

## Context

ADR-0147 establishes an OpenAI-native Responses transport family and requires migrating OpenAI HTTP calls to the official SDK before introducing WebSocket transport. A migration completion contract is needed because the current LiteLLM and future OpenAI SDK paths do not produce byte-identical wire requests or response objects.

Treating LiteLLM's transformed wire representation as the target would copy an intermediary's incidental behavior into the new OpenAI lowerer. Migrating only primary Agent sampling would instead leave OpenAI request semantics split between the new adapter and the shared LiteLLM Responses helper used by context compaction and automatic Session title generation.

The stable contract must cover product-visible behavior and existing run lifecycle invariants while allowing the OpenAI-native path to represent the same semantics in the official SDK's types.

## Decision

### Use semantic parity rather than LiteLLM wire parity

The OpenAI SDK HTTP migration is complete when the same Azents inputs and configuration produce the expected OpenAI Responses semantics and the same Azents-observable outcomes. Literal equality with LiteLLM's serialized HTTP body, private metadata, or response wrapper types is not required.

Request parity covers every currently supported OpenAI request dimension, including:

- model identity and endpoint credentials;
- instructions and input items;
- client and provider-hosted tools;
- text, reasoning, include, sampling, and prompt-cache options;
- file and media materialization;
- `store=false` and continuation behavior where applicable;
- request-size enforcement after final OpenAI lowering.

Output parity covers:

- canonical assistant, reasoning, tool-call, and provider-tool events;
- live text deltas and completed output items;
- explicit `response.completed` success classification;
- provider-reported failed or incomplete responses;
- usage provenance and `cost_usd` accounting;
- cancellation, timeout, cleanup, and Azents failed-run retry behavior;
- privacy-safe structured logging.

### Migrate all OpenAI Responses call sites in the HTTP phase

The HTTP phase covers every call using `LLMProvider.OPENAI`, including primary Agent sampling, context-compaction summary generation, and automatic Session title generation. They share OpenAI endpoint configuration and transport ownership even when a helper call begins with prebuilt Responses input items rather than the durable event transcript.

`LLMProvider.CHATGPT_OAUTH` remains on its existing LiteLLM HTTP full-context path with `store=false`. Non-OpenAI providers remain on LiteLLM.

### Establish parity with deterministic tests and bounded live evidence

The required deterministic suite verifies the OpenAI lowerer, SDK call arguments, stream-event normalization, usage/cost extraction, failure mapping, timeout/cancellation behavior, and each OpenAI call site. Golden fixtures assert the semantic request and canonical output contracts rather than SDK object internals or JSON key ordering.

Live OpenAI verification supplements deterministic coverage for provider behavior that cannot be faithfully simulated, including accepted request options, representative tool and reasoning streams, usage fields, and cost inputs. Live evidence is a rollout gate for enabling the new path in production, but credentials are not required for the ordinary hermetic unit-test suite.

A differential test may compare the old LiteLLM path and the new OpenAI SDK path during migration. Differences are classified against this semantic contract; LiteLLM output is evidence, not the source of truth.

## Consequences

- The migration removes LiteLLM-specific transformations instead of preserving them as an accidental compatibility layer.
- Primary sampling, compaction, and title generation cannot silently diverge in OpenAI endpoint behavior after cutover.
- Test fixtures remain stable across harmless SDK serialization changes.
- Usage and cost accounting need an explicit OpenAI-native contract because direct SDK responses do not expose LiteLLM's `_hidden_params.response_cost`.
- A production cutover requires representative live OpenAI evidence in addition to hermetic CI.
- ChatGPT OAuth and non-OpenAI provider behavior remain outside the migration and retain their current adapters.

## Alternatives Considered

### Require byte-identical LiteLLM wire requests

Rejected because it would make LiteLLM's version-dependent transformations part of Azents' new OpenAI contract and would not guarantee parity with the later SDK WebSocket path.

### Migrate only primary Agent sampling first

Rejected because OpenAI compaction and title calls would retain a second request and transport owner. This would make provider behavior depend on call site and defer the same migration risk.

### Cut over after unit tests without live provider evidence

Rejected because local mocks cannot prove that OpenAI accepts every request combination or emits the exact event and usage variants needed by the normalizer and cost path.
