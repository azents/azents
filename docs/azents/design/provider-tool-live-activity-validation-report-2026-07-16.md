---
title: "Provider Tool Live Activity Validation Report"
created: 2026-07-16
tags: [backend, engine, frontend, llm, testing]
---

# Provider Tool Live Activity Validation Report

## Scope

This report validates the provider-neutral live activity implementation at frontend commit `dd9b966d`, including the backend pipeline inherited from `af30fb3d`.

The validation phase adds a deterministic AIMock Responses fixture that emits a `web_search_call` running output item, pauses before its completed item, and then completes with durable provider-tool output and assistant text. The E2E test uses only public REST and WebSocket product paths.

## Deterministic E2E Scenario

Fixture: `Provider tool live activity handoff`

Expected sequence:

1. A provider-tool live Event is broadcast with semantic name `web_search` and canonical status `running`.
2. `GET /chat/v1/sessions/{session_id}/live` restores the same deterministic live Event ID.
3. The live Event is updated to `completed` without changing identity.
4. A durable `provider_tool_call` with the same `call_id` is appended.
5. The live counterpart is removed after the durable append.
6. Final history contains one completed provider-tool call and the expected assistant response.
7. Final live state contains no provider-tool event for the completed call.

## Commands and Results

| Command | Working directory | Commit | Result | Notes |
| --- | --- | --- | --- | --- |
| `uv run ruff check --fix .` | `python/apps/azents` | `dd9b966d` | Pass | No backend lint errors. |
| `uv run ruff format .` | `python/apps/azents` | `dd9b966d` | Pass | 934 files unchanged. |
| `uv run pyright` | `python/apps/azents` | `dd9b966d` | Pass | 0 errors, 0 warnings. |
| `uv run pytest` | `python/apps/azents` | `dd9b966d` | Pass | 1,355 passed, 391 skipped. |
| `pnpm --filter @azents/web format` | `typescript` | `dd9b966d` | Pass | Web sources formatted. |
| `pnpm --filter @azents/web test` | `typescript` | `dd9b966d` | Pass | 22 tests passed. |
| `pnpm exec turbo run lint typecheck --filter=@azents/web` | `typescript` | `dd9b966d` | Pass | Lint and TypeScript checks passed. |
| `pnpm --filter @azents/web build-storybook` | `typescript` | `dd9b966d` | Pass | Provider-tool lifecycle stories compiled successfully. |
| `uv run ruff check --fix . && uv run ruff format . && uv run pyright .` | `testenv/azents/e2e` | `dd9b966d` | Pass | E2E fixture and test passed static validation. |
| `uv run pytest -vv src/tests/azents/public/test_provider_tool_live_activity.py` | `testenv/azents/e2e` | `dd9b966d` | Environment unavailable | Local runtime has no Docker socket. Test setup failed before fixture startup with `FileNotFoundError` for the Docker Unix socket. Required PR CI remains the authoritative deterministic E2E run. |

## Design and Spec Comparison

| Designed behavior | Implementation evidence | Result |
| --- | --- | --- |
| Provider-native stages become a provider-neutral canonical projection. | OpenAI and LiteLLM normalizer tests plus the shared accumulator tests. | Match |
| Running activity is visible before response completion. | Deterministic AIMock fixture pauses between running and completed provider-tool events; E2E asserts live WebSocket and REST state. | Covered by required CI E2E |
| Multiple calls, duplicates, enrichment, and terminal monotonicity are stable. | Accumulator unit tests and frontend semantic identity tests. | Match |
| Failed attempts remove provider activity before retry state. | Projector failed-attempt cleanup tests. | Match |
| Stop and terminal cleanup clear remaining live state. | Existing generic session terminal cleanup plus projector tests. | Match |
| `/live` restores the same provider-tool card. | New deterministic E2E asserts stable live Event ID and `call_id`. | Covered by required CI E2E |
| Durable history replaces live activity only after append. | Projector tests and new E2E WebSocket ordering assertions. | Covered by required CI E2E |
| Providers without progress are not guessed. | Normalizers emit activity only for observed native lifecycle or output-item events. | Match |
| Frontend uses semantic tool names rather than provider identity. | Projection tests and Storybook running/completed/failed/unknown states. | Match |
| Provider activity does not become an Azents client active tool. | Live projection remains in Redis and Run phase stays `streaming_model`. | Match |

## Required CI Policy

The validation PR must not be considered complete until its deterministic E2E job passes. The E2E fixture has no live credential dependency. Optional live-provider verification is not required for this feature and was not run.

## Findings

No implementation defect was found by backend, frontend, Storybook, or E2E static checks. Local dynamic E2E execution was blocked only by the unavailable Docker daemon; the added test is expected to execute in the repository's deterministic E2E CI environment.
