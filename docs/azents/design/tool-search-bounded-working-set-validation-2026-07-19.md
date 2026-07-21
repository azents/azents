---
title: "Tool Search and Bounded Working Set Validation"
created: 2026-07-19
tags: [backend, frontend, engine, toolkit, llm, validation]
document_role: supporting
document_type: supporting-validation-report
migration_source: "docs/azents/design/tool-search-bounded-working-set-validation-2026-07-19.md"
---

# Tool Search and Bounded Working Set Validation

## Scope

This report validates [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-281) after Tool Search became an Agent-level opt-in capability. It covers Agent persistence and API propagation, generated clients, default-disabled compatibility behavior, enabled deferred Tool Search behavior, provider request compatibility budgets, the session-shared working set, frontend settings, and product-path E2E fixtures.

The validated stack shape is:

1. `feature/tool-search-design`
2. `feature/tool-search-plan`
3. `feature/tool-search-budget`
4. `feature/tool-search-catalog`
5. `feature/tool-search-agent-settings`
6. `feature/tool-search-runtime`
7. `feature/tool-search-frontend`
8. `feature/tool-search-validation`
9. `feature/tool-search-spec`
10. `feature/tool-search-cleanup`

The validation preserves [deterministic-260628/ADR](../adr/deterministic-260628-deterministic-catalog-and-mcp-snapshots.md) deterministic provider-facing ordering and snapshot-backed MCP discovery. It does not use live provider credentials or remote provider calls.

## Environment

- Date: July 19, 2026
- Repository: `azents/azents`
- Python interpreter: CPython 3.14.6
- Backend validation: local deterministic unit and integration fixtures
- Frontend validation: generated TypeScript client plus azents-web static and unit checks
- Product-path fixture: AIMock plus the registered test-only `runtime_hook_qa` Toolkit
- Docker-backed E2E: unavailable locally because the environment has no Docker Unix socket; a dedicated pull-request CI job runs the focused runtime-provider tests on `ubuntu-latest`
- External provider credentials: none

The product-path fixture requires the existing Docker-composed Azents public server, engine worker, PostgreSQL, Redis, AIMock, and runtime-hook QA provider. No external MCP server, cloud account, or live LLM is required.

## Commands and Results

### Database Migration Graph

```console
cd python/apps/azents
uv run alembic -c db-schemas/rdb/alembic.ini heads
uv run alembic -c db-schemas/rdb/alembic.ini history \
  -r 7e9b625b4c81:f81c4d3b1f17
```

Result: `f81c4d3b1f17` is the single head and directly follows `7e9b625b4c81`. The migration adds the non-null `agents.tool_search_enabled` column with a `false` server default and the checked revision file points at the new head.

### Focused Backend Regression Set

```console
cd python/apps/azents
uv run pytest -q \
  src/azents/engine/run/tool_budget_test.py \
  src/azents/engine/tooling/tool_search_test.py \
  src/azents/engine/events/tools_test.py \
  src/azents/engine/events/engine_adapter_test.py \
  src/azents/engine/events/litellm_responses_test.py \
  src/azents/engine/events/openai_responses_test.py \
  src/azents/engine/tools/mcp_base_test.py \
  src/azents/engine/tooling/toolkit_state_test.py \
  src/azents/engine/run/resolve_test.py \
  src/azents/rdb/models/agent_test.py \
  src/azents/services/agent/service_test.py
```

Result: 247 passed, 4 skipped. The skipped cases are existing environment-dependent tests; no deterministic Tool Search or Agent opt-in test was skipped.

### Full Backend Quality and Test Suite

```console
cd python/apps/azents
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
```

Results:

- Ruff: passed
- Format check: 987 files already formatted
- Pyright: 0 errors
- Pytest: 1,714 passed, 400 skipped, 5 existing dependency warnings

### Public OpenAPI and Generated Clients

```console
cd python/apps/azents
uv run python src/cli/dump_openapi.py

cd ../../../libs/azents-public-client
make generate
uv run pytest -q

cd ../../../typescript
pnpm run generate --filter=@azents/public-client
```

Results:

- Public OpenAPI regeneration included optional create/update fields and a required response field for `tool_search_enabled`.
- The tracked Python client retained only the six Agent request/response artifacts affected by this schema change; unrelated generator template drift was discarded.
- Python public client tests: 428 passed with 4 existing collection warnings.
- The generated TypeScript client contains the create, response, and update field types. Its generated directory is intentionally gitignored.

### azents-web Validation

```console
cd typescript
pnpm run format:check --filter=@azents/web
pnpm run lint --filter=@azents/web
pnpm run typecheck --filter=@azents/web
pnpm --filter @azents/web test
```

Results:

