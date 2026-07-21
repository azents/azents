---
title: "Model Catalog Projection and Sync"
created: 2026-06-20
tags: [architecture, backend, frontend, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: catalog-260620
historical_reconstruction: true
migration_source: "docs/azents/adr/0067-model-catalog-projection-sync.md"
---

# catalog-260620/ADR: Model Catalog Projection and Sync

## Status

Accepted.

## Context

Agent model selection currently lists provider models at request time. For AWS Bedrock, the API path calls `ListFoundationModels` with the user-provided integration credential. When that credential lacks `bedrock:ListFoundationModels`, the provider returns `AccessDeniedException`, which is currently wrapped as an unhandled `ListingProviderError` and surfaces as a server error.

This exposed several modeling issues:

- Model listing has different ownership depending on source. Some catalogs are managed by Azents independent of a customer credential, while others depend on a customer's provider integration.
- User-provided credential failures must not be treated as Azents server failures.
- External catalog sources such as models.dev can be slow or unstable, so request-time dependence is fragile. The design removes models.dev from model catalog source path instead of adding another sync dependency around it.
- Provider APIs and metadata catalogs have different roles: provider APIs can tell whether a model is visible for a customer integration, while metadata catalogs describe capabilities, context windows, modalities, and runtime compatibility.
- Current UI uses searchable select, which is not enough to expose sync state, sync failure, stale snapshot, infinite scroll, and capability details.
- LiteLLM currently fetches a remote model cost map at import/startup, but LiteLLM is only the current lowerer target. The runtime abstraction must remain open to any-llm or native SDK targets later.

Therefore model catalog needs an explicit sync/projection layer rather than request-time provider calls.

## Decision

### catalog-260620/ADR-D1. Separate system catalog and integration catalog

Model catalog is split by ownership.

System catalog is managed by Azents and is independent of any customer integration. It covers sources such as OpenAI or Anthropic model lists when Azents does not use customer credentials for listing.

Integration catalog is scoped to a provider integration. It covers providers such as AWS Bedrock and Google Vertex AI where visible models depend on credential, account, project, region, or provider-side permission.

Integration is the top-level user-facing unit in model picker. Provider without an enabled integration is not shown as a selectable source.

### catalog-260620/ADR-D2. Do not call external catalog/provider listing from normal read path

Model selection read APIs must read stored catalog projections. They must not fetch models.dev, call Bedrock `ListFoundationModels`, call Vertex publisher models API, or refresh LiteLLM remote metadata during normal model-picker reads.

Read path returns catalog entries with catalog sync metadata, stale/failure state, and pagination cursor.

### catalog-260620/ADR-D3. Full sync is the sync unit

Catalog sync fetches the full available list for the relevant source.

System catalog full sync is expected and should run by schedule or admin operation.

Integration catalog full sync is executed only when appropriate for that integration, not for every unused integration on a global cron. Bedrock/Vertex sync fetches the full provider-visible list for that integration.

Read APIs can expose the stored result with search and infinite scroll. Provider-side partial fetch is not a primary design because it would reintroduce request-path dependency on external providers.

### catalog-260620/ADR-D4. System catalog sync is periodic/admin only and assumes scheduler infrastructure

System catalog sync is not user-triggered.

System catalog refresh should be invoked by Azents periodic execution infrastructure and can optionally be exposed as admin-only operation. Normal users do not get a sync button for system catalog because that can waste shared resources and one user's action can affect all users.

This ADR assumes periodic execution infrastructure exists. It does not design scheduler locking, leasing, retry, worker topology, cron expression, or generic background job framework. Those are separate architecture topics. This ADR only defines the catalog sync/projection services and their persisted state.

If system catalog sync fails, Azents keeps the last successful projection and records the failure for operations. This can be Sentry/alert-worthy because system catalog is Azents-owned.

### catalog-260620/ADR-D5. Integration catalog sync is explicit and throttled

Integration catalog sync can happen in these cases:

- Initial sync after integration create or credential/config update.
- User-triggered sync from integration/model picker UI.
- Optional stale lazy refresh if the integration is actively viewed and throttle/backoff allows it.

Global cron over all integration catalogs is not the default because unused catalogs should not consume provider quota or Azents resources.

Sync must be throttled per integration and workspace. If sync is already running, the button is disabled. Credential/config failures such as access denied or invalid credential should stop automatic retries until the user changes configuration or explicitly retries.

### catalog-260620/ADR-D6. User credential failures are domain state, not unhandled server errors

When an integration catalog sync uses user-provided credentials, access denied, invalid credential, assume-role failure, invalid project/region, and provider permission errors are customer configuration failures.

They must be recorded as catalog sync failure state and shown in UI. They must not be reported as unhandled server errors.

Provider transient failures such as timeout, rate limit, or provider 5xx are controlled sync failures. Existing last successful snapshot remains usable if available.

### catalog-260620/ADR-D7. Model picker uses integration-first modal with infinite scroll

The form shows selected model summary and a model change affordance. Actual model selection opens a modal, popup, or drawer.

The picker first selects provider integration, not provider. After integration is selected, it shows:

- Catalog sync status.
- Last synced time.
- Model count.
- Sync button only for user/integration catalogs.
- Sync loading indicator.
- Failure panel with actionable guidance.
- Search input.
- Infinite-scroll model list.
- Model capability and metadata badges.

Selecting a model closes the picker and updates the form with selected integration and model snapshot.

### catalog-260620/ADR-D8. Use canonical projection layer

Catalog entries stored and exposed by Azents are canonical projections. They are not raw models.dev records, raw provider API records, or raw LiteLLM model cost entries.

A projection contains at least:

- provider integration id when integration-scoped
- provider
- publisher
- provider model identifier
- lowerer target
- runtime model identifier
- display name
- family
- normalized capabilities
- context window
- lifecycle/visibility status
- source metadata snapshot
- projection source metadata

Projection source is chosen by active lowerer target. Current target is LiteLLM, so current projection uses LiteLLM model registry/model cost map. If future lowerer targets such as native SDK or any-llm are added, each target can define its own projection source and matcher.

### catalog-260620/ADR-D9. LiteLLM catalog can be current projection source, but not permanent platform source of truth

LiteLLM currently fetches remote model cost map at import/startup from LiteLLM's GitHub-hosted `model_prices_and_context_window.json`, falling back to bundled backup if remote fetch fails. This catalog includes useful runtime metadata such as context windows, output token limits, vision support, tool calling support, response schema support, PDF input support, reasoning support, and supported OpenAI-compatible parameters.

Because current lowerer target is LiteLLM, LiteLLM registry is the current projection source for system and integration catalogs.

However LiteLLM is not the only possible runtime target. Projection layer must not hard-code LiteLLM as platform source of truth. It should model `lowerer_target` and allow future target-specific projection sources.

### catalog-260620/ADR-D10. Provider x publisher matters for runtime projection

Provider alone is not sufficient for runtime support and capability decisions.

For example, Bedrock x Mistral may use LiteLLM while Bedrock x Claude may later use Anthropic-native-compatible implementation. Vertex x Gemini and Vertex x Anthropic can also require different projection and adapter rules.

Therefore projection and matching must keep publisher/family information, not just provider.

### catalog-260620/ADR-D11. Bedrock/Vertex integration projection uses provider availability plus target projection

For user-scoped providers such as Bedrock and Vertex:

- Provider API is availability source.
- Active lowerer target projection source supplies canonical metadata and runtime compatibility.
- Final selectable catalog is provider-visible models that can be projected for current lowerer target and pass Azents policy.

For current LiteLLM target, this means provider-visible model id must be matchable to LiteLLM model metadata. This is not a permanent rule; it is target-specific projection rule for current runtime.

### catalog-260620/ADR-D12. OpenAI/Anthropic provider APIs are not used yet

OpenAI and Anthropic provider API model listing remain open design space. Current design does not introduce OpenAI or Anthropic API-based listing.

Until a provider API listing design is explicitly adopted, system catalog projection for those providers uses the active lowerer target catalog source and Azents policy.

### catalog-260620/ADR-D13. Preserve agent model selection snapshot semantics

Agent model selection continues to store a snapshot rather than an FK to mutable catalog row.

Catalog projection is used at selection time. Once selected, Agent stores the model selection snapshot needed for runtime. Later catalog sync failures, stale status, or metadata updates do not silently mutate existing Agent model selection.

UI can diagnose drift between selected snapshot and current catalog, but runtime source of truth remains Agent snapshot. Catalog drift is not a runtime block reason by itself. If selected model is missing from current catalog, catalog refresh failed, or metadata changed, Agent form shows warning/diagnostic and lets user keep current selection or choose a current model.

Integration deletion or disabled state can still block or fail runtime because credential/config lookup is no longer possible. This is integration availability failure, not catalog drift failure.

### catalog-260620/ADR-D14. Remove models.dev from catalog source path

models.dev is removed from model catalog source path instead of being wrapped in a new sync lifecycle.

System catalogs such as OpenAI, Anthropic, and Gemini use the current lowerer target projection source. With current LiteLLM target, they are projected from LiteLLM catalog rather than models.dev.

Integration catalogs such as Bedrock and Vertex also use LiteLLM projection source for current target, combined with provider API availability.

OpenAI and Anthropic provider API listing remains out of scope for this ADR. The immediate decision is not to add OpenAI/Anthropic API listing and not to keep models.dev as a parallel source.

### catalog-260620/ADR-D15. Store LiteLLM source snapshots separately from projections

LiteLLM catalog is stored as a source snapshot before system or integration projections are generated.

Periodic execution infrastructure invokes LiteLLM source sync. That job fetches LiteLLM remote model cost map, validates it, records fallback/local source information if fallback is used, and stores a source snapshot with source hash, model count, source URL, LiteLLM version, loaded source, and failure metadata.

System catalog projection and integration catalog projection use the latest successful LiteLLM source snapshot. Integration sync does not fetch LiteLLM remote metadata directly.

### catalog-260620/ADR-D16. Keep only current snapshot and latest attempt state

Catalog identity, current projection snapshot, and latest sync attempt state are separated, but catalog history is not retained in v1.

A catalog represents logical model source for either system scope or integration scope. It points to the current successful snapshot.

A catalog snapshot represents the current successful projection result. Failed sync attempts never overwrite the current snapshot. When a new successful snapshot becomes current, previous snapshots and their entries can be deleted. Historical diff/audit is out of scope and can be designed later if needed.

A sync attempt represents the latest source sync or projection attempt state needed by UI. It records status, timing, produced snapshot if any, failure code/message/action hint, and stats such as fetched count, matched count, skipped count, and hidden count. Long-term attempt history is out of scope for v1.

Read APIs return current snapshot summary, latest attempt summary, and paginated entries. This lets UI show existing model list while also showing that latest sync failed.

### catalog-260620/ADR-D17. Initial integration sync runs after create/update in background

Integration create/update persists integration first and then starts a background initial catalog sync attempt.

Initial sync failure is not integration create/update failure. It is recorded as catalog sync attempt failure.

Persistent error is shown in integration detail model catalog section and in model picker catalog panel. Create/update form can show a transient toast, but the primary failure UI is catalog panel.

When there is no current snapshot and latest attempt failed, picker shows error panel instead of model list. When a current snapshot exists and latest attempt failed, picker keeps showing existing entries and adds a warning banner with retry action.

### catalog-260620/ADR-D18. Start with automatic exposure and hygiene filters, not allow policy

Initial projection does not use provider/publisher/family allow policy.

Projection exposes models that are projectable for the active lowerer target and pass basic hygiene filters. Hygiene filters remove clearly unsupported entries such as embedding-only models, image-generation-only entries when unsupported by Azents model picker, fine-tuned model keys, pricing/image-size variants, unsupported modes, deprecated entries when explicit, provider mismatch, and provider-visible mismatch.

Projection records diagnostics for total candidates, exposed count, hidden count, and hidden reasons. Allow policy can be introduced later when observed catalog noise or runtime failures justify it.

### catalog-260620/ADR-D19. Bedrock and Vertex selectable matching is exact-only in v1

For Bedrock and Vertex integration catalogs, selectable entries require exact match between provider-visible model and current lowerer target projection key.

For current LiteLLM target, Bedrock uses exact `bedrock/{model_id}` projection key. Vertex uses exact `vertex_ai/{model_id}` or exact `vertex_ai/{name_last_segment}` when provider API returns resource name and model id separately.

Fallback normalization candidates such as regional-prefix stripping, version suffix rewriting, `@` to `-` conversion, or direct Anthropic identifier mapping are recorded only as diagnostics in v1. They are not selectable until explicit alias/normalization rules are added based on observed data.

## Consequences

### Positive

- External catalog/provider failures no longer break normal read path.
- User credential permission failures become visible and actionable sync state instead of unhandled server errors.
- Model picker can show sync status, errors, stale snapshot, infinite scroll, and capability metadata.
- System catalog and integration catalog ownership are separated.
- Full sync plus paginated reads keeps provider dependency out of UI browsing.
- Removing models.dev avoids a second unstable external catalog dependency.
- Source snapshots, successful projections, and attempts provide debuggable sync history.
- Canonical projection layer keeps future non-LiteLLM lowerer targets possible.

### Negative / Trade-offs

- Requires new catalog sync/projection storage and jobs.
- Requires UI model picker instead of simple searchable select.
- Requires target-specific model id matching and publisher extraction.
- Current LiteLLM projection can still drift from future non-LiteLLM runtime targets unless target is explicitly recorded.
- LiteLLM catalog is not a UI catalog, so v1 needs hygiene filters and diagnostics.
- Exact-only Bedrock/Vertex matching can hide provider-visible models until explicit alias rules are added.
- Initial sync after integration creation can be asynchronous, so UI must handle `syncing`, `failed`, and `never_synced` states.

## Alternatives

### Keep request-time provider listing

Rejected. It makes external provider/catalog latency and permission failures part of normal read path and turns customer credential failures into server errors.

### Keep models.dev as catalog source

Rejected. models.dev would require its own external sync lifecycle and can be slow or unstable. Keeping it alongside LiteLLM projection source would mix catalog semantics and create drift between selectable models and current lowerer target behavior.

### Use LiteLLM as permanent source of truth

Rejected. LiteLLM is current lowerer target, but Azents lowerer abstraction is generic and future targets may use native SDKs or other runtimes. LiteLLM can be current projection source, not permanent platform source of truth.

### Expose provider-level picker

Rejected. Model visibility and sync state depend on provider integration, not provider alone. Provider without integration is not selectable.

### Partial provider fetch for large catalogs

Rejected for initial design. It reintroduces provider dependency into browsing and complicates complete list UX. Use full sync and expose stored entries with infinite scroll.

## Related Documents

- [selection-260616/ADR: Agent Model Selection Stores Catalog Snapshot Directly Without ModelConfig](./selection-260616-selection-snapshot.md)
- [llm-260513/ADR: Organize LLM model catalog source](./llm-260513-llm-catalog-source.md)

## Migration provenance

- Historical source filename: `0067-model-catalog-projection-sync.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
