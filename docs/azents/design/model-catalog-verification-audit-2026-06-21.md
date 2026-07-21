---
title: "Model Catalog Verification Audit - 2026-06-21"
created: 2026-06-21
updated: 2026-06-21
implemented: 2026-06-21
tags: [backend, api, frontend, engine, verification]
document_role: supporting
document_type: supporting-audit
migration_source: "docs/azents/design/model-catalog-verification-audit-2026-06-21.md"
---

# Model Catalog Verification Audit - 2026-06-21

## Scope

This audit compares the model catalog stacked implementation against [catalog-260620/ADR](../adr/catalog-260620-catalog-projection-sync.md) and `docs/azents/design/model-catalog-projection-sync.md` before merge.

Audited PR stack:

- `#4810` model-catalog [1/N]: projection sync design
- `#4811` model-catalog [2/N]: backend storage foundation
- `#4812` model-catalog [3/N]: system projection
- `#4813` model-catalog [4/N]: schedule system projection
- `#4814` model-catalog [5/N]: sync attempt state
- `#4815` model-catalog [6/N]: integration projection
- `#4816` model-catalog [7/N]: stored catalog reads

## Verification commands

Executed before and during this audit:

```console
$ cd python/apps/azents && uv run ruff check --fix src/azents/repos/llm_catalog
$ cd python/apps/azents && uv run ruff format src/azents/repos/llm_catalog
$ cd python/apps/azents && uv run pyright src/azents/repos/llm_catalog
$ cd python/apps/azents && uv run pytest src/azents/services/llm_catalog
$ cd typescript && pnpm --filter @azents/web run format
$ cd typescript && pnpm --filter @azents/web run lint
$ cd typescript && pnpm --filter @azents/web run typecheck
$ cd python/apps/azents && uv run ruff check --fix src/azents/services/llm_catalog src/azents/api/public/llm_provider_integration/v1
$ cd python/apps/azents && uv run ruff format src/azents/services/llm_catalog src/azents/api/public/llm_provider_integration/v1
$ cd python/apps/azents && uv run pyright src/azents/services/llm_catalog src/azents/api/public/llm_provider_integration/v1
$ cd python/apps/azents && uv run python src/cli/dump_openapi.py
$ cd typescript && pnpm --filter @azents/public-client run generate
```

CI evidence:

- `#4811` and `#4812` reached green after the migration enum fix.
- Later stack runs had repeated deterministic E2E failures caused by GitHub runner shutdown/buildx timeout, with log evidence such as `runner has received a shutdown signal` and Docker socket `context deadline exceeded`. Non-E2E jobs passed on the observed runs.

## Findings and fixes

### F-1. Migration enum bootstrap failure

- **Related requirements:** REQ-6, REQ-11
- **Finding:** The projection table migration reused `llm_model_lifecycle_status` after the legacy static catalog migration had dropped that enum. CI test database creation failed with `type "llm_model_lifecycle_status" does not exist`.
- **Fix:** `#4811` migration now creates and drops `llm_model_lifecycle_status` with the new projection tables.
- **Status:** Fixed and CI-verified on `#4811`.

### F-2. Normal frontend model reads still used request-time listing

- **Related decisions:** [catalog-260620/ADR-D2](../adr/catalog-260620-catalog-projection-sync.md), D14
- **Finding:** Agent and workspace model settings containers still called the legacy `/models` path through tRPC.
- **Fix:** `#4816` switches `llmProviderIntegration.listModels` to `/catalog-entries` and maps stored projection entries into the existing option shape.
- **Status:** Fixed for current azents-web normal model selection reads.

### F-3. Integration catalog reads for system providers needed fallback

- **Related decisions:** [catalog-260620/ADR-D1](../adr/catalog-260620-catalog-projection-sync.md), D12
- **Finding:** Stored catalog reads are integration-first, but OpenAI/Anthropic/Gemini use system catalogs rather than integration-specific provider listings.
- **Fix:** The repository read path verifies the integration belongs to the workspace, then falls back to the provider system catalog when no integration catalog exists.
- **Status:** Fixed.

### F-4. Integration sync failure could still surface as unhandled server error

- **Related decisions:** [catalog-260620/ADR-D6](../adr/catalog-260620-catalog-projection-sync.md), D17
- **Finding:** Integration sync marked attempts as failed but re-raised provider/listing exceptions. A manual sync retry could still return an unhandled server error instead of domain failure state.
- **Fix:** Verification phase changes `IntegrationCatalogProjectionService.sync_integration_catalog()` to return a failed sync summary after persisting the failed attempt. The public sync response includes `status`, `failure_code`, `failure_message`, and `action_hint`.
- **Status:** Fixed in verification branch.

### F-5. Initial integration sync was not queued after create/update

- **Related decisions:** [catalog-260620/ADR-D5](../adr/catalog-260620-catalog-projection-sync.md), D17
- **Finding:** The explicit sync endpoint existed, but create/update did not start an initial integration catalog sync.
- **Fix:** Verification phase queues a best-effort FastAPI background task after Bedrock/Vertex create or update. The background task calls the integration sync service and never fails the create/update response.
- **Status:** Fixed in verification branch.

