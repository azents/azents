---
title: "ADR-0171: Add Kimi Subscription as an Integration-Scoped Provider"
created: 2026-07-19
tags: [architecture, backend, frontend, engine, llm, oauth, billing, security]
---

# ADR-0171: Add Kimi Subscription as an Integration-Scoped Provider

## Status

Accepted for implementation on 2026-07-19.

## Context

Kimi Code subscriptions can authorize the official Kimi CLI through an RFC 8628 device flow and use the resulting access token against the Kimi Code inference, model-listing, and usage endpoints. This credential is operationally different from a Moonshot developer API key: billing and quota belong to a user subscription, tokens rotate, the authorization service requires a stable device identity, and account-visible models come from the authenticated Kimi Code catalog.

Azents already separates ChatGPT and xAI subscription credentials from their developer API-key providers. It also has integration-scoped model catalogs, encrypted provider credentials, runtime token refresh, and normalized subscription-usage presentation. Kimi should join those boundaries rather than introduce an independent runtime or credential store.

The implemented Kimi CLI contract inspected for this decision is MoonshotAI/kimi-cli commit `4a550effdfcb29a25a5d325bf935296cc50cd417` (Kimi CLI 1.49.0, 2026-07-16).

## Decision

### ADR-0171-D1. Represent Kimi subscription access as `kimi_oauth`

Add `LLMProvider.KIMI_OAUTH` with value `kimi_oauth`. It is separate from any present or future Moonshot developer API-key provider because credential shape, billing, entitlement, refresh lifecycle, catalog visibility, and recovery actions differ.

The provider is initially marked experimental. The UI describes it as a user-authorized Kimi subscription connection and does not imply an official Azents partnership.

### ADR-0171-D2. Use the Kimi Code public device client contract

Azents implements only the Kimi Code device authorization flow:

- authorization host: `https://auth.kimi.com`;
- device authorization path: `/api/oauth/device_authorization`;
- token path: `/api/oauth/token`;
- public client id: `17e5f671-d194-4dfb-9706-5516cb48c098`;
- inference base URL: `https://api.kimi.com/coding/v1`.

The public client id is not a secret. Compatibility endpoints and client version remain explicit constants with environment overrides for controlled recovery if Kimi changes the contract.

### ADR-0171-D3. Keep a stable per-integration device identity encrypted

Kimi authorization and refresh requests require `X-Msh-*` compatibility headers, including a stable device id. Azents generates an opaque device id when device authorization starts, stores it encrypted with the pending session, and moves it into encrypted integration secrets after authorization succeeds.

Azents uses fixed product-neutral device labels rather than exposing the deployment hostname or host operating-system identity. The device id, device code, access token, and refresh token are never returned by the public API or written to logs.

### ADR-0171-D4. Use an integration-scoped catalog sourced from Kimi `/models`

`kimi_oauth` uses an integration-scoped model catalog. After connection, Azents refreshes the access token if needed and reads `GET /models` from the Kimi Code API with the subscription Bearer token.

The provider response is authoritative for model visibility, display name, context window, reasoning support, and image/video input support. A matching LiteLLM metadata entry is not required for selection because Kimi account-visible aliases can differ from the public Moonshot catalog.

Catalog reads remain stored projections and reuse the existing create, explicit refresh, stale refresh, cooldown, backoff, fencing, and last-successful-snapshot behavior.

### ADR-0171-D5. Reuse the LiteLLM Moonshot runtime route

Runtime model identifiers use the `moonshot/` LiteLLM prefix and the fixed Kimi Code API base URL. The OAuth access token is passed as the provider API key, with the encrypted device identity projected into the required Kimi compatibility headers.

Kimi remains on the provider-neutral LiteLLM execution path. This decision does not add a Kimi-native Azents transport. Provider-specific differences are limited to credential resolution, routing configuration, headers, and catalog normalization.

### ADR-0171-D6. Refresh before runtime and quarantine permanent rejection

Azents proactively refreshes Kimi access tokens within five minutes of expiry. Refresh-token rotation is persisted atomically through the existing integration repository update path.

- HTTP 401 or 403 from token refresh becomes `refresh_required`.
- HTTP 429 and provider 5xx or transport failure become `temporarily_unavailable`.
- A concurrent successful refresh wins over a stale failing refresh after the latest integration is reread.

Model calls continue to use the common classified `ModelProviderFailure` boundary after credentials resolve.

### ADR-0171-D7. Add Kimi to normalized subscription usage

Kimi usage is read live from `GET https://api.kimi.com/coding/v1/usages` through a provider adapter. The adapter accepts the documented `usage` summary and `limits` collection shapes, normalizes used percentage and reset metadata, and never exposes raw provider payloads.

The existing integration-scoped subscription-usage permissions, non-durable fetch policy, LLM Settings card, and selected-composer projection remain authoritative. Kimi adds one provider adapter; it does not introduce a new public usage schema.

### ADR-0171-D8. Exclude Kimi-specific Search and Fetch services

The Kimi Code search and fetch endpoints are not added in this change. They are separate tool-service contracts and must not be advertised as provider-hosted model capabilities without a dedicated capability, transcript, security, and UX design.

## Rejected Alternatives

### Store Kimi subscription tokens under a generic Moonshot API-key provider

Rejected because it would hide refresh and recovery requirements behind an API-key contract and mix subscription quota with developer API billing.

### Use a system catalog projected from LiteLLM

Rejected because subscription-visible aliases and entitlements come from the authenticated Kimi `/models` response and may not exist in LiteLLM metadata.

### Add a native Kimi transport

Rejected for the first release because LiteLLM already owns the Moonshot chat-completion dialect used by Azents. A native transport would duplicate request lowering, streaming normalization, provider failure classification, and tool-call handling without a demonstrated semantic gap.

### Expose Kimi Search and Fetch as built-in tools

Rejected because the endpoints are service-specific client tools rather than proven model-hosted capabilities. They require a separate execution and transcript contract.

## Consequences

### Positive

- Kimi subscription users can connect without a developer API key.
- Credentials, model visibility, execution, and quota presentation reuse established Azents boundaries.
- New account-visible Kimi models can appear after catalog synchronization without an Azents release.
- Provider contract drift is isolated to explicit Kimi adapters and constants.

### Trade-offs and Risks

- The public Kimi Code client contract can change without notice.
- Kimi may restrict third-party use of its subscription endpoints or public client identity.
- Stable device identity becomes part of encrypted credential lifecycle and migration behavior.
- Live verification requires a real Kimi subscription and remains opt-in; deterministic CI uses mocked provider responses.

## Related Decisions

- ADR-0067 remains authoritative for catalog projection and synchronization.
- ADR-0165 remains authoritative for model-provider failure classification.
- ADR-0169 remains authoritative for integration-scoped subscription usage.
- ADR-0170 remains authoritative for selected-composer usage projection.
