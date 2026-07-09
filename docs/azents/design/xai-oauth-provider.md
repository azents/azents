---
title: "xAI Grok OAuth Provider"
created: 2026-07-10
updated: 2026-07-10
tags: [backend, frontend, engine, security]
---

# xAI Grok OAuth Provider

## Problem

Azents users want to connect Grok with their own xAI account subscription instead of only using an xAI platform API key. xAI has publicly documented and announced user-authorized Grok OAuth flows in open-source agents such as Hermes and OpenCode. The subscription OAuth path is operationally different from an API key path: quota and entitlement are owned by the user's xAI account, tokens must be refreshed, and xAI may reject inference with HTTP 403 when the account is not entitled to the OAuth API surface.

## Goals

- Add an experimental xAI Grok OAuth LLM provider that connects with OAuth device authorization.
- Keep the provider separate from the future xAI API key provider.
- Store access and refresh tokens only in encrypted provider integration credentials.
- Reuse the existing Responses/LiteLLM runtime path for Grok model calls.
- Classify xAI OAuth HTTP 403 as an entitlement or allowlist failure, not as a stale-token failure.
- Gate the provider behind an operational feature flag and xAI OAuth client id configuration.

## Non-goals

- Add xAI API key provider support in this phase.
- Claim or imply an official Azents-xAI partnership.
- Reuse or hard-code another application's OAuth client identity.
- Add xAI image, video, TTS, transcription, or X search surfaces in this phase.
- Generalize all LLM OAuth providers into a shared storage abstraction in this phase.

## Current behavior

Azents supports API-key based LLM providers and ChatGPT OAuth as a separate subscription provider. ChatGPT OAuth uses a provider-specific device flow, stores tokens in encrypted `LLMProviderIntegration` credentials, refreshes before runtime, and routes runtime calls through the LiteLLM Responses adapter. Model selection uses stored model catalog projections. Providers with static public model catalogs use system catalogs projected from LiteLLM source metadata.

Azents does not currently define an xAI provider enum value, xAI model catalog, or xAI OAuth credential type.

## Proposed design

### Provider identity

Add `LLMProvider.XAI_OAUTH` with value `xai_oauth`. This is a separate provider from the later `xai` API key provider because billing, entitlement, setup, and refresh lifecycle differ.

Display name:

```text
xAI Grok OAuth (SuperGrok / X Premium)
```

The UI and docs must describe the provider as experimental and user-authorized. They must not imply an official partnership.

### Operational config

Add server settings:

- `AZ_XAI_OAUTH_ENABLED` — defaults to `false`.
- `AZ_XAI_OAUTH_CLIENT_ID` — required when OAuth is enabled.

When disabled, the device-start endpoint rejects the connection attempt and the frontend hides the provider option. This provides an admin kill switch if xAI changes access policy.

### OAuth endpoints

Use xAI OIDC discovery from:

```text
https://auth.x.ai/.well-known/openid-configuration
```

Expected endpoints:

- device authorization: `https://auth.x.ai/oauth2/device/code`
- token: `https://auth.x.ai/oauth2/token`

Device start sends form data:

```text
client_id=<configured client id>
scope=openid profile email offline_access api:access grok-cli:access
```

Device poll sends form data:

```text
grant_type=urn:ietf:params:oauth:grant-type:device_code
client_id=<configured client id>
device_code=<device code>
```

Refresh sends form data:

```text
grant_type=refresh_token
client_id=<configured client id>
refresh_token=<refresh token>
```

### Data model

Add an `xai_oauth_sessions` table mirroring the ChatGPT OAuth session table, with workspace/user ownership, encrypted device code, public user code, verification URI, polling interval, status, and expiry.

After a successful exchange, create a workspace-scoped `LLMProviderIntegration(provider=xai_oauth)`.

Encrypted secrets:

```json
{
  "type": "xai_oauth",
  "access_token": "...",
  "refresh_token": "...",
  "id_token": "...",
  "expires_at": "2026-07-10T00:00:00Z"
}
```

Plain config:

```json
{
  "type": "xai_oauth",
  "account_id": "...",
  "email": "user@example.com",
  "connection_method": "device",
  "status": "connected",
  "entitlement_status": null,
  "connected_at": "2026-07-10T00:00:00Z",
  "last_refreshed_at": "2026-07-10T00:00:00Z",
  "last_failed_at": null,
  "last_failure_reason": null
}
```

