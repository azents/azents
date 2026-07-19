---
title: "Tool Search and Bounded Working Set Implementation Plan"
created: 2026-07-19
tags: [backend, frontend, engine, toolkit, llm, plan]
---

# Tool Search and Bounded Working Set Implementation Plan

## Source of Truth

- ADR: `docs/azents/adr/0147-tool-search-bounded-working-set.md`
- Current Toolkit spec: `docs/azents/spec/domain/toolkit.md`
- Current execution spec: `docs/azents/spec/flow/agent-execution-loop.md`
- Current model catalog spec: `docs/azents/spec/domain/model-catalog.md`
- Deterministic ordering and MCP snapshot constraint: `docs/azents/adr/0085-deterministic-tool-catalog-and-mcp-snapshots.md`
- Model snapshot constraint superseded only for the effective tool declaration limit: `docs/azents/adr/0067-model-catalog-projection-sync.md`

## Feature Summary

Tool Search is an Agent-level opt-in capability. New and existing Agents default to `tool_search_enabled=false`, preserving the complete existing model-visible client-tool catalog. Agent administrators can enable the capability through the Agent API and Capabilities settings UI.

When enabled, Azents keeps core execution tools directly visible, defers attached service Toolkit operations, exposes deterministic `tool_search`, and persists one ordered deferred-tool working set per AgentSession. Each prepared model call projects that shared working set under the current provider request path's verified declaration limit while preserving canonical provider-facing tool order.

Verified hard limits come from a code-owned provider-request compatibility registry. Unknown limits remain unlimited. The executable catalog, search index, provider-visible projection, and executor routing are immutable for one prepared call and rebuilt for the next call.

## Non-Goals

- Provider-native deferred tool loading protocols.
- Embedding or remote semantic search.
- A mutable Admin tool-limit configuration surface.
- Runtime provider-document scraping.
- Persisting copied tool schemas or handlers in Toolkit State.
- Changing Toolkit attachment, authorization, or MCP snapshot discovery behavior.
- Adding a product-wide soft tool cap when no verified provider limit exists.
- Model-scoped, provider-scoped, or workspace-scoped Tool Search toggles.

## Stack Shape

```text
main
← feature/tool-search-design
← feature/tool-search-plan
← feature/tool-search-budget
← feature/tool-search-catalog
← feature/tool-search-agent-settings
← feature/tool-search-runtime
← feature/tool-search-frontend
← feature/tool-search-validation
← feature/tool-search-spec
← feature/tool-search-cleanup
```

PR title prefix: `Tool Search`

## Phase 1 — Design ADR

- Branch: `feature/tool-search-design`
- PR title: `Tool Search [1/10]: Design`
- Scope:
  - Add ADR-0147 with accepted working-set, search, persistence, projection, compatibility-registry, prepared-call snapshot, and Agent-level opt-in decisions.
  - Define `tool_search_enabled=false` as the default and the complete legacy catalog as disabled behavior.
  - Do not change runtime behavior.
- Validation: documentation frontmatter/index pre-commit checks.

## Phase 2 — Multi-Phase Implementation Plan

- Branch: `feature/tool-search-plan`
- PR title: `Tool Search [2/10]: Implementation plan`
- Scope: add this plan with phase boundaries, dependencies, validation matrix, migration/client-generation requirements, rollout, and cleanup responsibilities.
- Validation: documentation frontmatter/index pre-commit checks.

## Phase 3 — Provider Request Tool-Budget Policy

- Branch: `feature/tool-search-budget`
- PR title: `Tool Search [3/10]: Add provider request tool budgets`
- Purpose: implement the code-owned compatibility registry and pure budget resolution independently of Agent configuration and Tool Search membership.
- Runtime changes:
  - Normalize provider, adapter/native request path, runtime model identifier, model developer, and model family.
  - Add reviewed rules with stable IDs, limits, counting scope, source metadata, and verification dates.
  - Apply xAI's documented 200 total-tool limit.
  - Apply a conservative 128 function-declaration rule only to Vertex AI Google/Gemini paths while recording Google's conflicting 128 and 512 documentation.
  - Leave direct Gemini API and Vertex-hosted non-Google models unmatched.
  - Resolve exact-model before family before endpoint rules and reject equal-specificity conflicts.
  - Define typed direct-tool overflow preparation failure.
- Data/API changes: none.
- Tests: rule matching, conflicts, counting scopes, hosted declarations, unknown unlimited behavior, and provider-family separation.

## Phase 4 — Deferred Catalog, Search, and Persistent Working Set