## Requirement audit

| Requirement | Verdict | Evidence / Notes |
| --- | --- | --- |
| REQ-1. Split system catalog and integration catalog | Pass | `llm_catalogs.scope`, system/integration uniqueness constraints, integration-first read API. |
| REQ-2. Remove external listing from normal read path | Pass for current UI read path | azents-web now calls `/catalog-entries`; read repository only queries stored rows. Legacy `/models` endpoint remains for compatibility but is no longer the normal frontend path. |
| REQ-3. Implement full sync units | Partial | System projection and explicit integration full sync exist. Initial create/update sync is now queued. Throttled stale refresh and duplicate-running disable are not implemented in v1 stack. |
| REQ-4. Persist user credential failures as domain state | Pass for sync attempt state | Failed integration sync attempts are persisted and manual sync now returns failed sync summary instead of re-raising. UI failure panel is still minimal. |
| REQ-5. Provide integration-first picker with catalog state | Partial | Existing UI remains Select-based and integration-first enough for current forms. The richer modal/drawer, sync status panel, failure panel, and infinite-scroll UX are not implemented in this stack. |
| REQ-6. Store canonical projection entries | Pass | `llm_catalog_entries` stores provider, publisher/family, provider/runtime ids, lowerer target, capabilities, lifecycle/visibility, source/projection metadata. |
| REQ-7. Combine provider availability with target projection for Bedrock/Vertex | Pass for v1 exact matching | Integration projection uses provider listing plus exact LiteLLM target keys and hides missing matches. |
| REQ-8. Keep OpenAI/Anthropic listing and models.dev out of scope | Pass for model catalog stored path | System projection uses LiteLLM source. Legacy models.dev code remains isolated in the legacy `model_listing` service. |
| REQ-9. Preserve Agent snapshot semantics | Pass for backend/runtime model | Agent selection continues to store snapshots; catalog entries are not referenced as mutable runtime FK. Drift diagnostics UI is not implemented. |
| REQ-10. Store LiteLLM source snapshots separately from projections | Pass | `litellm_source_snapshots` is separate from `llm_catalog_snapshots` and projection entries reference source snapshot IDs. |
| REQ-11. Keep current snapshot and latest attempt only | Pass | Catalog points to current snapshot/latest attempt; snapshot replacement deletes the previous snapshot and cascading entries. |

## ADR audit

| Decision | Verdict | Evidence / Notes |
| --- | --- | --- |
| D1 | Pass | System vs integration catalogs and integration-first frontend reads. |
| D2 | Pass for current UI read path | Stored `/catalog-entries` endpoint is used by azents-web model selection. |
| D3 | Pass | Sync writes full snapshots, read path paginates/searches stored entries. |
| D4 | Pass | Scheduler task `model_catalog_system_projection` drives system projection. |
| D5 | Partial | Explicit sync and create/update background sync exist. Throttling/concurrent-disable remains a follow-up. |
| D6 | Pass | Sync exceptions become failed attempt state and failed sync response. |
| D7 | Partial | Current UI reuses Select controls; full modal/infinite-scroll/catalog-state UX remains follow-up. |
| D8 | Pass | Canonical projection storage exists. |
| D9 | Pass | LiteLLM is modeled as lowerer target and source snapshot, not permanent platform truth. |
| D10 | Pass | Publisher/family fields are stored. |
| D11 | Pass | Bedrock/Vertex integration projection combines provider visibility and target projection metadata. |
| D12 | Pass | OpenAI/Anthropic provider API listing was not added. |
| D13 | Pass | Agent model selection snapshot semantics remain unchanged. |
| D14 | Pass for stored model catalog path | models.dev is not used by sync/projection/read path. |
| D15 | Pass | LiteLLM source snapshots are separate records. |
| D16 | Pass | Current snapshot/latest attempt state only. |
| D17 | Pass for backend behavior | Initial sync is now queued after create/update, and failures are persisted. |
| D18 | Pass | Hygiene filters hide unsupported modes, sample spec, and fine-tuned keys; no allow policy. |
| D19 | Pass | Exact Bedrock/Vertex target projection matching is implemented. |

## Remaining follow-ups before GA

The following items are intentionally left as follow-up UX/operational hardening rather than blockers for the backend stored-read cutover stack:

1. Replace Select-based frontend picker with the full modal/drawer catalog browser.
2. Add catalog sync status/failure panel and manual retry UI to the model picker.
3. Add server-side cursor pagination/infinite-scroll UI.
4. Add stale refresh throttling and duplicate-running sync disable semantics.
5. Add Agent edit drift diagnostics between selected snapshot and current catalog.
6. Remove or quarantine the legacy `/models` endpoint after all consumers migrate.

## Verdict

The high-risk reliability gaps found during audit were fixed in the verification branch:

- migration enum bootstrap;
- frontend stored-read cutover;
- system catalog fallback for non-user-listed providers;
- user credential sync failure as domain state;
- create/update best-effort initial integration sync.

The remaining gaps are UX completeness and operational hardening items. They should be tracked before GA, but they do not reintroduce external provider/model catalog calls into the current frontend normal read path.