### Runtime behavior

Before an agent run, refresh xAI OAuth tokens when the access token is near expiry. A five-minute refresh window matches the existing OAuth runtime preflight behavior while still avoiding expiration at request start.

Runtime calls pass:

- `api_key=<access token>`
- `base_url=https://api.x.ai/v1`
- `api_base=https://api.x.ai/v1`
- `custom_llm_provider=xai`

Model calls use LiteLLM's xAI Responses API support.

### Model catalog

Add `xai_oauth` to system catalog projection using LiteLLM provider family `xai`. Provider-facing model identifiers remove the `xai/` prefix, while runtime model identifiers are reconstructed with the `xai/` prefix.

The default selectable model is determined by the projected catalog. The implementation should not hard-code a single Grok default in the OAuth connection flow.

### Error handling

- Device `authorization_pending` remains pending.
- Device `slow_down` remains pending and keeps the provider-recommended polling cadence from device start.
- Device expiry asks the user to start over.
- Token refresh 400/401 marks the integration `refresh_required`.
- Token refresh 403 marks the integration `entitlement_denied` and does not retry repeatedly.
- Inference 403 is surfaced as an xAI OAuth entitlement/tier failure with guidance to use a supported xAI subscription tier or wait for the later API key provider.
- Transient network and 5xx failures mark the provider temporarily unavailable.

### UI/UX

The LLM settings modal exposes xAI OAuth only when the server reports it as enabled. The connection card shows the verification URL and user code, supports headless use, and includes the warning:

```text
Availability is controlled by xAI and may return 403 depending on your subscription tier.
```

## Security and permissions

- Device sessions are bound to workspace and user.
- Device code, refresh token, access token, and id token are never returned to the browser or logs.
- OAuth client id is configuration, not copied from another app.
- The provider is disabled by default.
- Refresh failure quarantine prevents repeated refresh storms for terminal failures.

## Alternatives considered

### Reuse ChatGPT OAuth provider machinery directly

Rejected for this phase. The storage/session code is similar, but xAI has different endpoints, scopes, refresh semantics, and entitlement handling. Copying the structure keeps the implementation explicit and reviewable.

### Use Hermes' OAuth client id

Rejected. That would risk presenting Azents as another registered app identity. Azents should use its own configured client id.

### Implement API key provider first

Deferred by product direction. The current phase implements OAuth first and leaves API key provider as a follow-up.

## Test Strategy

### E2E primary matrix

| Scenario | Expected result | Automation |
| --- | --- | --- |
| xAI OAuth disabled | Provider option hidden and device start rejected | Deterministic E2E or API test |
| Device start enabled | UI shows verification URL and code | Mock-provider E2E or component test |
| Device poll success | Integration row appears with xAI OAuth provider | Mock-provider E2E/API test |
| Refresh required | Runtime refreshes token before model call | Backend unit/integration test |
| Refresh 403 | Integration becomes entitlement denied, not refresh required | Backend unit test |
| Cross-user/session access | Poll/cancel rejected | Backend unit/API test |

### Fixture/prerequisite support

A live xAI OAuth smoke test requires a real account, client id, and subscription entitlement. It must be optional and skipped unless explicit live credentials are configured. Deterministic CI should use mocked xAI OAuth endpoints and not require a real xAI subscription.

### CI policy

Run Python unit tests for xAI OAuth service, credential mapping, model catalog projection, and runtime mapping. Run TypeScript typecheck after generated client updates and frontend changes. Run E2E only when the mock-provider fixture is available in this implementation phase; otherwise record it as planned follow-up validation.

## Rollout

1. Ship disabled by default.
2. Operators configure `AZ_XAI_OAUTH_CLIENT_ID` and enable `AZ_XAI_OAUTH_ENABLED`.
3. Admin refreshes system model catalog so `xai_oauth` models become selectable.
4. If xAI blocks OAuth API use, operators disable the flag without removing stored integrations.

## Open questions

- How will Azents operators obtain an xAI OAuth client id?
- Should the later xAI API key provider share the same `xai` model catalog entries or have its own provider catalog projection?
