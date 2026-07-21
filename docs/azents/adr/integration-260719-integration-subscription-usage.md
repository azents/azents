---
title: "Read Subscription Usage Through Provider Integrations"
created: 2026-07-19
tags: [architecture, backend, frontend, llm, oauth, billing, security, ux, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: integration-260719
historical_reconstruction: true
migration_source: "docs/azents/adr/0169-integration-scoped-subscription-usage.md"
---

# integration-260719/ADR: Read Subscription Usage Through Provider Integrations

## Status

Accepted for implementation planning.

## Context

Azents supports workspace-scoped ChatGPT OAuth and xAI OAuth integrations that use a user's subscription credential for model execution. The LLM Settings surface shows connection and enabled state, but it does not show the provider-side subscription limits that determine whether the integration can continue serving runs.

This information is different from AgentRun token usage and context-window pressure. Run usage describes one resolved model execution. Subscription usage describes an external account quota shared by every Azents execution and other clients using the same provider account.

Current upstream clients expose authenticated usage data, but the contracts are provider-specific and not documented as stable public APIs:

- OpenAI Codex reads ChatGPT rate-limit windows, credits, spend control, and plan metadata from the ChatGPT backend.
- Grok Build reads xAI credit usage and billing details through the CLI proxy, and can replace inline usage with a provider-managed external usage URL through remote settings.

Azents must expose useful operational quota state without leaking OAuth credentials, raw billing payloads, sensitive financial details, or provider-specific wire contracts into the public API and frontend.

## Decision

### integration-260719/ADR-D1. Model subscription usage as an integration-scoped live snapshot

Subscription usage belongs to `LLMProviderIntegration`, not Agent, Session, AgentRun, model catalog, or token-usage history.

Azents exposes one usage read operation for one integration. A snapshot states what the provider reported at `fetched_at`; it is not an Azents accounting ledger and does not claim that Azents caused the reported usage.

AgentRun token usage, context-window usage, estimated API cost, and subscription usage remain separate contracts and UI labels.

### integration-260719/ADR-D2. Support only subscription OAuth integrations

The first supported providers are:

- `chatgpt_oauth`;
- `xai_oauth`.

OpenAI API-key and xAI API-key integrations are excluded because developer API billing is separate from ChatGPT, SuperGrok, and X Premium subscription usage. Other providers require an explicit adapter and contract decision before becoming eligible.

### integration-260719/ADR-D3. Use provider adapters behind a normalized public contract

Each provider adapter owns authentication headers, compatibility versions, endpoint paths, response parsing, and provider-specific failure classification.

The public response exposes:

- a discriminated availability state;
- normalized limit windows with usage percentage and reset metadata;
- optional plan display metadata;
- optional provider-specific financial details visible only to integration managers;
- fetch time and a provider-neutral action hint.

Raw provider responses, arbitrary metadata, OAuth tokens, account headers, request identifiers, and provider exception serialization never cross the adapter boundary.

### integration-260719/ADR-D4. Keep the feature read-through and non-durable

The initial implementation does not add subscription-usage tables, snapshot history, periodic collection, workspace aggregation, alerts, or billing reconciliation.

The backend fetches the provider when the authenticated usage endpoint is read. The web query cache controls duplicate reads and preserves the last successful client-side value during a failed refresh. No background global scan calls unused integrations.

Historical graphs or server-side shared cache require a later decision because they introduce retention, freshness, multi-tenant financial-data storage, and scheduler policy.

### integration-260719/ADR-D5. Split operational and financial visibility by existing permissions

A member with `LLM_INTEGRATIONS_READ` can read operational quota information needed to understand shared integration availability:

- limit label;
- used percentage;
- window duration;
- reset time;
- provider availability state.

Financial details are returned only when the member also has `LLM_INTEGRATIONS_WRITE`:

- credit balances;
- spend-control amounts;
- pay-as-you-go cap and usage;
- auto top-up state and amounts.

The endpoint does not introduce a new permission resource in the first implementation.

### integration-260719/ADR-D6. Place the primary UI inside each LLM Settings integration card

The Workspace LLM Settings integration card is the canonical usage surface because it already owns connection state, enabled state, alias, and credential management.

The card shows compact limit rows below its header. Provider-specific financial details remain collapsed and are omitted for read-only members. The UI shows fetch freshness and a manual refresh affordance.

The first implementation does not add a persistent global header indicator or an always-visible chat indicator. Those surfaces are ambiguous when a workspace has multiple integrations or a run resolves a different provider. A future run-scoped warning may be designed separately using resolved integration provenance.

### integration-260719/ADR-D7. Treat expected provider read outcomes as typed domain state

The usage read contract can return `available`, `external`, or `unavailable` domain states.

Expected external outcomes such as an unsupported account, provider rate limit, provider-side billing permission denial, missing account metadata, provider contract drift, or provider-directed external usage page are typed usage states. Unexpected Azents failures still raise normally and are not hidden inside a successful response.

Isolation is integration-local across the entire read path. Each integration uses a separate child endpoint request and card-local frontend query. Usage completion never gates the integration list or card management controls, and one usage failure never invalidates, cancels, or hides another integration's usage state. Initial failure replaces only the affected card's usage section; failed refresh preserves its last successful client snapshot as stale. A card-local presentation error boundary contains unexpected usage UI defects.

A usage fetch failure does not disable the integration or change its execution status. Only the existing shared OAuth refresh lifecycle may update integration status when token refresh itself proves the credential invalid.

### integration-260719/ADR-D8. Respect provider-specific control planes

ChatGPT usage uses the ChatGPT backend root and rate-limit usage path, not the Responses runtime URL ending in `/codex`.

xAI usage uses the authenticated CLI proxy, not the `api.x.ai/v1` inference endpoint. Before reading billing data, the adapter performs the provider remote-settings check. A valid provider-managed usage redirect returns the `external` state and skips billing fetch, matching Grok Build's kill-switch behavior.

Provider-returned external URLs are exposed only after HTTPS and trusted xAI domain validation.

### integration-260719/ADR-D9. Do not infer quota enforcement or remaining request count

Azents displays provider-reported percentages, windows, reset times, and financial values without converting them into estimated message counts or guaranteed remaining executions.

Model choice, request size, provider multipliers, shared external usage, and provider policy can change actual consumption. The UI uses `used` terminology and never promises a precise number of requests remaining.

## Rejected Alternatives

### Persist every usage snapshot

Rejected for the first version. It creates a financial-data retention contract, requires collection scheduling and pruning, and can imply accounting authority that Azents does not have.

### Add usage fields to the integration list response

Rejected because ordinary integration reads would trigger external provider calls, couple list availability to upstream availability, and prevent independent loading and refresh state per integration.

### Expose provider responses directly

Rejected because it leaks unstable wire contracts and potentially sensitive billing metadata into the public API and frontend.

### Show subscription usage in the global app header

Rejected because one workspace can have multiple eligible integrations and the global percentage would not identify which integration or quota window it represents.

### Make usage visible only to owners

Rejected because ordinary workspace members consume the shared integration and need operational quota/reset visibility. Financial values remain management-only.

### Treat provider usage failure as integration failure

Rejected because billing visibility and inference entitlement are not identical. A provider can deny or redirect usage reads while model execution remains valid.

## Consequences

### Positive

- Users can diagnose shared subscription exhaustion before or after a provider limit failure.
- Provider wire contracts remain isolated behind adapters.
- No durable billing or financial-history storage is introduced.
- Existing workspace permission boundaries govern visibility.
- ChatGPT and xAI can render through one common card component while retaining provider-specific details.

### Trade-offs

- The feature depends on implementation-backed upstream endpoints that can change without public API version guarantees.
- A page refresh can fail even while inference remains healthy.
- Multiple members can independently trigger provider reads; the initial design relies on client query caching rather than shared server cache.
- Supporting new subscription providers requires a new adapter, normalization tests, and explicit financial-detail projection.

## Related Decisions

- [catalog-260620/ADR](./catalog-260620-catalog-projection-sync.md) remains authoritative for provider integration catalog sync. Subscription usage is intentionally not a catalog projection or stored sync lifecycle.
- [context-260710/ADR](./context-260710-context-usage-display.md) remains authoritative for run-scoped context usage display. Subscription usage must not be combined with its numerator or denominator.
- [failures-260718/ADR](./failures-260718-failures-transparent.md) remains authoritative for model execution provider failures. Subscription usage reads use a separate read outcome and do not create AgentRun retry state.

## Migration provenance

- Historical source filename: `0169-integration-scoped-subscription-usage.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
