---
title: "Tool Search and Bounded Working Set Implementation Plan"
created: 2026-07-19
tags: [backend, engine, toolkit, llm, plan]
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

Azents will keep core execution tools directly visible, defer attached service Toolkit operations, expose a deterministic `tool_search` function, and persist one ordered deferred-tool working set per AgentSession. Each prepared model call will project that shared working set under the current provider request path's verified declaration limit while preserving canonical provider-facing tool order.

Verified hard limits will come from a code-owned provider-request compatibility registry. Unknown limits remain unlimited. The executable catalog, search index, provider-visible projection, and executor routing will be immutable for one prepared call and rebuilt for the next call.

## Non-Goals

- Provider-native deferred tool loading protocols.
- Embedding or remote semantic search.
- A mutable Admin tool-limit configuration surface.
- Runtime provider-document scraping.
- Persisting copied tool schemas or handlers in Toolkit State.
- Changing Toolkit attachment, authorization, or MCP snapshot discovery behavior.
- Adding a product-wide soft tool cap when no verified provider limit exists.

## Stack Shape

```text
main
← feature/tool-search-design
← feature/tool-search-plan
← feature/tool-search-budget
← feature/tool-search-catalog
← feature/tool-search-runtime
← feature/tool-search-validation
← feature/tool-search-spec
← feature/tool-search-cleanup
```

PR title prefix: `Tool Search`

## Phase 1 — Design ADR

- Branch: `feature/tool-search-design`
- PR title: `Tool Search [1/8]: Design`
- Scope:
  - Add ADR-0147 with accepted working-set, search, persistence, projection, compatibility-registry, and prepared-call snapshot decisions.
  - Do not change runtime behavior.
- Validation:
  - Documentation frontmatter/index pre-commit checks.

## Phase 2 — Multi-Phase Implementation Plan

- Branch: `feature/tool-search-plan`
- PR title: `Tool Search [2/8]: Implementation plan`
- Scope:
  - Add this plan with phase boundaries, dependencies, validation matrix, fixture requirements, rollout, and cleanup responsibilities.
  - Do not change runtime behavior.
- Provides for later phases:
  - Stable PR ownership and test responsibilities.

## Phase 3 — Provider Request Tool-Budget Policy

- Branch: `feature/tool-search-budget`
- PR title: `Tool Search [3/8]: Add provider request tool budgets`
- Purpose:
  - Implement the code-owned compatibility registry and pure budget resolution independent of Tool Search membership.
- Runtime changes:
  - Add a normalized request compatibility key containing provider, runtime adapter/lowering mode, runtime model identifier, model developer, and normalized model family.
  - Add versioned compatibility rules with stable rule IDs, maximum declarations, counting scope, authoritative source metadata, and verification date.
  - Add applicable xAI request rules with a 200 total-tool declaration limit.
  - Add a conservative 128 function-declaration rule only for Vertex AI request paths targeting Google/Gemini models, with rule metadata recording Google's conflicting official 128 and 512 sources and the 2026-07-19 verification date.
  - Leave direct Gemini API requests unmatched and unlimited until an authoritative hard declaration limit is verified.
  - Exclude Vertex-hosted Anthropic and other non-Google models from the Vertex Google/Gemini rule.
  - Resolve exact-model rules before family rules and endpoint rules; reject same-specificity conflicts.
  - Calculate effective client-function capacity after provider-hosted declarations that share the rule's counting scope.
  - Keep an absent match as unlimited.
  - Define a typed preparation error for direct-tool overflow; runtime integration occurs in Phase 5.
- Data/API changes:
  - No database migration.
  - No public API or generated client changes.
  - Saved `AgentModelSelection` capability snapshots remain unchanged; the registry is evaluated at prepared-call time.
- Tests:
  - Exact, family, endpoint, and unknown matching.
  - Same-specificity conflict rejection.
  - xAI total-tool hosted declaration accounting.
  - Vertex Google/Gemini function-only accounting.
  - Vertex Google/Gemini versus Vertex Anthropic separation.
  - Direct Gemini remains unmatched and unlimited.
  - Rule provenance captures the Vertex 128-versus-512 documentation conflict.
  - Unknown limit remains unlimited.

## Phase 4 — Deferred Catalog, Search, and Persistent Working Set

- Branch: `feature/tool-search-catalog`
- PR title: `Tool Search [4/8]: Add deferred catalog search`
- Purpose:
  - Represent direct and deferred executable tools, search the current deferred catalog, and persist session recency without changing model request projection yet.
