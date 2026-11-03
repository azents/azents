---
title: "Request capabilities and built-in tools"
created: 2026-11-04
tags: [wiki]
---

# Request capabilities and built-in tools

Owns admission of configured semantic built-ins and the split between provider-hosted and Azents-executed capabilities. Tool connection discovery is a separate concern.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Model selection and operation snapshots](selection.md)
- [Model catalog](../domain/model-catalog.md)
- [Tool discovery and working sets](../tools/discovery.md)
- [File exchange and storage](../flow/file-exchange-storage.md)
- [Agent](../domain/agent.md)

## Built-in Tool Validation

Configuration and settings-copy validation use final supported-tool membership.
They do not remove a conditional tool by evaluating an incomplete runtime request.
Actual request admission evaluates captured conditions with the complete encoded
effort and JSON-function declarations; support, strict schemas and structured
responses remain separate.

Each selectable model option owns a semantic built-in tool opt-in list. Model snapshot `normalized_capabilities.built_in_tools.supported` means the capability is selectable; it does not prescribe whether the provider or Azents executes it. A supported tool omitted from that option's settings is not exposed when the option is selected.

The configurable implemented registry contains `web_search` and `image_generation`. Capability projection filters out unimplemented identifiers such as `web_fetch`. Agent and Workspace submit normalization rejects unknown, duplicate, or capability-unsupported names per option. `image_generation` uses the same model-scoped validation contract as other builtins and does not restore historical provider-specific Agent validation conditions.

Runtime passes the selected Session settings as `BuiltinToolSpec(name, config)` and resolves every selected semantic capability to one execution owner before provider dispatch. `web_search` remains provider-hosted. OpenAI API-key and ChatGPT OAuth `image_generation` become an auto-bound unprefixed client function backed by the selected integration's Images SDK endpoint; xAI API-key and xAI OAuth use an auto-bound client function backed by Imagine. An advertised `image_generation` capability for another provider remains provider-hosted. OpenAI and ChatGPT capability projection includes supported function-capable chat models even when provider metadata does not advertise a hosted image tool; other providers require their trusted capability metadata or implemented fallback policy. Only the provider-hosted partition reaches the request lowerer. A capability missing from the selected snapshot, unimplemented by the resolver, or lacking its required client binding fails before provider dispatch; no configured builtin is silently omitted or exposed through both execution paths.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/core/model_provider_declarations.py`](../../../../python/apps/azents/src/azents/core/model_provider_declarations.py)
- [`python/apps/azents/src/azents/engine/events`](../../../../python/apps/azents/src/azents/engine/events)
- [`python/apps/azents/src/azents/engine/tools`](../../../../python/apps/azents/src/azents/engine/tools)
