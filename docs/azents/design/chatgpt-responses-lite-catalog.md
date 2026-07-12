---
title: "ChatGPT Responses Lite Catalog Integration"
created: 2026-07-12
updated: 2026-07-12
implemented: 2026-07-12
tags: [backend, engine, model-catalog, chatgpt-oauth]
---

# ChatGPT Responses Lite Catalog Integration

## Problem

ChatGPT subscription models can require either the standard Responses request contract or the Responses Lite request contract. Model names are not a stable protocol signal, and LiteLLM does not automatically discover or lower the Responses Lite contract for ChatGPT OAuth models.

Azents already stores model selections as immutable Agent snapshots and already separates system catalogs from provider-integration catalogs. ChatGPT OAuth currently uses the shared system catalog projected from LiteLLM metadata, so it cannot represent account-visible models or the backend `use_responses_lite` capability.

## Goals

- Discover account-visible ChatGPT models from the authenticated Codex backend model catalog.
- Select the Responses transport from backend metadata rather than model-name allowlists.
- Reuse the existing integration catalog, snapshot, sync-attempt, picker, and Agent model-selection snapshot infrastructure.
- Lower Responses Lite requests in Azents while continuing to use LiteLLM for transport and streaming response parsing.
- Preserve Azents client identity and existing transcript replay semantics.

## Non-goals

- Do not change Agent model-selection snapshot semantics.
- Do not update existing Agent snapshots after a catalog refresh.
- Do not upgrade LiteLLM as part of this feature.
- Do not switch to LiteLLM's native `chatgpt/` provider.
- Do not impersonate the Codex CLI client identity.
- Do not retry a failed Responses Lite request with the standard Responses contract.

## Current Behavior

- ChatGPT OAuth model choices come from the system catalog projected from LiteLLM OpenAI metadata.
- User-scoped integration catalog sync is supported for AWS Bedrock and Google Vertex AI.
- Agent and Workspace model selections copy normalized catalog capabilities into immutable selection snapshots.
- The Responses lowerer uses the saved model capability snapshot supplied by `RunRequest`.

## Design

### Account-scoped model discovery

ChatGPT OAuth integration sync calls the authenticated Codex backend model endpoint:

```text
GET https://chatgpt.com/backend-api/codex/models?client_version=0.144.0
```

The request uses the integration access token, account identifier, and Azents client identity. Selectable candidates must be advertised as API-supported and picker-visible by the backend.

The backend model metadata is authoritative for:

- account visibility;
- Responses Lite selection;
- supported reasoning effort levels;
- parallel tool-call support;
- context window and input modalities when present;
- tool mode and minimum client version diagnostics.

LiteLLM metadata is not required for a ChatGPT backend model to remain selectable. This prevents newly rolled out ChatGPT models from being hidden while LiteLLM metadata lags behind.

### Catalog lifecycle

ChatGPT OAuth reuses the existing integration catalog lifecycle:

- initial sync after OAuth connection completes;
- initial sync after integration update;
- explicit user-triggered sync;
- duplicate-running attempt protection;
- failed-attempt state without replacing the last successful snapshot;
- stored catalog reads without request-time provider calls.

The existing ChatGPT system catalog remains the fallback before an integration catalog exists. Once an integration catalog is created, its state and snapshot are authoritative for that integration.

### Capability projection and snapshot semantics

`use_responses_lite` is normalized into the model compatibility capability contract. Model selection copies that capability into the existing Agent or Workspace model selection snapshot.

Catalog refreshes do not mutate existing selections. Runtime transport selection uses the saved model capability snapshot. Users obtain refreshed transport metadata by selecting the model again through the current catalog.

### Responses Lite lowering

When the provider is ChatGPT OAuth and the saved capability requires Responses Lite, the Responses lowerer:

1. moves tools from the top-level request into an `additional_tools` developer input item;
2. moves instructions into a developer message input item;
3. removes image `detail` fields from request input items;
4. sets `parallel_tool_calls` to `false`;
5. sets `reasoning.context` to `all_turns` while preserving configured reasoning effort;
6. uses the session identifier as the prompt cache key;
7. keeps `store=false`, streaming, encrypted reasoning content, and existing transcript replay behavior;
8. adds the Responses Lite compatibility headers using the Azents session identifier.