- Runtime changes:
  - Preserve the final model-visible tool name as the working-set identity.
  - Retain Toolkit source metadata while building the executable catalog so search documents can include final name tokens, Toolkit slug/type/display name, description, parameter names/descriptions, and available routing metadata.
  - Classify auto-bound core execution/session-control tools as direct.
  - Classify DB-attached service Toolkit operations as deferred by default.
  - Keep required service control tools such as GitHub `switch_installation` direct through an explicit classification policy.
  - Add a deterministic local BM25 index over the current deferred executable catalog with final-name ascending tie breaking.
  - Add the stable `tool_search` schema with default result limit 5 and maximum 10.
  - Add a session-bound Toolkit State payload containing schema version and ordered final tool names only.
  - Add optimistic-lock-safe load, activation, and invocation-touch operations using the existing `toolkit_states` table.
  - Preserve absent names in recency state and use the current executable catalog entry when a name returns or its schema changes.
- Data/API changes:
  - Reuse the existing `toolkit_states` table; no migration.
  - No public API or generated client changes.
- Tests:
  - Direct/deferred/control-tool classification.
  - Search tokenization, BM25 ranking, deterministic ties, parameter metadata, and empty results.
  - Search limit validation and result serialization.
  - Activation ordering, duplicate refresh, invocation touch, absent-name retention, and optimistic-lock retry.
  - Catalog metadata changes invalidate the cached index key when caching is enabled.

## Phase 5 — Prepared-Call Projection and Runtime Integration

- Branch: `feature/tool-search-runtime`
- PR title: `Tool Search [5/8]: Integrate bounded tool projection`
- Purpose:
  - Apply the registry budget and session working set to every prepared model call and wire Tool Search activation into the following call.
- Runtime changes:
  - Resolve provider-hosted and client-executed built-in tools before budget projection.
  - Load the shared session working set for every prepared call.
  - Add `tool_search` as a pinned direct tool whenever deferred tools exist.
  - Project direct tools first and fill remaining explicit capacity from current available deferred names in MRU order.
  - With no verified limit, expose all currently active deferred tools without count truncation.
  - Fail preparation before provider I/O when pinned direct declarations exceed the explicit effective capacity.
  - Keep executor routing over the full executable catalog while provider-visible schemas use only the projected subset.
  - Make the prepared catalog, search index, projection, and executor one immutable call snapshot.
  - Have `tool_search` activate only results that can become visible under the current explicit capacity and report reductions.
  - Refresh deferred-tool recency before executing an emitted tool call, including hook denial, handler error, and tool-level failure paths.
  - Preserve canonical final-name ordering in lowerer input and keep LRU relevant only to membership.
  - Emit structured logs for matched compatibility rule ID, resolved limit, hosted count, direct count, active deferred count, and visible deferred count without logging tool arguments or credentials.
- Tests:
  - First call contains direct tools and `tool_search` but not inactive deferred tools.
  - Tool Search result changes the immediately following prepared call.
  - Invoked deferred tool becomes MRU regardless of result status.
  - Smaller and larger request-path limits project the same shared state without deleting its hidden tail.
  - Run-to-run catalog disappearance and return preserve recency.
  - Same-name schema changes use the current handler/schema.
  - Direct overflow fails before adapter invocation.
  - Provider-hosted declaration accounting is applied once and provider adapters do not independently truncate.
  - Prepared-call executor cannot execute a newly appeared tool that was not in its immutable snapshot.
  - Canonical provider-facing order remains stable for identical membership.

## Phase 6 — Product-Path Validation

- Branch: `feature/tool-search-validation`
- PR title: `Tool Search [6/8]: Validate product behavior`
- Purpose:
  - Run deterministic product-path validation, record evidence, and fix behavior discovered outside focused unit tests.
- E2E fixture support:
  - Extend the deterministic AIMock fixture with a two-turn sequence:
    1. assert and call `tool_search` for the registered test Toolkit probe;
    2. call the activated deferred probe and return a terminal response.
  - Use the existing testenv-only `runtime_hook_qa` registered Toolkit as a deterministic deferred service Toolkit. No external credentials are required.
  - Record AIMock request journals to verify that the deferred probe schema is absent before search and present after activation.
  - Start a later AgentRun in the same Session and verify the activated probe remains visible from persisted Toolkit State.
- Validation commands:
  - Focused Ruff, Pyright, and Pytest for changed backend modules.
  - Full `python/apps/azents` Ruff, Pyright, and Pytest.
  - Focused testenv E2E for Tool Search.
  - Existing Toolkit, runtime hook, MCP snapshot, provider lowering, and engine execution regressions.
- Evidence document:
  - Add a dated validation report under `docs/azents/design/` containing commands, environment, results, fixture prerequisites, failures found, fixes applied, and an implementation-versus-ADR matrix.
- Failure policy:
  - Deterministic E2E fixture failures block this phase.
  - Live provider calls are not required and must not be used as a CI prerequisite.

