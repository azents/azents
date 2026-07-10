---
title: "xAI API Key Provider"
created: 2026-07-10
updated: 2026-07-10
tags: [backend, frontend, engine, security, api, testenv]
---

# xAI API Key Provider

## Problem

Azents supports xAI through an experimental user-authorized OAuth integration, but it does not expose the standard xAI developer API-key integration. Users with an xAI API key cannot create a stable, developer-billed provider integration even though the existing LiteLLM Responses path can invoke current Grok models successfully.

The API-key and OAuth products must remain separate. They use the same xAI inference protocol and model family, but differ in credentials, billing, entitlement, refresh lifecycle, and setup UX.

## Goals

- Add a stable workspace-scoped xAI API-key provider.
- Store the API key only in encrypted `LLMProviderIntegration` secrets.
- Reuse the validated xAI Responses API, system-instruction, tool, and model-catalog paths.
- Allow xAI API-key and xAI OAuth integrations to coexist in one workspace.
- Present a clear UI distinction between developer API billing and experimental account OAuth.
- Keep provider behavior capability-oriented so future providers can reuse the same transport policies.

## Non-goals

- Replace, merge, or stabilize the xAI OAuth provider.
- Validate API keys or fetch models from xAI during integration CRUD.
- Add xAI image, video, audio, X search, or code execution tools.
- Add provider-specific retry behavior in this feature.
- Correct historical LiteLLM reasoning-effort metadata for every legacy Grok model.
- Introduce a generic provider plugin framework.

## Current Behavior

`LLMProvider.XAI_OAUTH` stores refreshable OAuth tokens, uses the LiteLLM `xai/` runtime prefix, projects the xAI LiteLLM family into a system catalog, and routes calls to `https://api.x.ai/v1/responses`. xAI does not accept the OpenAI Responses top-level `instructions` field, so Azents places system instructions in the first `system` input item. Provider-hosted web search is already lowered to xAI's Responses tool shape.

API-key providers reuse `ApiKeySecrets`, require no plaintext config, and are created through the generic LLM provider integration CRUD API. Their secrets are encrypted by the repository and omitted from all public responses. OpenAI, Anthropic, and Google Gemini currently use this pattern.

## Decision Points

### Provider Identity

**Options**

- Reuse `xai_oauth` for both credential types.
- Add `LLMProvider.XAI = "xai"` as a separate provider.

**Decision**: Add `xai`. OAuth and API-key credentials have different billing and lifecycle semantics, and the current xAI OAuth spec already reserves a separate future API-key provider.

### Credential Contract

**Options**

- Define an xAI-specific API-key secret type.
- Reuse the existing discriminated `ApiKeySecrets` contract.

**Decision**: Reuse `ApiKeySecrets(type="api_key")` with no provider config. The encryption, create/update semantics, blank-key edit behavior, and response redaction are identical to existing API-key providers.

### Model Catalog Scope

**Options**

- Fetch `/v1/models` using each integration key and create an integration-scoped catalog.
- Project the existing LiteLLM `xai` source into a provider-specific system catalog.

**Decision**: Use a system catalog for v1, matching xAI OAuth and current OpenAI/Anthropic/Gemini behavior. Normal picker reads remain credential-free and deterministic. API-key validation and account-scoped model discovery can be added later as a separate contract if xAI access becomes meaningfully key-specific.

The `xai` and `xai_oauth` system catalogs are separate stored catalogs even though both project the same LiteLLM provider family. Provider-facing identifiers strip the `xai/` prefix; runtime identifiers restore it.

### Runtime Endpoint Configuration

**Options**

- Rely only on LiteLLM's model-prefix defaults.
- Explicitly normalize xAI provider routing and the official API base.

**Decision**: Normalize xAI API-key calls to `custom_llm_provider="xai"` and `https://api.x.ai/v1`, matching the OAuth inference path while omitting all OAuth refresh behavior. The API key is passed as `api_key` only after decryption at run resolution.

### Integration Validation

**Options**

- Call xAI during create/update to validate the key.
- Persist credentials without a provider call, like existing API-key providers.

**Decision**: Do not call xAI during CRUD. This avoids turning temporary provider/network failures into configuration failures and preserves consistent API-key provider semantics. Authentication errors surface on model calls. Optional live verification remains a separate test path.

### UI Presentation

**Decision**: Show both provider options when reported by the capability API:

- `xai`: **xAI API key**, stable, generic API-key form.
- `xai_oauth`: **xAI Grok OAuth**, experimental, existing device authorization card.

The API-key setup copy states that xAI developer API billing is separate from SuperGrok or X Premium. Stored keys are never redisplayed.

## Proposed Design

### Provider and Database Contract

Add `xai` to the `LLMProvider` enum and PostgreSQL `llm_provider` enum using a new generated Alembic revision. No existing migration is modified and no row backfill is required.

Map `xai` to:

- secret type: `api_key`
- config: none
- LiteLLM provider/model prefix: `xai/`
- model developer: `xai`
- system catalog source family: `xai`
- public display name: `xAI API key`
- experimental: `false`

### Public API

The existing integration CRUD and provider capability endpoints remain unchanged in shape. The additive enum value appears in OpenAPI and generated clients. A create request uses:

```json
{
  "provider": "xai",
  "name": "xAI API key",
  "secrets": {
    "type": "api_key",
    "api_key": "..."
  },
  "config": null,
  "enabled": true
}
```

