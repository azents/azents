---
title: "xAI Integration Model Discovery Requirements"
created: 2026-08-18
updated: 2026-08-18
implemented: 2026-08-18
tags: [xai, model-catalog, integration, backend]
document_role: primary
document_type: requirements
snapshot_id: xai-260818
---

# xAI Integration Model Discovery Requirements

- Snapshot: `xai-260818`
- Document reference: `xai-260818/REQ`

## Problem

The `xai` API-key and `xai_oauth` integrations currently use separate credentials but share globally projected model visibility from LiteLLM metadata. The picker can therefore omit models available to an authenticated integration, expose models that integration cannot use, and incorrectly assume API-key and OAuth products have identical model sets.

## Primary Actor

A workspace member selecting a model for an enabled xAI provider integration.

## Primary Scenario

After an xAI API-key integration is created or an xAI OAuth connection succeeds, Azents synchronizes the models visible to that exact credential. The model picker then shows the last successfully synchronized integration-specific model set and retains that set if a later refresh fails.

## Supporting Scenarios

- An xAI OAuth access token is refreshed before discovery when it is near expiry.
- An explicitly requested refresh retries after a credential or entitlement failure.
- API-key and OAuth integrations in the same workspace may expose different models.
- A provider-visible model remains selectable when optional LiteLLM metadata is missing.

## Goals

- Make authenticated xAI model visibility integration-specific.
- Preserve provider-returned models independently of LiteLLM catalog completeness.
- Keep capability claims conservative while using trusted metadata enrichment when available.
- Preserve the existing integration-catalog synchronization lifecycle and last-successful-snapshot behavior.

## Non-Goals

- Validate credentials synchronously during integration CRUD.
- Make picker reads call xAI directly.
- Merge the API-key and OAuth provider identities or credential lifecycles.
- Guarantee runtime entitlement after the latest successful catalog snapshot.
- Add new model execution transports or provider tools.

## Requirements

### REQ-1. Credential-scoped model visibility

Each enabled `xai` and `xai_oauth` integration must have a model catalog derived from the models visible to its own credential.

**Acceptance criteria**

- API-key and OAuth integrations can persist different model sets.
- Picker reads return the stored catalog for the selected integration and do not fall back to an xAI system catalog.

### REQ-2. Provider-authoritative model existence

A model returned by the authenticated xAI listing must remain eligible for selection even when optional enrichment metadata has no matching entry.

**Acceptance criteria**

- Missing enrichment metadata does not hide or remove a provider-listed model.
- Unverified capabilities remain disabled rather than inferred optimistically.
- Metadata misses are recorded only in credential-safe diagnostics.

### REQ-3. Trusted capability projection

Provider-returned capabilities must take precedence, and trusted LiteLLM metadata may fill only capability fields absent from the xAI response.

**Acceptance criteria**

- Provider context-window, reasoning, backend-search, and protocol information is retained when supplied.
- LiteLLM enrichment never overrides conflicting provider-supplied values.

### REQ-4. OAuth freshness

xAI OAuth discovery must use the existing persisted token refresh lifecycle before contacting the model-list endpoint.

**Acceptance criteria**

- A near-expiry token is refreshed before listing.
- Permanent refresh failures block automatic retry until explicit retry or integration update; transient refresh failures remain retryable.

### REQ-5. Failure safety

Discovery failures must preserve the last successful catalog and expose only bounded, credential-safe failure state.

**Acceptance criteria**

- `401` and `403` failures are treated as credential, reconnect, or entitlement failures that block automatic retry.
- `429`, transport failures, provider `5xx`, and invalid provider responses remain retryable after backoff.
- Credentials, authorization headers, account claims, tokens, and raw provider bodies do not appear in diagnostics or public responses.

### REQ-6. Existing synchronization lifecycle

xAI integration catalogs must participate in the existing creation, credential/configuration update, re-enable, stale refresh, backoff, cooldown, and explicit retry behavior.

**Acceptance criteria**

- Initial and configuration-change synchronization is queued for enabled integrations.
- Failed synchronization does not replace an existing successful snapshot.
- Existing integrations receive an integration catalog during migration.

## Fixed Constraints

- `xai` and `xai_oauth` remain distinct provider identities.
- Normal model picker reads use stored projections only.
- Provider credentials remain encrypted and are never persisted in catalog metadata.
- Runtime model identifiers retain the existing `xai/` LiteLLM routing prefix.

## Open Assumptions

- The authenticated xAI model-list endpoints remain compatible with the currently verified response contracts.
- LiteLLM model metadata remains optional enrichment rather than availability authority.

## Confirmation

Confirmed by the requester on 2026-08-18 through GitHub issue #1317 and the instruction to implement the existing integration-catalog pattern without additional decision waiting.
