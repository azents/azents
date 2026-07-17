---
title: "Provider-Hosted Image Generation Validation Report"
created: 2026-07-17
tags: [backend, engine, frontend, llm, storage, testenv]
---

# Provider-Hosted Image Generation Validation Report

## Scope

This report validates the implementation described by [`provider-hosted-image-generation.md`](./provider-hosted-image-generation.md).

The validation covers:

- provider-neutral builtin registration and model capability projection;
- OpenAI SDK, ChatGPT OAuth, and LiteLLM request lowering and replay behavior;
- transient Base64 handling and durable dual materialization as ModelFile plus Exchange attachment;
- retry-safe metadata admission and object compensation;
- direct generated-image presentation in the web chat surface;
- deterministic product-path E2E support for the OpenAI Responses transport.

## Environment

- Date: 2026-07-17
- Worktree branch: `feature/provider-hosted-image-generation-validation`
- Python: 3.14
- Node/pnpm: repository-pinned toolchain
- Local Docker: unavailable because `/var/run/docker.sock` is not present
- Deterministic image fixture: `testenv/azents/e2e/src/support/fixtures/provider-image-generation.png`
- Fixture size: 69 bytes
- Fixture SHA-256: `b1ff9c8ea3a780bad09b346c423d2d0e46815926879b18e841d928376a946640`

## Validation Results

### Backend runtime, materialization, and replay

The focused backend suite passed with 238 tests:

```console
cd python/apps/azents
uv run pytest -q \
  src/azents/testing/deterministic_model_listing_test.py \
  src/azents/core/builtin_tools_test.py \
  src/azents/core/llm_catalog_test.py \
  src/azents/services/provider_hosted_tools_test.py \
  src/azents/services/model_listing/providers_test.py \
  src/azents/services/llm_catalog/system_projection_test.py \
  src/azents/engine/events/litellm_responses_test.py \
  src/azents/engine/events/openai_responses_test.py \
  src/azents/engine/events/provider_output_test.py \
  src/azents/engine/events/execution_test.py \
  src/azents/engine/events/responses_continuation_test.py
```

A second focused materialization and execution run passed with 52 tests after adding retry-safe idempotent admission and compensation coverage.

Ruff and Pyright passed for the changed backend files. The relevant Pyright runs reported zero errors.

### Web presentation

The web formatter, linter, and type checker passed. The production build also passed:

```console
cd typescript
pnpm run build --filter=@azents/web
```

The build completed compilation, TypeScript checking, static page generation, and final page optimization successfully. Client generation produced no tracked diff.

### Deterministic proxy and E2E support

The proxy was validated directly against `AsyncOpenAI`. The SDK parsed the expected Responses stream lifecycle:

1. `response.created`
2. `response.output_item.added`
3. `response.image_generation_call.in_progress`
4. `response.image_generation_call.generating`
5. `response.image_generation_call.completed`
6. `response.output_item.done`
7. `response.completed`

A separate timing test verified that proxy passthrough preserves upstream SSE delivery rather than buffering the complete response. Three upstream events emitted 250 milliseconds apart arrived through the proxy at approximately 0, 250, and 500 milliseconds.

Ruff formatting, Ruff lint, Pyright, and Python bytecode compilation passed for the changed E2E support and test files.

The focused product E2E command is:

```console
cd testenv/azents/e2e
uv run pytest -vv -s src/tests/azents/public/test_provider_image_generation.py
```

Local execution reached test setup but could not start Testcontainers because the Docker Unix socket is unavailable. This is an environment limitation, not a test assertion failure. The deterministic E2E remains mandatory in pull-request CI, where Docker is available.

## Runtime Coverage Matrix

| Runtime path | Capability and lowering | Output normalization | Materialization | Native replay | Cross-adapter replay | Product E2E |
| --- | --- | --- | --- | --- | --- | --- |
| OpenAI SDK | Passed | Passed | Shared path passed | Passed | Passed | Deterministic test added |
| ChatGPT OAuth | Passed | Shared OpenAI path passed | Shared path passed | Passed with `store=false` | Passed | Covered by focused adapter tests |
| LiteLLM | Passed | Passed | Shared path passed | Passed | Passed | Covered by focused adapter tests |

The product E2E uses the OpenAI Responses transport because ChatGPT OAuth and non-OpenAI LiteLLM providers require provider-specific credentials and endpoints. Their dialect-specific request and replay contracts are exercised in deterministic focused tests, while all three paths converge on the same provider-neutral materialization and durable event path.

## Product-Path Assertions

The deterministic E2E verifies that:

- `image_generation` is sent as a provider-hosted tool;
- running and completed live activity are streamed;
- Base64 is absent from WebSocket actions and durable history;
- exactly one provider result contains one ModelFile-backed `FileOutputPart` and one available Exchange attachment;
- the downloaded attachment bytes and SHA-256 match the committed fixture;
- a later compatible model request rehydrates the native image-generation result from request-local ModelFile storage;
- rehydrated Base64 remains absent from the final durable history;
- retry-safe materialization reuses deterministic metadata and never deletes already admitted objects.

## Implementation and Spec Comparison

| Area | Implemented behavior | Current spec before promotion | Action |
| --- | --- | --- | --- |
| Builtin registry | `web_search` and `image_generation` are implemented configurable builtins | Registry says only `web_search` | Update Agent and model catalog specs |
| Capability projection | Trusted OpenAI-family capability sources advertise `image_generation` | Projection says image generation is filtered out | Update model catalog spec |
| Request lowering | OpenAI SDK, ChatGPT OAuth, and LiteLLM lower provider-specific image-generation syntax | Not documented as supported | Update execution-loop and Agent specs |
| Durable output | Original Exchange attachment plus normalized ModelFile, without Base64 | Provider-generated dual materialization is not documented | Update conversation and file-exchange specs |
| Replay | Request-local native rehydration or cross-adapter rich-image/placeholder fallback | Not documented | Update conversation and execution-loop specs |
| UI | Provider tool card directly renders available image attachments | Generic attachment behavior only | Update conversation spec if presentation details are normative |

No implementation gap was found in the shared runtime/materialization/replay contract. The remaining drift is documentation promotion plus CI execution of the Docker-dependent deterministic E2E.

## Validation Findings Fixed

1. The first proxy implementation buffered forwarded responses. It now streams upstream chunks immediately, preserving watchdog and delayed-stream E2E semantics.
2. Deterministic materialization identities were not idempotent at metadata admission, and failed duplicate admission could delete objects referenced by an earlier successful attempt. Admission now reuses matching metadata, rejects identity collisions, and protects keys owned by committed metadata during compensation.
3. Raw request prompt matching now accepts both string content and structured `input_text` content.

## Remaining CI Evidence

The validation pull request must pass the repository CI matrix, including deterministic Python E2E. If CI exposes a feature-related failure, the validation branch will be updated before spec promotion. An unrelated intermittent E2E failure is not treated as feature evidence without reproduction or a causal link.
