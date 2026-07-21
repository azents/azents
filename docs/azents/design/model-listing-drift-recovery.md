---
title: "Model Listing Drift Recovery Design"
created: 2026-06-18
tags: [backend, api, frontend, engine, documentation]
document_role: supporting
document_type: supporting-consolidation
migration_source: "docs/azents/design/model-listing-drift-recovery.md"
supporting_role: consolidation
---

# Model Listing Drift Recovery Design

## 1. Background

[dynamic-260516/ADR](../adr/dynamic-260516-dynamic-llm-configs.md) adopted a structure that separates Agent model selection from static `LLMModel` / `LLMProviderModel` catalog and queries provider-specific dynamic model listing through workspace `LLMProviderIntegration` credential/config. That decision included these principles.

- `LLMModel` / `LLMProviderModel` are no longer managed as static catalog for Agent model selection.
- Existing `llm_models`, `llm_provider_models`, catalog sync, Admin/public model catalog API, and frontend static model router are removal targets.
- Do not reuse `llm_provider_models` as discovery cache.
- Dynamic listing result is ephemeral and is not FK target of Agent or ModelConfig.
- If cache is needed, newly design separate table not referenced by Agent/ModelConfig.

[selection-260616/ADR](../adr/selection-260616-selection-snapshot.md) later removed `ModelConfig` entity and simplified Agent/Workspace to directly store model selection snapshots. This change removes ModelConfig rows; it does not remove integration-scoped dynamic listing. At Agent/Workspace settings submit time, server still must query integration-scoped listing again and store selected model identifier as server-normalized snapshot.

Current implementation has drifted from this intent.

## 2. Current Drift

### 2.1 Static catalog entity remains

Following static catalog code and DB models still remain.

- `llm_models`
- `llm_provider_models`
- `llm_catalog_sources`
- `llm_model_overrides`
- `LLMCatalogSyncService`
- `LLMModelRepository`
- `LLMProviderModelRepository`
- `LLMCatalogSourceRepository`
- `LLMModelOverrideRepository`
- Admin/public `llm_model` / `llm_provider_model` API surface
- catalog sync merge/materialize/source status code

These do not match [dynamic-260516/ADR](../adr/dynamic-260516-dynamic-llm-configs.md) decision to remove static catalog.

### 2.2 Integration model listing uses static cache

`ModelListingService.list_by_integration()` loads integration, then first queries `llm_provider_models` materialized cache. In production, even if cache is empty, it does not fall through to provider API or Models.dev dynamic listing and returns empty listing.

This differs from `dynamic-llm-model-configs.md` design: "dispatch through integration provider to query dynamic listing and do not persist listing rows."

### 2.3 Providers like Bedrock/Vertex cannot be represented by global cache

For providers such as AWS Bedrock, Google Vertex AI, and Azure OpenAI, exposed models differ by user integration account, project, region, credential, entitlement, and IAM permission. Global `llm_provider_models` cache cannot represent this difference.

Therefore, Bedrock/Vertex family becomes structurally inaccurate once using global static catalog cache. As in original design, source of truth must be dynamic listing based on integration credential/config.

### 2.4 Spec reflected the drift

Current `docs/azents/spec/domain/agent.md` says production environment prioritizes materialized `llm_provider_models` cache and does not perform on-demand fetch even if cache is empty.

But this conflicts with intent of [dynamic-260516/ADR](../adr/dynamic-260516-dynamic-llm-configs.md)/0063. Spec followed current implementation and became drifted. This recovery must update it to original decisions.

## 3. Goals

1. Restore Agent/Workspace model picker to integration-scoped dynamic listing.
2. Do not use `llm_provider_models` as model listing cache.
3. Remove static catalog entity, repository, service, API, and sync code.
4. Store only model selection snapshot verified by server at submit time in Agent/Workspace.
5. Use provider-specific listing source in production as well. OpenAI/Anthropic/Gemini can use public catalog source; Bedrock/Vertex use provider API based on integration credential/config.
6. Existing Agent runtime uses stored snapshot as source of truth and does not query latest listing again on run start.
7. Update current spec to match [dynamic-260516/ADR](../adr/dynamic-260516-dynamic-llm-configs.md)/0063 intent.

## 4. Non-goals

- Do not introduce integration-scoped persistent cache table in this work.
- Do not create model listing refresh scheduling, stale indicator, or manual refresh UX in this work.
- Do not automatically correct existing Agent snapshot to latest listing.
- Do not handle provider-specific quota, billing, or failover policy.
- Do not revive ModelConfig entity.

## 5. Target State

### 5.1 Model listing source

`GET /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/{integration_id}/models` behaves in this order.

1. Verify Workspace member permission.
2. Verify Integration ownership and enabled state.
3. Call provider-specific listing adapter according to Integration provider.
4. Adapter returns only normalized model candidates needed by runtime.
5. Exclude source models that fail normalization or are unsupported from user-visible list and report skip summary.
6. Listing result is not stored in DB.