- Branch: `feature/tool-search-catalog`
- PR title: `Tool Search [4/10]: Add deferred catalog search`
- Purpose: represent direct/deferred executable tools, search the current deferred catalog, and persist session recency without changing provider request projection.
- Runtime changes:
  - Preserve final model-visible name as working-set identity.
  - Retain Toolkit source and searchable schema metadata.
  - Classify core capabilities as direct and attached service operations as deferred.
  - Keep required integration control tools such as GitHub `switch_installation` direct.
  - Add deterministic local BM25 search with final-name tie breaking.
  - Add stable `tool_search` schema with default 5 and maximum 10 results.
  - Store only schema version and ordered final tool names in session-bound Toolkit State.
  - Preserve absent names and use current catalog schemas/handlers when names return.
- Data/API changes: reuse existing `toolkit_states`; no migration.
- Tests: classification, search ranking/metadata/limits, state recency/reconciliation, and optimistic-lock retry.

## Phase 5 — Agent Settings and Public API

- Branch: `feature/tool-search-agent-settings`
- PR title: `Tool Search [5/10]: Add Agent opt-in settings`
- Purpose: persist explicit Agent administrator intent before runtime behavior is enabled.
- Data changes:
  - Add non-null `agents.tool_search_enabled` boolean with server default `false`.
  - Backfill existing Agents through the same default in a generated Alembic migration.
  - Update the checked schema revision.
- API/service changes:
  - Add required response and optional create/update request fields.
  - Carry the value through repository, service, and public API boundaries.
  - Regenerate the public OpenAPI document and Python/TypeScript clients.
- Tests:
  - RDB constructor and migration graph/default checks.
  - Service default forwarding and repository/API mapping coverage.
  - Generated client type validation.

## Phase 6 — Prepared-Call Projection and Runtime Integration

- Branch: `feature/tool-search-runtime`
- PR title: `Tool Search [6/10]: Integrate opt-in tool projection`
- Purpose: branch immutable model-call preparation on the resolved Agent setting.
- Disabled path:
  - Expose the complete executable client-tool catalog in canonical final-name order.
  - Do not inject `tool_search`.
  - Do not resolve or enforce compatibility budgets.
  - Do not load or mutate Tool Search working-set state.
  - Do not wrap execution with deferred recency tracking.
- Enabled path:
  - Resolve hosted/client built-ins before budget projection.
  - Load the session working set and add pinned `tool_search` when deferred tools exist.
  - Project direct tools first, then active deferred names in MRU order.
  - Fail direct overflow before provider I/O.
  - Activate search results for the next prepared call and refresh emitted deferred calls before hooks/handlers.
  - Preserve immutable prepared catalog/search/projection/executor boundaries and canonical final-name ordering.
- Tests:
  - Default-disabled complete catalog and no state mutation.
  - Enabled first-call hiding, next-call activation, recency, projection, overflow, hosted counting, and immutable routing.
  - `resolve_invoke_input` carries the Agent setting into `RunRequest`.

## Phase 7 — Agent Settings Frontend

- Branch: `feature/tool-search-frontend`
- PR title: `Tool Search [7/10]: Add Agent settings toggle`
- Purpose: expose the opt-in control to Agent administrators.
- Frontend changes:
  - Add a required boolean to Agent form state with create default `false`.
  - Load stored response state when editing.
  - Add the Tool Search switch to the Capabilities section with localized description.
  - Send the value through create/update tRPC and generated public-client calls.
  - Update AgentResponse story fixtures and the Agent form story.
- Tests and checks:
  - Generated client dependency regeneration.
  - Prettier, ESLint, and TypeScript typecheck for `@azents/web`.
  - Storybook static fixture coverage for the off state; edit-mode fixtures may opt in explicitly when needed.

## Phase 8 — Product-Path Validation

- Branch: `feature/tool-search-validation`
- PR title: `Tool Search [8/10]: Validate opt-in product behavior`
- E2E matrix:
  1. Create an Agent without the setting and verify its first request contains the attached service probe and omits `tool_search`.
  2. Create an Agent with `tool_search_enabled=true` and verify the first request contains `tool_search` but omits the deferred probe.
  3. Call search, verify the next request contains the probe, execute it, and complete the Run.
  4. Start a later AgentRun in the same AgentSession and verify persisted activation appears on its first request.
  5. Keep runtime-hook deny/replace scenarios enabled explicitly before their deferred probe calls.
- Fixture support:
  - Reuse AIMock request journals and the registered test-only `runtime_hook_qa` Toolkit.
  - No live provider, external MCP server, or cloud credential is required.