- Prettier check: passed
- ESLint: passed
- TypeScript typecheck: passed
- Unit tests: 45 passed
- All four modified locale JSON files parsed successfully.

### E2E Project Static Validation

```console
cd testenv/azents/e2e
uv run ruff check .
uv run ruff format --check .
uv run pyright .
python -m json.tool \
  src/support/aimock_fixtures/agents_md_loader.json >/dev/null
```

Results:

- Ruff: passed
- Format check: 48 files already formatted
- Pyright: 0 errors
- AIMock fixture JSON validation: passed

### Docker-backed Product-path E2E

```console
cd testenv/azents/e2e
uv run pytest -vv -s \
  src/tests/azents/public/test_runtime_hooks.py::TestRuntimeHooks::test_runtime_hooks_execute_through_public_chat_path \
  src/tests/azents/public/test_runtime_hooks.py::TestRuntimeHooks::test_tool_search_persists_deferred_probe_across_runs
```

Local result: both tests were blocked during shared fixture setup before Azents product code executed.

The Docker SDK could not fetch the server API version because the local Unix socket did not exist. The root exception was `FileNotFoundError: [Errno 2] No such file or directory`, surfaced as `docker.errors.DockerException`. This is an execution-environment blocker rather than a product assertion failure.

Pull-request CI includes a dedicated `ci-tool-search-runtime-provider-e2e-run` job on `ubuntu-latest`. It runs exactly these two tests when the runtime-hook test, AIMock fixture, or CI workflow changes, and its result gates the aggregate `ci-python-e2e` check.

## Product-path Fixture Coverage

The runtime-hook E2E now covers both rollout modes.

### Default-disabled Agent

1. The Agent is created without specifying `tool_search_enabled`.
2. Its first provider request includes the attached `rtqa_observe__runtime_hook_qa_probe` service tool.
3. The same request omits `tool_search`.
4. Existing observe, deny, and replacement hook behavior remains exercised; the search-dependent Agents are explicitly enabled.

### Enabled Agent

1. The Agent is created with `tool_search_enabled=true`.
2. The first model request exposes `tool_search` and omits `rtqa_tool_search__runtime_hook_qa_probe`.
3. AIMock calls `tool_search` for the runtime-hook QA probe.
4. The immediately following request exposes the activated deferred probe.
5. AIMock calls the probe and receives a terminal result.
6. A later AgentRun reuses the same AgentSession.
7. The later Run's first model request already exposes the probe from persisted Toolkit State.

The E2E reads AIMock request journals rather than inferring membership only from scripted responses. It accepts both direct Responses-style `name` declarations and nested `function.name` declarations when extracting client tool names.

## Deterministic Evidence

| Requirement | Evidence | Result |
| --- | --- | --- |
| New and existing Agents default to disabled | RDB default, migration server default, create input defaults, service forwarding tests | Passed |
| Agent create/update/response API carries and persists the setting | Public API and service mappers, deterministic repository write tests, OpenAPI, generated clients | Passed |
| `RunRequest` uses the resolved Agent snapshot | Resolve propagation and runtime request tests | Passed |
| Disabled mode exposes the complete catalog | Engine adapter integration test over deferred-classified service tools | Passed |
| Disabled mode injects no `tool_search` and does not mutate state | Engine adapter request and execution assertions | Passed |
| Enabled first call hides inactive deferred tools | Engine adapter integration tests | Passed |
| Tool Search activation affects the next prepared call | Prepared-call integration tests | Passed |
| Activated tools persist across AgentRuns in one Session | Toolkit State tests and AIMock journal E2E | Deterministic tests passed locally; focused Docker path gates pull-request CI |
| Unknown request-path limit remains unlimited | Compatibility registry and projection tests | Passed |
| xAI uses the verified 200 total-declaration rule | Rule matching and hosted-declaration accounting tests | Passed |
| Vertex Google/Gemini uses the conservative 128 declaration rule | Endpoint/family matching and counting-scope tests | Passed |
| Direct Gemini remains unmatched | Direct Gemini compatibility-key tests | Passed |
| Vertex Anthropic does not inherit Gemini rules | Developer/family separation tests | Passed |
| Equal-specificity rule conflicts fail | Registry validation tests | Passed |
| Search ranking is deterministic | BM25 ranking, metadata, result-limit, and tie-break tests | Passed |
| Working-set state stores final names only | Toolkit State codec and recency tests | Passed |
| Provider-facing order remains canonical | Projection and lowerer regression tests | Passed |
| Direct overflow fails before provider I/O | Typed preparation-failure tests | Passed |
| Prepared catalog and executor boundaries are immutable | In-flight catalog-change test plus rejection of a catalog-present tool omitted from the prepared projection before hooks, recency, or handler execution | Passed |
| MCP discovery remains snapshot-backed | Existing MCP snapshot regression set | Passed |
| Agent settings UI defaults off and submits the value | Form schema/container/component, stories, generated client typecheck | Passed |