Provider-specific source policy:

- OpenAI, Anthropic, Google Gemini, ChatGPT OAuth: can use Models.dev or provider-specific public catalog adapter.
- AWS Bedrock: call Bedrock API with integration config/secrets.
- Google Vertex AI: call Vertex publisher model API with integration config/secrets.
- Future providers decide source in adapter depending on account/project/region scoped nature.

### 5.2 Agent/Workspace submit path

Agent create/update and Workspace model settings update accept only `{ llm_provider_integration_id, model_identifier }` sent by client as trustworthy keys. Server queries same integration-scoped listing again and stores snapshot only when matching candidate exists.

If matching candidate is absent or integration listing fails, do not store and return error.

### 5.3 Runtime path

Runtime resolve uses only Agent row `model_selection` / `lightweight_model_selection` snapshot and integration credentials. Runtime does not query model listing API or catalog.

## 6. Removal Targets

Remove following code families in this recovery.

- `azents.rdb.models.llm_model`
- `azents.rdb.models.llm_provider_model`
- `azents.rdb.models.llm_catalog_source`
- `azents.rdb.models.llm_model_override`
- `azents.repos.llm_model`
- `azents.repos.llm_provider_model`
- `azents.repos.llm_catalog_source`
- `azents.repos.llm_model_override`
- `azents.services.llm_model`
- `azents.services.llm_provider_model`
- `azents.services.llm_catalog_sync`
- `azents.api.admin.llm_model`
- `azents.api.admin.llm_provider_model`
- `azents.api.public.llm_provider_model`
- `Config.llm_catalog_*` settings
- catalog sync-only tests and stale spec wording

However, provider dynamic listing adapter may reuse Models.dev parser. Reused code must remain as listing adapter implementation, not static catalog sync service.

## 7. DB Migration

DB migration drops static catalog tables and enums.

Target tables:

- `llm_provider_models`
- `llm_models`
- `llm_model_overrides`
- `llm_catalog_sources`

Target enums:

- `llm_model_lifecycle_status`
- `llm_catalog_source_type`
- `llm_catalog_source_status`

Deletion order considers FK dependencies. In current state converted to Agent/Workspace snapshot structure, runtime path must not reference these tables. Before migration, verify there are no remaining references with code search and pyright.

## 8. UI/UX Impact

Agent form and Workspace model settings form already use integration selector and model selector. Main improvement is error/empty state.

- If listing is empty after Integration selection, show "No selectable models."
- If listing query fails, show "Failed to fetch model list."
- If Integration is disabled, clearly show model listing error.

This UX improvement makes cause easier to understand, but core recovery is returning backend listing source to dynamic path.

## 9. Risks and Responses

| Risk | Response |
|---|---|
| Provider API listing failure directly affects Agent create/settings UX | Existing Agent runtime snapshot continues to work. Listing failure affects only new selection/change. |
| Bedrock listing latency can be long | Design integration-scoped cache/refresh as separate future feature. This recovery prioritizes correctness. |
| Models.dev payload change can break OpenAI/Gemini listing | Fix payload shape with adapter tests and propagate original exception so FastAPI/server error handling treats as 500. |
| Static catalog table drop can break unexpected reference | Verify with code search, pyright, migration test, repository/service test cleanup. |

## 10. Test Strategy

### 10.1 Backend unit/integration

- `ModelListingService.list_by_integration()` calls provider adapter without `llm_provider_models` repository.
- OpenAI integration listing returns Models.dev adapter result as normalized candidates.
- Bedrock integration listing calls Bedrock adapter using integration config/secrets.
- If integration is disabled, listing API returns clear error.
- Listing fetch failure is propagated as original exception, not modeled as service failure variant.
- Agent create/update revalidates selection key with server-side listing and stores snapshot.
- Workspace model settings update uses same validation path.
- Runtime resolve uses only Agent snapshot and does not call listing service.

### 10.2 Migration

- Alembic upgrade drops static catalog tables and enums.
- Alembic downgrade clearly follows minimal recreation or unsupported policy if needed.
- After migration, metadata import and pyright pass without static catalog model references.

### 10.3 Frontend

- Model options are shown when model listing query succeeds after provider selection.
- Empty message is shown when listing result is empty.
- Error message is shown when listing query fails.

### 10.4 E2E / live

- With deterministic fixture integration, model appears in Agent creation screen and Agent creation succeeds.
- Live/external Bedrock verification runs only in opt-in environment with credential snapshot. If credential is absent, deterministic CI skips.

## 11. Rollout / Verification

1. Pass Python unit/integration, pyright, TypeScript typecheck/lint, and migration verification in PR.
2. Merge after CI passes.
3. After deployment, verify `/models` returns models for OpenAI provider integration in production.
4. For Bedrock, verify `/models` returns region/account-scoped result in workspace with live credential.
5. Verify existing Agent run executes normally with stored snapshot.
