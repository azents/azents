---
title: "Model Catalog ADR-0067 Drift Correction"
created: 2026-06-21
updated: 2026-06-21
tags: [backend, frontend, engine, documentation]
---

# Model Catalog ADR-0067 Drift Correction

## Context

ADR-0067 defines model catalog projection and sync as a stored projection system. The implementation that reached production created part of the persistence and API surface, but it drifted from the ADR in several user-visible and lifecycle-critical areas.

This document records that drift and is the active correction checklist. The implementation must prefer replacement over modification: when a local component, hook, service method, or response model has the wrong state model, replace the narrow unit instead of preserving the wrong shape with flags or compatibility branches. Legacy dynamic listing and compatibility layers must be removed rather than kept alongside the corrected path.

## Source of Truth

- ADR: `docs/azents/adr/0067-model-catalog-projection-sync.md`
- Current spec: `docs/azents/spec/domain/model-catalog.md`
- Current affected paths:
  - `python/apps/azents/src/azents/services/llm_catalog/__init__.py`
  - `python/apps/azents/src/azents/repos/llm_catalog/__init__.py`
  - `python/apps/azents/src/azents/api/public/llm_provider_integration/v1/__init__.py`
  - `python/apps/azents/src/azents/api/public/llm_provider_integration/v1/data.py`
  - `typescript/apps/azents-web/src/features/agents/containers/useAgentFormContainer.ts`
  - `typescript/apps/azents-web/src/features/agents/components/AgentForm.tsx`
  - `typescript/apps/azents-web/src/features/agents/components/ModelCatalogPicker.tsx`
  - `typescript/apps/azents-web/src/trpc/routers/llm-provider-integration.ts`

## Drift Register

### D1. Form-level model list prefetch violates lazy stored read intent

ADR-0067 requires the normal picker read path to read stored projections without request-time provider listing. The current backend read path mostly follows that rule, but the web form prefetches catalog entries for every integration while rendering the form.

Impact:
- `Change model` shows a spinner before the picker opens.
- Opening the agent form triggers unnecessary catalog entry API calls for all integrations.
- User catalog status and entries are coupled to form load instead of picker state.

Correction:
- Remove form-level `listModels` query fan-out.
- Keep the form summary sourced from the saved model selection snapshot.
- Load catalog status/entries only inside the picker after it is opened and an integration is selected.

### D2. User catalog failure state is not a provider-specific issue

ADR-0067-D6 applies to every user/integration catalog that uses user-provided credentials. Bedrock access denied is only one example. Google Vertex AI and any future user-credential catalog provider must use the same domain failure model.

Impact:
- No-snapshot failure can be masked as `never synced`, `0 models`, or empty search results.
- The UI does not reliably show permission/credential/config failures with action guidance.

Correction:
- Model catalog status must expose latest attempt even when there is no current snapshot.
- User catalog failures must render through provider-independent UI states.
- Bedrock and Vertex-specific errors may map to provider-specific messages, but the UI state machine is common.

### D3. Read API cannot represent no-snapshot failure state

ADR-0067-D16/D17 requires read APIs to return current snapshot summary, latest attempt summary, and paginated entries so the UI can distinguish never synced, syncing, failed with no snapshot, and failed with an existing snapshot.

Impact:
- `/catalog-entries` returns 404 when the catalog has no current snapshot.
- The UI cannot show the latest failed attempt if entries are unavailable.

Correction:
- Replace the current catalog entry read response shape with a status-aware response that can return `current_snapshot_id: null`, `entries: []`, `total: 0`, and `latest_attempt`.
- Do not add a legacy compatibility response. Regenerate the OpenAPI client and replace the frontend types accordingly.

### D4. Picker uses a Load more button instead of infinite scroll

ADR-0067-D7 requires an infinite-scroll model list.

Impact:
- The picker visibly exposes a `Load more` button and does not implement the intended scroll behavior.

Correction:
- Replace local slicing with server-paged data.
- Add an intersection sentinel inside the scroll area.
- Fetch the next page automatically when the sentinel becomes visible.

### D5. Latest model ordering is not implemented

The accepted goal requires newest model choices to appear first. The current repository query orders by `display_name.asc()`.

Impact:
- Older or lexicographically earlier models can appear above current GPT-5.x style models.