Standard ChatGPT OAuth models and every other provider retain the existing lowering path.

### Request identity and compatibility headers

Azents uses its own identity:

```text
originator: azents
user-agent: azents/<version>
```

Responses Lite requests additionally include:

```text
version: 0.144.0
session-id: <Azents session UUID>
x-session-affinity: <Azents session UUID>
x-openai-internal-codex-responses-lite: true
```

`ChatGPT-Account-Id` remains derived from the connected integration. No secondary session mapping is introduced.

## Error Handling

- Provider listing authentication, permission, protocol, and availability failures become the existing integration catalog failed-attempt state.
- A failed sync preserves the last successful catalog snapshot.
- A model absent from the stored selectable catalog cannot be newly selected.
- Runtime uses the saved Agent snapshot and does not query the model catalog.
- Responses Lite provider failures follow the existing model-call error path without standard-contract retry.

## Security

- OAuth access and refresh tokens remain encrypted integration secrets.
- Catalog responses store model metadata but never token values.
- Logs, API responses, tests, and PR artifacts must not expose OAuth tokens.
- Listing and model-call requests use the account identifier only as the provider-required header.

## Rollout

The feature ships in one pull request because it extends an existing catalog and lowerer boundary without a data migration. Existing model capability JSON remains forward-compatible through Pydantic defaults. Existing Agent snapshots remain unchanged and therefore continue to use the standard Responses contract until a model is selected again with Responses Lite metadata.

## Test Strategy

### Backend unit and integration tests

- Normalize ChatGPT backend model metadata, including `use_responses_lite=true` and `false`.
- Filter non-API or hidden backend models.
- Preserve ChatGPT models that have no LiteLLM metadata entry.
- Verify integration catalog sync success, failure state, and snapshot preservation.
- Verify OAuth completion and integration update schedule initial catalog sync.
- Verify standard Responses lowering remains unchanged.
- Verify Responses Lite instructions, tools, reasoning context, parallel-tool setting, prompt cache key, image normalization, and headers.
- Verify function-call and transcript replay shapes remain unchanged.

### Frontend validation

- Verify ChatGPT OAuth integrations expose the existing catalog sync control and catalog states.
- Run formatting, linting, type checking, and build checks for affected TypeScript workspaces.

### E2E primary validation matrix

| Behavior | Primary verification | Fixture or prerequisite |
|---|---|---|
| Integration-first picker state and manual sync | Existing deterministic integration-catalog E2E flow, exercised with the ChatGPT sync-capable provider UI state | Reuse the stored deterministic catalog fixture; no ChatGPT credential is required |
| Account catalog normalization and filtering | Backend integration test with a mocked Codex `/models` response | Mock access token and account id; never use a live token in CI |
| Saved capability selects standard or Lite transport | Lowerer and adapter integration tests that inspect the complete wire request | Static transcript, tools, image content, and capability snapshots |
| Failed sync preserves the last successful snapshot | Existing catalog repository/service failure-state coverage plus ChatGPT listing failure injection | Existing catalog database fixture |

No new testenv credential fixture is required. The product-visible picker states already use the provider-independent deterministic catalog fixture, while the ChatGPT endpoint and Responses Lite wire contract are more deterministically verified below the browser boundary with mocked HTTP and stream adapters.

### Evidence and CI policy

Validation evidence records commands and pass/fail summaries without request authorization values, OAuth payloads, or account identifiers. CI runs deterministic Python and TypeScript checks only. Optional live validation may use an existing temporary OAuth credential, but it must be explicitly enabled, must redact all credential material, and must be skipped rather than failed when the credential prerequisite is absent. A live test failure after the prerequisite is confirmed is a feature validation failure, not an allowed skip.

## Alternatives Considered

### Hard-coded model allowlist

Rejected because backend model rollout and protocol metadata can change independently of Azents releases.

### Runtime model-catalog lookup

Rejected because it changes the accepted immutable Agent model-selection snapshot semantics and adds provider dependency to model execution.

### LiteLLM-native ChatGPT provider

Rejected for this feature because the current provider does not automatically implement the Responses Lite lowering contract and injects client behavior that does not match Azents identity and prompt ownership.