## Failures Found and Fixes Applied

### Disabled compatibility behavior needed a separate runtime branch

Simply leaving the working set empty would still have injected `tool_search`, hidden service tools, and applied provider budgets. The adapter now branches before budget resolution and state loading. Disabled Agents use the complete canonical executable catalog and the unwrapped client-tool executor.

### The Agent repository initially dropped explicit Tool Search values

The public API and Agent service carried `tool_search_enabled`, but the repository initially omitted it when constructing the RDB row and the partial update statement. Enabled creates therefore fell back to the database default `false`, which the Docker product-path CI exposed when the first request showed the deferred probe directly. Create and update now persist explicit values, and deterministic repository tests inspect both the mapped RDB object and SQL update parameters.

### Prepared executors initially retained routes outside the visible projection

The provider request used the bounded projection, but the prepared executor initially retained the complete catalog. A model-emitted known final name could therefore reach a hidden deferred tool. Enabled prepared calls now use an outer allowlist that rejects names omitted from that request before runtime hooks, working-set recency, cancellation, or handler execution. The regression test invokes a catalog-present deferred tool from the first search-only request and verifies both failure and unchanged Toolkit State.

### The web router initially dropped the submitted Agent setting

The Agent form submitted `tool_search_enabled`, but the tRPC create and update handlers initially omitted it from the generated public-client request body. Both paths now forward the optional value. Generated-client type checking, ESLint, Prettier, and all 45 azents-web unit tests pass with the corrected routing.

### Existing runtime-hook fixtures called newly deferred tools directly

The deny and replacement fixtures now explicitly enable Tool Search and call `tool_search` before their deferred QA probe. The default observe Agent remains disabled and directly verifies legacy tool visibility.

### Living spec version metadata lagged behind changelog entries

The Toolkit and Agent Execution Loop changelogs recorded versions 58 and 108 while their frontmatter still reported 57 and 107. Validation corrected the frontmatter to match the promoted behavior.

### Python client regeneration produced unrelated template drift

The generator rewrote unrelated subscription and generated test artifacts. Review retained only the six Agent schema artifacts caused by `tool_search_enabled` and discarded unrelated drift. Newly added Markdown rows were normalized so repository whitespace checks pass.

## Implementation-to-ADR Comparison

| [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-282) decision | Implementation status | Evidence |
| --- | --- | --- |
| D1: one session-shared working set projected per prepared call | Implemented | Session Toolkit State plus model-path projection tests |
| D2: optional verified limits; absent means unlimited | Implemented | Compatibility registry and unmatched-path tests |
| D3: core tools direct; attached service operations deferred | Implemented when enabled | Classification policy and catalog tests |
| D4: search activates ranked results and updates recency | Implemented when enabled | BM25/search activation and capacity tests |
| D5: persist ordered final names and snapshot each call immutably | Implemented when enabled | State codec, reconciliation, and snapshot tests |
| D6: deterministic in-memory BM25 over current deferred catalog | Implemented when enabled | Search document, ranking, tie, and metadata tests |
| D7: fixed generic Tool Search schema | Implemented when enabled | Stable schema and prepared-call tests |
| D8: apply limits to provider-counted declarations | Implemented when enabled | Hosted/client counting-scope tests |
| D9: versioned code-owned request compatibility registry | Implemented when enabled | Rule provenance, specificity, conflict, and key tests |
| D10: Agent-level opt-in defaults disabled | Implemented | Persistence/API/UI propagation and disabled/enabled runtime tests |

## Current-spec Comparison

The spec-promotion changes document the validated current behavior:

- `docs/azents/spec/domain/toolkit.md` records the Agent setting, complete-catalog disabled path, and enabled search/state behavior.
- `docs/azents/spec/flow/agent-execution-loop.md` records `RunRequest` propagation and the separate immutable prepared-call branches.
- `docs/azents/spec/domain/model-catalog.md` limits the call-time compatibility-registry exception to Tool Search-enabled Agents.

No current spec removes [deterministic-260628/ADR](../adr/deterministic-260628-deterministic-catalog-and-mcp-snapshots.md) deterministic ordering or snapshot-backed MCP discovery.

## Validation Conclusion

All deterministic backend, generated-client, frontend, and static E2E validation sets pass. The implementation matches [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-283) including D10 and preserves [deterministic-260628/ADR](../adr/deterministic-260628-deterministic-catalog-and-mcp-snapshots.md) behavior. Docker-backed product-path execution remains unavailable locally because the Docker socket is absent. The two focused runtime-provider tests run in a dedicated Docker-capable pull-request CI job and gate `ci-python-e2e`; that job must pass before the stack is merge-ready.
