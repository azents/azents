---
title: "ADR-0166: Resolve built-in capabilities to model-specific executors"
created: 2026-07-18
tags: [architecture, backend, engine, llm, tools]
---

# ADR-0166: Resolve built-in capabilities to model-specific executors

## Context

Azents exposes model-scoped built-in capabilities such as `web_search` and
`image_generation`. The existing runtime contract treats every selected built-in as a
provider-hosted tool and passes it directly to the provider request lowerer.

That assumption does not hold for every provider. OpenAI and ChatGPT models can execute
`image_generation` as a provider-hosted Responses tool. Grok language models support
function calling, while image creation is provided through the separate xAI Imagine API.
Azents can therefore provide the same user-visible capability to Grok by exposing a
client-executed function tool that calls Imagine with the selected xAI integration.

The xAI language-model catalog and the LiteLLM model metadata used by Azents do not
publish a language-model-to-Imagine capability relation. They do publish whether a
language model supports function calling. Maintaining a Grok model identifier allowlist
would require an Azents release for each new model and alias.

## Decision

`normalized_capabilities.built_in_tools.supported` represents effective capabilities of
a selectable model option. A capability may be implemented by the provider or by an
Azents client executor.

Azents resolves each selected built-in capability to an execution strategy before model
request lowering:

- OpenAI API-key and ChatGPT OAuth `image_generation` use a provider-hosted tool.
- xAI API-key and xAI OAuth `image_generation` use an Azents client function tool backed
  by the xAI Imagine API.
- Unsupported provider and capability combinations fail before provider dispatch.

The Agent and Workspace configuration contract remains one semantic flag:
`image_generation`. Execution strategy is internal runtime state and is not persisted in
Agent configuration.

Azents projects `image_generation` for selectable xAI and xAI OAuth chat models that
support function calling. It does not maintain an individual Grok model identifier
allowlist. Account credentials, quota, and subscription entitlement remain runtime
concerns rather than model capability metadata.

Both xAI credential modes are supported in the first implementation:

- xAI API-key requests use the selected integration API key.
- xAI OAuth requests use the selected integration access token after the existing
  proactive refresh flow.
- An Imagine `401` for OAuth forces one token refresh and one request retry.
- A second `401` requires reconnection. `403` is treated as an entitlement or permission
  failure and is not retried as authentication refresh.

Credentials remain backend-only. They are not included in tool schemas, tool arguments,
events, logs, runtime workspace state, or generated file metadata.

Provider-hosted and client-executed implementations keep their native event ownership:
provider tool events for provider-hosted execution and client tool events for
Azents-executed work. They converge on the same user-observable generated-image contract:
an Exchange attachment for presentation and a ModelFile-backed file part for subsequent
model input.

## Consequences

- Model capability projection must be separated from provider-hosted tool policy.
- Runtime preparation must partition selected semantic built-ins into provider-hosted
  specifications and client-executed bindings.
- The provider request lowerer continues to receive only provider-hosted tools.
- Generated-image validation and dual materialization must become reusable by both
  provider output admission and the Imagine client tool.
- xAI OAuth failures can surface after capability selection when an account lacks Imagine
  entitlement. This is an explicit runtime failure, not a reason to hide the model-level
  capability.
- New providers can implement the same semantic capability without changing the Agent
  configuration or frontend contract.

## Alternatives considered

### Keep built-ins provider-hosted only

Rejected because it would require a second user-facing setting for Grok image generation
and would make equivalent capabilities differ by provider in the Agent configuration.

### Add a Grok-specific `imagine` toolkit setting

Rejected because users select an image-generation capability, not an implementation
vendor. It would also couple Agent configuration to the currently selected provider.

### Maintain a Grok model identifier allowlist

Rejected because function calling is the relevant language-model requirement. An
identifier allowlist would drift as xAI adds aliases and new models.

### Treat generated images as identical event kinds

Rejected because provider-hosted work and Azents client execution have different retry,
cancellation, and recovery ownership. Only their generated-file result contract is
shared.