Responses include provider, alias, enabled state, and timestamps, but never the API key.

### Runtime

Run resolution does not invoke xAI OAuth refresh for `provider=xai`. It decrypts `ApiKeySecrets` and builds the xAI Responses transport kwargs. The lowerer applies provider capabilities shared by both xAI credential modes:

- system instructions are the first `system` input item;
- top-level `instructions` is omitted;
- provider-hosted `web_search` uses xAI's tool target;
- Anthropic cache-control hints are not applied;
- the runtime model identifier uses the `xai/` prefix.

Current model catalog capabilities continue to decide whether model parameters and hosted tools are selectable. Legacy model reasoning-effort metadata correction is tracked outside this feature; current supported Grok models are the rollout target.

### Frontend

The existing `ApiKeyForm` handles create and edit. Provider lists, labels, badge rendering, and all supported locales add the `xai` value. The xAI OAuth card is unchanged. The backend capability response remains the authority for which options are available.

### Security and Permissions

- Existing workspace LLM integration permissions govern create, update, list, and delete.
- API keys are accepted only in request bodies, encrypted before persistence, and omitted from response models and logs.
- Editing an alias or enabled state does not require re-entering the API key.
- No key is sent to xAI until a run invokes a model.
- Deterministic tests use fake keys and never contact xAI.

## Error Handling

Existing user-visible provider error normalization applies to `401`, `403`, `429`, and `5xx` responses:

- `401`: invalid or revoked API key.
- `403`: xAI account or permission failure; it is not treated as OAuth token expiry.
- `429`: quota or rate limit.
- `5xx`: provider failure.

Provider `400` responses, including model or parameter incompatibility, currently follow the internal model-call failure path. Changing generic `400` normalization is outside this feature. CRUD errors remain Azents validation/permission errors because CRUD does not contact xAI.

## Rollout and Migration

1. Apply the additive PostgreSQL enum migration before application instances create `provider=xai` rows.
2. Deploy backend/API/client and frontend support.
3. Refresh the `xai` system catalog through existing admin/periodic catalog infrastructure.
4. Users create xAI API-key integrations and select current visible Grok models.
5. Keep xAI OAuth available independently.

Rollback may hide `xai` from the provider capability list and disable affected integrations. The PostgreSQL enum value remains harmless and is not removed during rollback.

## Test Strategy

### E2E Primary Matrix

| Scenario | Expected result | Execution |
|---|---|---|
| Provider discovery | Capability API exposes stable `xai` with `api_key` and experimental `xai_oauth` separately | Deterministic API E2E |
| Create API-key integration | Owner creates `xai` integration with fake key; response omits the secret | Deterministic API E2E |
| Edit without key | Alias/enabled update preserves encrypted credential | Deterministic API E2E or backend integration test |
| Coexistence | Workspace lists independent `xai` and `xai_oauth` records | Deterministic API/backend test |
| Model picker | xAI API-key integration reads the xAI system catalog and stores an `xai/` runtime selection | Deterministic catalog/API test |
| Runtime lowering | Mocked call contains system input message, xAI routing, and optional web search without top-level instructions | Backend adapter test |
| Live model call | Current Grok model returns a response using an operator-provided key | Optional live external test |
| Read-only member | Non-owner cannot create/update/delete the integration | Existing permission E2E coverage plus provider enum regression |

### Fixture and Prerequisite Support

Deterministic CI needs no new external fixture: existing provider integration API tests can use a fake xAI key, and runtime tests mock LiteLLM/xAI transport. If a live smoke test is added, the testenv credential check recognizes `XAI_API_KEY` only as present or missing and never records its value. Live evidence contains model identifier, terminal status, and redacted error classification only.

### CI and Skip/Fail Policy

- Backend enum, credential, CRUD, catalog, runtime mapping, and lowerer tests run in normal CI.
- OpenAPI generation and Python/TypeScript generated-client checks run in normal CI.
- Frontend format, lint, typecheck, build, and component/story coverage run in normal CI.
- Deterministic E2E uses fake credentials and must pass.
- Optional live verification skips when `XAI_API_KEY` is absent in scheduled exploratory runs. When a maintainer explicitly requests live verification, a missing key or failed current-model call is a failure.

## Alternatives Rejected

- **Reuse xAI OAuth integration**: conflates developer billing with subscription entitlement and refresh state.
- **Add an xAI-specific API-key schema**: duplicates the existing encrypted API-key contract without additional semantics.
- **User-scoped `/models` catalog in v1**: adds remote availability and credential failure handling to normal setup without demonstrated product need.
- **Validate keys during create**: inconsistent with existing API-key providers and vulnerable to temporary provider outages.
- **Hard-code a default Grok model**: model selection belongs to the stored catalog projection.

## Risks and Follow-ups

- LiteLLM source metadata can lag xAI model availability or overstate model-parameter capabilities. Operators should refresh source/catalog snapshots and prefer current visible models.
- A later design may add credential validation and integration-scoped `/models` discovery if xAI accounts expose materially different model sets.
- Legacy Grok reasoning-effort compatibility should be hardened through model capability projection, not provider-name checks in this feature.

## ADR Assessment

No new ADR is required. The separate API-key/OAuth identity and encrypted generic API-key storage follow established provider contracts and are already anticipated by the current xAI OAuth living spec. This design records the feature-specific choices; current behavior will be promoted into the provider and model-catalog specs after validation.
