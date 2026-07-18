---
title: "Model-Specific Image Generation Execution"
created: 2026-07-18
implemented: 2026-07-18
tags: [backend, engine, frontend, llm, storage, tools, security, testenv]
---

# Model-Specific Image Generation Execution

## Problem

Azents currently models `image_generation` as a model-scoped configurable built-in, but
the runtime assumes every selected built-in is provider-hosted. This works for OpenAI
Responses image generation. It does not provide an equivalent capability when the
selected language model is Grok, because xAI exposes image generation through the
separate Imagine API rather than as a hosted tool executed inside the Grok language-model
request.

A user should enable one `image_generation` capability and receive image generation from
any supported model option. The implementation detail must follow the selected provider:
provider-hosted for OpenAI-family models and Azents client-executed for xAI models.

xAI API-key and xAI OAuth integrations must both work in the first release. Credentials
must remain backend-only, generated image bytes must not enter durable event payloads, and
the result must remain available both to the user and to later model calls.

## Goals

- Keep one model-scoped `image_generation` setting in the Agent and Workspace contracts.
- Treat normalized built-in capability as effective product behavior rather than only a
  provider-hosted feature.
- Continue using provider-hosted image generation for supported OpenAI API-key and
  ChatGPT OAuth model options.
- Provide an `image_generation` client function tool for xAI API-key and xAI OAuth model
  options.
- Reuse the selected xAI integration for Grok and Imagine requests without exposing its
  credential to the model or runtime workspace.
- Support proactive OAuth refresh and one forced refresh retry after an Imagine `401`.
- Produce the existing durable generated-image result: Exchange attachment plus
  ModelFile-backed `FileOutputPart` without durable Base64.
- Preserve deterministic tool catalogs and explicit unsupported-capability failures.

## Non-goals

- Adding image editing, image-to-video, or video generation.
- Adding a separate user-selectable Imagine toolkit or image-provider selector.
- Making provider-hosted and client-executed calls share one event kind.
- Discovering account subscription entitlement during every catalog projection.
- Persisting xAI temporary image URLs or xAI Files API identities.
- Adding a Grok model identifier allowlist.
- Changing existing OpenAI generated-image behavior or replay semantics.

## Current behavior

### Model capability projection

System xAI API-key and xAI OAuth catalogs are projected from the same LiteLLM `xai/*`
source entries. Current Grok metadata includes chat mode and function-calling support but
does not include `image_generation`. `supported_provider_hosted_tools()` constructs the
built-in capability list and currently returns image generation only for trusted
OpenAI-family policy or explicit source metadata.

### Runtime built-in lowering

Agent model settings are converted to `BuiltinToolSpec` values and stored on
`RunRequest.builtin_tools`. `EventEngineAdapter` passes every value as `hosted_tools` to
the Responses lowerer. The lowerer emits native `{"type": "image_generation"}` syntax for
selected image generation.

### Generated image storage

Completed provider-hosted image generation is validated and materialized into two
independent resources:

1. an Exchange file and preview for user presentation;
2. a ModelFile and `FileOutputPart` for later model input.

Raw Base64 and provider-native result bytes are excluded from durable events.

### xAI credentials

xAI API-key integrations use encrypted `ApiKeySecrets`. xAI OAuth integrations use
encrypted access and refresh tokens. Before a run, OAuth access tokens within one hour of
expiry are refreshed and persisted. Both credential modes are normalized to an xAI Bearer
credential for the selected model request.

## External API contract

The client executor calls:

```text
POST https://api.x.ai/v1/images/generations
Authorization: Bearer <selected xAI integration credential>
Content-Type: application/json
```

The request uses the documented public image model by default:

```json
{
  "model": "grok-imagine-image",
  "prompt": "...",
  "n": 1,
  "aspect_ratio": "auto",
  "resolution": "1k",
  "response_format": "b64_json"
}
```

The model identifier is an internal configurable default, not an Agent setting. Base64 is
requested so Azents validates bytes directly and does not fetch an untrusted or expiring
remote URL. A bounded URL-download fallback may be implemented only if a documented xAI
response omits Base64, and must enforce HTTPS, an xAI-owned host allowlist, redirect
limits, byte limits, timeouts, and media validation.

## Proposed design

### 1. Generalize capability projection

Rename the policy boundary from provider-hosted tool support to effective built-in
capability support. The policy evaluates normalized source metadata and Azents-owned
provider rules.

For `image_generation`:

- preserve explicit trusted metadata overrides;
- preserve existing OpenAI and ChatGPT support policy;
- add support for `LLMProvider.XAI` and `LLMProvider.XAI_OAUTH` when the source entry is a
  selectable chat model and `supports_function_calling` is true;
