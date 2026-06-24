---
title: "Dynamic LLM ModelConfig Legacy Static Catalog Removal Plan"
created: 2026-05-17
tags: [backend, database, api, documentation, process]
---

# Dynamic LLM ModelConfig Legacy Static Catalog Removal Plan

## Scope

This phase removes remaining legacy static catalog runtime dependency after provider listing integration.

Targets:

- Remove `llm_provider_model` compatibility bridge in Agent service.
- Remove remaining `LLMModelRepository` / `LLMProviderModelRepository` from Agent runtime/subagent/worker dependencies.
- Remove catalog sync bootstrap from app startup.
- Regenerate OpenAPI/client as needed to remove static catalog API/generated client residue.
- Remove static catalog service/repository/model/schema within safe scope.

Non-goals:

- Do not delete historical migration backfill.
- Do not immediately drop legacy nullable columns in already deployed Agent rows. If column drop needs separate Alembic drop verification after runtime read/write removal, split into follow-up.
- Do not change provider listing adapter itself.

## Implementation Plan

1. Remove legacy provider/model pair path from Agent create/update input and allow only `model_config_id` based path.
2. Remove static provider model lookup from Agent output transformation and pin legacy `llm_provider_model` response to `None`.
3. Remove static catalog repositories from runtime resolve/subagent/worker service dependencies.
4. Remove `LLMCatalogSyncService` execution path and fixture import from app startup.
5. Confirm remaining static catalog sync service/repository/model/API imports through audit.
6. Check and apply OpenAPI dump plus Python/TypeScript client regeneration if needed.

## Verification

```bash
cd python/apps/azents && uv run pytest src/azents/services/agent src/azents/services/agent_runtime src/azents/engine/tools/subagent_test.py
cd python/apps/azents && uv run ruff check src/azents/services/agent src/azents/services/agent_runtime src/azents/engine/tools src/azents/worker src/azents/app.py && uv run pyright src/azents/services/agent src/azents/services/agent_runtime src/azents/engine/tools src/azents/worker src/azents/app.py
cd python/apps/azents && uv run python -m azents.testing.model_config_static_catalog_audit --repo-root ../../.. || true
```