- Validation commands:
  - Focused and full backend Ruff, format, Pyright, and Pytest.
  - azents-web Prettier, ESLint, and typecheck.
  - E2E Ruff, format, Pyright, JSON validation, and focused Docker-backed tests.
- Evidence: update the dated validation report with environment, commands, results, blockers, fixes, and ADR/spec comparison.
- Failure policy: deterministic E2E assertion failures block the phase; Docker-unavailable setup is recorded as an environment blocker and remains required in Docker-capable CI.

## Phase 9 — Living Spec Promotion

- Branch: `feature/tool-search-spec`
- PR title: `Tool Search [9/10]: Promote living specs`
- Scope:
  - Update Toolkit spec with Agent opt-in configuration, disabled complete-catalog behavior, and enabled search/state behavior.
  - Update execution-loop spec with `RunRequest` propagation and disabled/enabled prepared-call branches.
  - Update model-catalog spec so the registry exception applies only on the enabled path.
  - Update code paths, `last_verified_at`, versions, and change histories.
- Validation: documentation checks plus the focused backend/frontend/E2E static set from Phase 8.

## Phase 10 — Plan Cleanup

- Branch: `feature/tool-search-cleanup`
- PR title: `Tool Search [10/10]: Remove implementation plan`
- Scope: delete only this temporary implementation plan after validation and spec promotion are current.
- Validation: documentation frontmatter/index pre-commit checks.

## Dependency Order

- Budget and catalog foundations are independent pure runtime building blocks.
- Agent settings must land before runtime integration so the runtime never enables Tool Search without stored administrator intent.
- Frontend depends on the public API/client phase and runtime semantics.
- Validation depends on backend, runtime, generated clients, and frontend wiring.
- Spec promotion follows successful validation; cleanup follows spec promotion.

## E2E Primary Validation Matrix

| Behavior | Primary verification | Fixture/prerequisite | Phase |
| --- | --- | --- | --- |
| New/default Agent exposes the complete service catalog and no `tool_search` | AIMock first-request journal | Registered `runtime_hook_qa` Toolkit | 8 |
| Enabled Agent hides inactive service tools and exposes `tool_search` | AIMock first-request journal | Explicit `tool_search_enabled=true` | 8 |
| Search activation exposes the deferred tool on the next call | AIMock second-request journal | Deterministic search fixture | 8 |
| Activated deferred tool executes successfully | Canonical client tool result | Existing QA probe handler | 8 |
| Activated tool survives a later AgentRun | Later request journal in same Session | Existing Toolkit State persistence | 8 |
| Disabled invocation does not mutate Tool Search state | Engine integration test | In-memory state store | 6 |
| Known hard limits never produce an oversized enabled request | Budget/projection tests | Deterministic rule fixtures | 3 and 6 |
| Unknown enabled request paths remain unlimited | Projection tests | No external dependency | 3 and 6 |
| MCP discovery remains snapshot-backed | Existing MCP regression tests | Existing fake MCP support | 8 |
| Agent settings round trip through UI/API | Typecheck plus API/service tests | Generated clients | 5 and 7 |

## Fixture and Prerequisite Requirements

- AIMock records must invoke `tool_search` before deferred deny/replace/tool-search probes.
- E2E Agent creation must explicitly enable Tool Search for search-dependent records.
- The default-disabled scenario must inspect provider request membership rather than infer it from scripted output.
- Docker-composed public server, worker, PostgreSQL, Redis, AIMock, and runtime-hook QA provider are required for product-path execution.
- No external provider credentials are required.

## Spec Impact Candidates

- `docs/azents/spec/domain/toolkit.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/domain/model-catalog.md`

## Rollout and Observability

- The feature ships default-disabled per Agent.
- Disabling preserves the complete pre-feature catalog and ignores retained session working-set state.
- Enabling takes effect when the next Agent run resolves the Agent snapshot; re-enabling may reuse still-valid session names.
- Enabled unknown request paths remain unlimited but still defer inactive service tools.
- Enabled preparation logs rule and aggregate projection counts; disabled preparation logs complete-catalog count.
- Provider rejection never automatically learns a limit.
- Rollback is the Agent toggle; stored Toolkit State remains harmless while disabled.

## Known Blockers and External Actions

- Local Docker-backed E2E is blocked when the Docker Unix socket is unavailable; Docker-capable CI remains required.
- Provider limit documentation must be rechecked whenever compatibility rules change.
- Generated Python client output must be reviewed to avoid unrelated generator drift in the Agent-settings PR.