## Phase 7 — Living Spec Promotion

- Branch: `feature/tool-search-spec`
- PR title: `Tool Search [7/8]: Promote living specs`
- Purpose:
  - Update current behavior documentation only after implementation and validation are complete.
- Scope:
  - Update `docs/azents/spec/domain/toolkit.md` with direct/deferred exposure, Tool Search metadata, Toolkit State identity, and invocation recency behavior.
  - Update `docs/azents/spec/flow/agent-execution-loop.md` with prepared-call projection, immutable executor snapshot, overflow failure, and next-call activation behavior.
  - Update `docs/azents/spec/domain/model-catalog.md` to document the narrow call-time compatibility-registry exception to saved snapshot semantics.
  - Update code paths, `last_verified_at`, spec versions, and change histories.
  - Run spec review and accept pre-commit-generated documentation index changes.
- Validation:
  - Documentation frontmatter/index checks.
  - Re-run the focused runtime and E2E validation set used by Phase 6.

## Phase 8 — Plan Cleanup

- Branch: `feature/tool-search-cleanup`
- PR title: `Tool Search [8/8]: Remove implementation plan`
- Purpose:
  - Remove this temporary plan after code, validation evidence, and living specs are complete.
- Scope:
  - Delete only `docs/azents/plans/tool-search-bounded-working-set-implementation-plan.md` and accept generated documentation index changes.
  - Do not change behavior or refactor implementation code.
- Validation:
  - Documentation frontmatter/index checks.

## Dependency Order

- Phase 3 depends only on the accepted ADR and can be reviewed as a pure compatibility policy.
- Phase 4 depends on the state and catalog contracts identified by the ADR but not on Phase 3 runtime integration.
- Phase 5 combines Phase 3 budgets with Phase 4 catalog/search/state behavior.
- Phase 6 validates the complete implementation from Phase 5.
- Phase 7 depends on successful Phase 6 evidence.
- Phase 8 depends on completed spec promotion.

## E2E Primary Validation Matrix

| Behavior | Primary verification | Fixture/prerequisite | Phase |
| --- | --- | --- | --- |
| Inactive service tool is absent from first model request | AIMock request journal assertion | Registered `runtime_hook_qa` Toolkit | 6 |
| `tool_search` is directly visible and callable | AIMock scripted function call and transcript result | New deterministic AIMock sequence | 6 |
| Search activation exposes the deferred tool on the next call | Second AIMock request journal assertion | Same sequence and Session | 6 |
| Activated deferred tool executes successfully | Canonical client tool call/result transcript | Existing QA probe handler | 6 |
| Activated tool survives a later AgentRun | Later request journal in same Session | Existing Toolkit State persistence | 6 |
| Tool membership stays canonical | Focused engine/lowerer integration test | No external dependency | 5 |
| Known hard limits never produce an oversized request | Focused budget/projection tests | Deterministic rule fixtures | 3 and 5 |
| Unknown model limits remain unlimited | Focused projection test | No external dependency | 3 and 5 |
| MCP discovery remains off the run critical path | Existing MCP snapshot regression tests | Existing fake MCP support | 6 |

## Fixture and Prerequisite Requirements

- Add deterministic AIMock fixture records for Tool Search and the activated QA probe.
- Reuse the existing testenv-only registered `runtime_hook_qa` Toolkit provider.
- No external MCP server, cloud account, provider credential, or live LLM is required.
- The E2E environment must enable the existing runtime hook QA provider and AIMock journal endpoint, as current runtime-hook E2E tests already require.
- Fixture matching must assert request tool membership rather than relying only on the scripted response sequence.

## Spec Impact Candidates

- `docs/azents/spec/domain/toolkit.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/domain/model-catalog.md`

No public API schema, database migration, generated client, frontend, Helm, or runtime-provider spec changes are expected.

## Rollout and Observability

- The feature ships as common engine behavior without a user-facing toggle.
- Unknown request paths preserve unlimited count semantics but still defer inactive service tools.
- Structured preparation logs identify the matched compatibility rule and aggregate counts.
- Direct-tool overflow produces a typed pre-provider failure with provider, model, rule ID, direct count, and effective capacity; it does not silently drop tools.
- Provider rejection does not automatically learn or persist a limit.
- Rollback removes projection/search behavior while leaving Toolkit State rows harmless and session-scoped; no schema rollback is required.

## Known Blockers and External Actions

- No known external blocker.
- Official provider limit documentation must be rechecked when Phase 3 rules are authored; each shipped rule must retain a stable source reference and verification date.
- If current testenv AIMock cannot assert request tool membership for a scripted record, add that deterministic matcher before claiming E2E coverage rather than weakening the assertion.
