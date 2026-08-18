---
title: "xAI Integration Model Discovery"
created: 2026-08-18
tags: [xai, model-catalog, integration, architecture]
document_role: primary
document_type: adr
snapshot_id: xai-260818
---

# xAI Integration Model Discovery

- Snapshot: `xai-260818`
- Requirements: [xai-260818/REQ](../requirements/xai-260818-integration-model-discovery.md)

## Context

The current xAI API-key and OAuth pickers use separate system catalogs projected from the same LiteLLM provider family. This contradicts `xai-260818/REQ-1` because credential products and individual accounts may expose different model sets. It also makes LiteLLM metadata an unintended availability gate, contrary to `xai-260818/REQ-2`.

## Decisions

### xai-260818/ADR-D1 — Integration catalogs own xAI model visibility

`xai` and `xai_oauth` move from system-owned catalogs to integration-scoped catalogs. Existing integration-catalog creation, sync policy, stored read, failure preservation, and explicit retry behavior remain authoritative.

**Alternatives rejected**

- Keep separate xAI system catalogs: they still cannot represent credential-specific visibility.
- Add request-time listing fallback: it would make picker reads depend on provider availability and bypass stored synchronization state.

**Consequences**

- Existing xAI integrations require catalog backfill.
- xAI system catalogs and admin system-catalog operations become obsolete.

### xai-260818/ADR-D2 — xAI listing owns existence; LiteLLM is optional enrichment

Every valid model returned by xAI is selectable. Exact LiteLLM metadata, including expanded aliases, may enrich fields absent from the provider response but cannot remove the model or override provider-supplied values.

**Alternatives rejected**

- Require a LiteLLM match: upstream metadata lag would continue to hide available models.
- Ignore LiteLLM entirely: the API-key response and some OAuth entries may omit useful verified capability information.

**Consequences**

- Capability projection must distinguish provider-present fields from absent fields.
- Missing metadata becomes diagnostic state, not hidden visibility.

### xai-260818/ADR-D3 — Use each credential product's supported discovery boundary

The API-key provider uses the existing OpenAI-compatible SDK model-list operation against xAI's configured developer API base. The OAuth provider uses the authenticated Grok CLI proxy model endpoint because developer API SDKs do not implement the Grok OAuth account protocol. The OAuth direct-HTTP exception is limited to this unsupported SDK boundary and reuses the pinned, credential-safe CLI request identity already used for xAI subscription usage.

**Alternatives rejected**

- Add the official xAI SDK: its current protobuf constraint conflicts with the runtime-control protobuf version required by Azents.
- Send Grok OAuth tokens through the developer API endpoint: OAuth account entitlement and the verified account-visible response contract are exposed by the CLI proxy instead.
- Hand-write both calls: the installed OpenAI-compatible SDK already owns API-key authentication and model listing.

**Consequences**

- No new dependency is required for API-key discovery.
- The OAuth wire contract remains explicitly typed, tested, and version-pinned.

### xai-260818/ADR-D4 — Preserve existing failure and refresh lifecycle

OAuth tokens are refreshed through the current persistence service before listing. Provider `401` and `403` responses block automatic retry; `429`, transport, `5xx`, and invalid response failures remain retryable. Failed attempts retain the last successful catalog.

**Alternatives rejected**

- Add xAI-only scheduling or retry policy: the existing integration-catalog policy already covers the required lifecycle.
- Treat OAuth refresh success as entitlement proof: a refreshable credential may still lack inference entitlement.

## Acceptance

Accepted by the requester on 2026-08-18 through issue #1317 and the instruction to follow the existing integration-catalog pattern without additional design decisions.
