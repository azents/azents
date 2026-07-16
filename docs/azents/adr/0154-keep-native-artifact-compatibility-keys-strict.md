---
title: "ADR-0154: Keep Native Artifact Compatibility Keys Strict"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, compatibility]
---

# ADR-0154: Keep Native Artifact Compatibility Keys Strict

## Status

Accepted. Implementation has not started.

## Context

Azents stores adapter-native output items as opaque `NativeArtifact` data. Replay is allowed only when the artifact compatibility key matches the target lowerer:

```text
adapter:native_format:provider:model:schema_version
```

The Phase 1 OpenAI migration replaces the LiteLLM transport and adapter for OpenAI API-key and ChatGPT OAuth Responses HTTP calls. Existing artifacts therefore have `litellm:responses:...` keys while newly produced artifacts will have `openai:responses:...` keys.

The migration could add a cross-adapter exception that lets the OpenAI lowerer consume old LiteLLM Responses artifacts. That would preserve more provider-native historical context, including reasoning items that canonical fallback lowering intentionally does not replay. However, it would weaken the purpose of the compatibility key by treating independently owned adapter schemas as interchangeable without an explicit data migration.

## Decision

Native artifact compatibility remains exact key equality. The OpenAI Responses lowerer accepts only artifacts whose full compatibility key matches its own `openai:responses:{provider}:{model}:{schema_version}` key.

The migration does not add accepted-key sets, adapter aliases, LiteLLM-specific read fallbacks, or structural exceptions for artifacts with `litellm:responses:...` keys. A mismatched artifact follows the existing canonical fallback lowering contract.

Existing artifacts are not rewritten or backfilled. The durable canonical event remains available, but adapter-native fields that have no canonical replay representation are not carried into the new adapter request. In particular, cross-adapter reasoning artifacts remain visible for UI and audit purposes but are not replayed as model input.

Semantic parity for the new OpenAI SDK path applies within its own native compatibility boundary. It does not redefine native replay as compatible across the old LiteLLM and new OpenAI adapter identities.

## Consequences

- The compatibility key continues to be an enforceable schema and ownership boundary rather than advisory metadata.
- Existing OpenAI and ChatGPT OAuth conversations use canonical fallback lowering for artifacts produced by the LiteLLM adapter.
- Historical provider-native fields without a canonical lowering may be omitted after migration; this is an accepted consequence of changing adapter compatibility identity.
- New OpenAI SDK artifacts replay only when provider, model, native format, schema version, and adapter identity all match.
- No database migration, artifact rewrite, or permanent legacy read path is required.
- Tests must verify that a LiteLLM-keyed artifact is rejected by the OpenAI lowerer even when its payload resembles a valid Responses item.

## Alternatives Considered

### Accept old LiteLLM Responses artifacts in the OpenAI lowerer

Rejected because it would bypass the adapter component of the compatibility key and create an implicit cross-adapter schema contract.

### Rewrite stored LiteLLM artifact keys or payloads

Rejected because payload resemblance does not prove schema equivalence, and a rewrite would incorrectly assert that old artifacts were produced under the new adapter contract.