- do not inspect model identifiers such as `grok-4.5`.

Both xAI catalogs receive the same capability because API-key and OAuth are credential
modes for the same effective product feature. Invalid credentials and account entitlement
are runtime failures.

### 2. Resolve selected capabilities to implementations

Introduce a runtime resolver that consumes:

- selected semantic `BuiltinToolSpec` values;
- provider and model developer;
- normalized model capabilities;
- selected provider integration identity and credential mode.

It produces two deterministic collections:

- provider-hosted built-in specs for the request lowerer;
- client built-in implementation specs for auto-bound tool construction.

Resolution table:

| Semantic capability | Provider | Implementation |
| --- | --- | --- |
| `image_generation` | OpenAI API key | provider-hosted |
| `image_generation` | ChatGPT OAuth | provider-hosted |
| `image_generation` | xAI API key | client Imagine tool |
| `image_generation` | xAI OAuth | client Imagine tool |
| `image_generation` | other | unsupported |

Every selected capability must resolve exactly once. Missing and duplicate
implementations fail before provider dispatch. The provider lowerer never sees xAI client
image generation as a hosted tool.

### 3. Auto-bind the xAI image-generation tool

The worker constructs a non-user-configurable, unprefixed toolkit binding for resolved
xAI image generation. The tool appears to the model as `image_generation` and is included
in the normal deterministic client tool catalog.

Input schema:

- `prompt`: required non-empty text;
- `aspect_ratio`: optional enum, default `auto`;
- `resolution`: optional enum, default `1k`.

The first implementation generates one image per call. Multiple images require multiple
tool calls, preserving ordinary client tool lifecycle and retry ownership.

The toolkit is present only when the current model option selected the capability and the
runtime resolver selected the xAI client implementation. Switching to an OpenAI model
removes this client tool and restores provider-hosted lowering without changing Agent
settings.

### 4. Keep credentials backend-only

The xAI Imagine client receives a typed credential provider, not raw tool config.

API-key mode returns the selected encrypted integration API key after runtime resolution.
OAuth mode returns the proactively refreshed access token. The selected integration ID is
retained in non-durable run context so the client can request a forced OAuth refresh after
an authentication failure.

Credentials are prohibited from:

- tool definitions and arguments;
- system and toolkit prompts;
- runtime workspace or environment variables;
- client tool events, metadata, and native artifacts;
- logs, exception messages, and generated file metadata.

### 5. OAuth retry behavior

Normal run preparation calls the existing xAI OAuth refresh service. The Imagine client
then follows this state machine:

1. send with the refreshed access token;
2. on `401`, request one forced refresh through the existing OAuth service;
3. retry once with the newly persisted access token;
4. on a second `401`, fail with reconnect-required classification.

`403` is not refreshed and reports an Imagine entitlement or permission failure. `429`
reports rate limiting. Timeouts and retryable `5xx` responses use a small bounded transport
retry policy. Cancellation propagates immediately.

The refresh service must support an explicit force operation rather than duplicating OAuth
HTTP and persistence behavior inside the Imagine client.

### 6. Share generated-image materialization

Extract the existing provider-result byte validation and dual materialization workflow
into a service callable from both provider output admission and the xAI client tool.

Input:

- validated session, agent, workspace, and actor identity;
- deterministic generation identity;
- generated bytes and provider media type;
- source label and display name.

Output:

- available Exchange attachment with optional preview;
- ModelFile-backed `FileOutputPart`;
- stable metadata required for retry-safe admission.

The xAI client tool returns structured output containing an attachment output part and a
file output part. The standard client tool result remains the execution record. No new
public event kind is introduced.

### 7. Preserve UI semantics

The existing built-in selector continues to show `Image generation`. The provider tool
card remains unchanged for OpenAI. The xAI client tool card uses the same display label
and renders the available attachment through the existing attachment output projection.

No new frontend API schema is required. Frontend coverage verifies that the client result
attachment is visible without expanding diagnostic output.

## API and data model changes

- Agent and Workspace public schemas do not change.
- `BuiltinToolConfig(name="image_generation")` remains the stored setting.
- Runtime contracts gain an explicit selected-integration identity or credential handle
  needed for forced OAuth refresh.
- Runtime contracts distinguish semantic selected built-ins from resolved provider-hosted
  and client implementations.
- No migration is required for Agent settings or catalog entries. Catalog synchronization
  recomputes xAI effective capabilities from the new policy.

## Error handling