Correction:
- Add a projection sort key that ranks likely-newer model identifiers before older identifiers.
- Use the stored sort key in catalog entry reads.
- Add tests for GPT-style ordering and stable tie breakers.

### D6. Picker and form text is not localized

New model catalog UI strings are hardcoded in English.

Impact:
- Korean and other locale users see untranslated UI.

Correction:
- Move all new form/picker strings into locale messages.
- Update every supported locale file.
- Remove hardcoded user-facing picker text except provider/model identifiers and raw provider failure messages.

### D7. Sync throttling and retry policy is incomplete

ADR-0067-D5 requires per-integration throttling, disabled sync while running, and automatic retry suppression after credential/config failures until the user changes configuration or explicitly retries.

Impact:
- Duplicate sync behavior and retry semantics are not clearly enforced or tested.

Correction:
- Replace sync start logic with a repository/service path that detects running attempts and returns a domain conflict.
- Record retry-blocking failure categories for user credential/config errors.
- Allow explicit user retry and integration create/update to start a new attempt.

### D8. Projection diagnostics and hygiene are too shallow

ADR-0067-D18/D19 requires hidden reasons, diagnostics for exposed/hidden counts, and exact-only matching diagnostics for Bedrock/Vertex.

Impact:
- Missing projection matches are difficult to diagnose.
- Hidden model reasons are not summarized enough for operations.

Correction:
- Add diagnostics with candidate count, exposed count, hidden count, hidden reason counts, and exact-match misses.
- Keep Bedrock/Vertex selectable matching exact-only while recording possible fallback candidates only as diagnostics.

### D9. Frontend state model is not an ADR state machine

The picker currently derives UI from ad hoc props, `modelsLoading`, and local arrays.

Impact:
- Empty, failed, never-synced, syncing, and ready states are conflated.

Correction:
- Replace picker props with a state model that represents:
  - no integration selected
  - loading status
  - never synced
  - syncing without snapshot
  - failed without snapshot
  - ready
  - ready with latest failed attempt
  - empty ready result
  - loading next page
- Render failure before empty results.

## Correction Checklist

### Documentation

- [ ] Record this drift document in the PR.
- [ ] Update `docs/azents/spec/domain/model-catalog.md` after code changes.

### Backend/API

- [x] Replace catalog entry list output with status-aware nullable snapshot output.
- [x] Ensure user catalog latest attempt is readable with no current snapshot.
- [x] Replace integration sync start logic with running-attempt conflict/throttle behavior.
- [x] Record user credential/config failure categories as domain sync failures.
- [x] Keep provider-specific error mapping behind a provider-independent sync failure contract.
- [x] Add latest-first projection sort key and use it in repository reads.
- [x] Add projection diagnostics for hidden reasons and exact-match misses.
- [x] Remove remaining stale dynamic listing response or compatibility surfaces.

### Frontend

- [x] Remove form-level model catalog prefetch.
- [x] Remove `Change model` loading spinner.
- [x] Replace picker data flow with lazy open-and-selected-integration queries.
- [x] Replace `Load more` with intersection-observer infinite scroll.
- [x] Render provider-independent user catalog failure panels.
- [x] Render no-snapshot failed state before empty model state.
- [x] Render with-snapshot failed state as warning plus existing entries.
- [x] Apply latest-first ordering from API without client-only reordering hacks.
- [x] Localize all new picker/form strings in every supported locale.

### Tests

- [x] Unit-test status-aware no-snapshot failure response.
- [ ] Unit-test running sync conflict/throttle behavior.
- [x] Unit-test latest-first sort key.
- [ ] Unit-test projection diagnostics and exact-match miss diagnostics.
- [x] E2E-test user catalog credential failure using a provider fixture.
- [ ] E2E-test stored entries remain visible when latest sync fails after a successful snapshot.
- [ ] E2E-test picker lazy loading does not call model catalog before opening.
- [ ] E2E-test infinite scroll loads the next page without a button.
- [x] Update Storybook stories for picker state variants.

### Verification and Operations

- [ ] Run Python quality checks for azents.
- [ ] Run TypeScript lint/typecheck for azents-web.
- [ ] Run deterministic E2E tests.
- [ ] Open PR and monitor CI to green.
- [ ] Merge through PR, clean up branch, and monitor production deployment.
- [ ] Verify production scheduler heartbeat still succeeds.
- [ ] Verify production pods are ready and the web/app logs show no new model picker errors.