| Failure | Behavior |
| --- | --- |
| Unsupported capability/provider pair | Fail before provider dispatch |
| Invalid API key (`401`) | Fail with invalid integration credential |
| OAuth first `401` | Force refresh and retry once |
| OAuth second `401` | Fail as reconnect required |
| `403` | Fail as Imagine permission or entitlement denied |
| `429` | Fail as provider rate limited with retry metadata when available |
| Retryable `5xx` or timeout | Bounded retry, then provider unavailable |
| Invalid or oversized image | Reject before storage |
| Exchange or ModelFile materialization failure | Fail the tool; compensate unowned objects |
| Run cancellation | Cancel HTTP and storage work immediately |

Tool failures do not masquerade as successful text output. User-facing messages remain
sanitized and never include Authorization headers or provider response bodies that may
contain secrets.

## Security and resource controls

- Use dependency-injected `httpx.AsyncClient` with connect/read/total timeouts.
- Limit prompt length before dispatch using the Imagine model limit.
- Generate one image per tool call.
- Cap response body and decoded image bytes before decoding.
- Validate media magic bytes, allowlisted raster type, pixel count, and dimensions.
- Do not follow arbitrary URLs in the default Base64 path.
- Store no raw Base64 in PostgreSQL, WebSocket payloads, logs, or native artifacts.
- Bind generated files to the current session, workspace, agent, and authenticated actor.
- Reuse existing retry-safe object admission and cleanup behavior.

## Rollout and compatibility

1. Project `image_generation` onto xAI and xAI OAuth function-calling chat models.
2. Land the implementation resolver in the same delivery stack so no catalog entry can
   advertise a silently dropped capability.
3. Enable the Imagine client tool for both credential modes immediately.
4. Preserve existing OpenAI request and replay behavior.
5. Monitor Imagine authentication, entitlement, latency, rate-limit, and materialization
   failures by credential mode without recording credentials.

There is no legacy fallback. Unsupported or unresolved implementations fail explicitly.

## Test Strategy

### E2E primary validation matrix

| Scenario | Tool exposure | Execution | Result presentation | Later model input |
| --- | --- | --- | --- | --- |
| OpenAI model with flag enabled | hosted only | provider fixture | provider attachment | ModelFile replay |
| xAI API-key model with flag enabled | client only | mocked Imagine success | client attachment | FileOutputPart replay |
| xAI OAuth model with valid token | client only | mocked Imagine success | client attachment | FileOutputPart replay |
| xAI OAuth first `401` | client only | refresh then success | one attachment | available |
| xAI OAuth second `401` | client only | failed | sanitized error | none |
| xAI model with flag disabled | absent | no request | none | none |
| non-function-calling xAI model | unavailable | validation rejection | none | none |

The deterministic E2E model emits an `image_generation` client call for xAI runs. The
Imagine HTTP boundary uses a deterministic mock transport; CI does not require external
credentials or spend.

### Backend unit and integration coverage

- effective capability projection for xAI API key and OAuth;
- no per-model identifier allowlist behavior;
- exhaustive implementation resolution and duplicate prevention;
- provider lowerer receives only hosted implementations;
- deterministic client tool catalog ordering;
- API-key and OAuth Authorization header construction without log exposure;
- proactive and forced OAuth refresh behavior;
- `401`, `403`, `429`, timeout, `5xx`, cancellation, malformed response, and oversized
  image failures;
- shared materialization success, compensation, retry idempotency, and Base64 exclusion;
- OpenAI provider-hosted regression coverage.

### Frontend coverage

- the existing selector exposes `image_generation` for xAI options;
- xAI client tool attachment renders through the existing card and file preview;
- provider-hosted rendering remains unchanged.

### Fixture and prerequisite policy

Deterministic CI fixtures are required because external xAI OAuth entitlement, quota,
latency, and cost are not stable test prerequisites. Optional live validation may use a
retained test OAuth token without printing it. Missing live credentials skip only the
optional live test; deterministic behavior remains required and failing.

## Open questions

- Whether live integration catalog synchronization should later probe
  `/v1/image-generation-models` to provide account-level diagnostics. This is not required
  for capability projection or first-release OAuth support.
- Whether image editing should become a separate semantic capability in a future design.

## Alternatives considered

### Separate Imagine toolkit setting

Rejected because it exposes implementation details and breaks model-option portability.

### Per-Grok model allowlist

Rejected because all that the language model needs is function calling. New models and
aliases would otherwise require recurring Azents releases.

### Use the xAI temporary output URL as the durable attachment

Rejected because the URL expires and bypasses Azents ownership, authorization, preview,
and lifecycle controls.

### Store xAI Files API output directly

Rejected for the first version because it creates an external durable identity and cleanup
lifecycle in addition to the existing Exchange and ModelFile contracts.

### Advertise OAuth support only after a live entitlement probe

Rejected because immediate OAuth support is a product requirement and entitlement is an
account runtime condition. Runtime failures remain explicit and recoverable.
