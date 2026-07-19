---
title: "Tool Search and Bounded Working Set Validation"
created: 2026-07-19
tags: [backend, engine, toolkit, llm, validation]
---

# Tool Search and Bounded Working Set Validation

## Scope

This report validates the implementation of ADR-0147 through the provider request compatibility registry, deferred executable catalog, deterministic Tool Search index, session-shared working set, prepared-call projection, and runtime invocation boundaries.

The validated stack is:

1. `feature/tool-search-budget`
2. `feature/tool-search-catalog`
3. `feature/tool-search-runtime`
4. `feature/tool-search-validation`

The validation preserves ADR-0085 deterministic provider-facing ordering and snapshot-backed MCP discovery. It does not use live provider credentials or remote provider calls.

## Environment

- Date: July 19, 2026
- Repository: `azents/azents`
- Python interpreter: CPython 3.14.6
- Backend validation: local deterministic unit and integration fixtures
- Product-path fixture: AIMock plus the registered test-only `runtime_hook_qa` Toolkit
- Docker-backed E2E: unavailable because the local environment has no Docker Unix socket
- External provider credentials: none

The product-path fixture requires the existing Docker-composed Azents public server, engine worker, PostgreSQL, Redis, AIMock, and runtime-hook QA provider. No external MCP server, cloud account, or live LLM is required.

## Commands and Results

### Focused Backend Regression Set

```console
cd python/apps/azents
uv run pytest \
  src/azents/engine/run/tool_budget_test.py \
  src/azents/engine/tooling/tool_search_test.py \
  src/azents/engine/events/tools_test.py \
  src/azents/engine/events/engine_adapter_test.py \
  src/azents/engine/events/litellm_responses_test.py \
  src/azents/engine/events/openai_responses_test.py \
  src/azents/engine/tools/mcp_base_test.py \
  src/azents/engine/tooling/toolkit_state_test.py
```

Result: 227 passed, 4 skipped.

The skipped tests are existing environment-dependent Toolkit State cases. No deterministic Tool Search or provider-budget test was skipped.

### Full Backend Quality and Test Suite

```console
cd python/apps/azents
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

Results:

- Ruff: passed
- Format check: 974 files already formatted
- Pyright: 0 errors
- Pytest: 1,592 passed, 397 skipped, 5 existing dependency warnings

### E2E Project Static Validation

```console
cd testenv/azents/e2e
uv run ruff check src/tests/azents/public/test_runtime_hooks.py
uv run ruff format --check src/tests/azents/public/test_runtime_hooks.py
uv run pyright .
python -m json.tool src/support/aimock_fixtures/agents_md_loader.json >/dev/null
```

Results:

- Ruff: passed
- Format check: passed
- Pyright: 0 errors
- AIMock fixture JSON validation: passed

### Focused Docker-backed Product-path E2E

```console
cd testenv/azents/e2e
uv run pytest -vv -s \
  src/tests/azents/public/test_runtime_hooks.py::TestRuntimeHooks::test_tool_search_persists_deferred_probe_across_runs
```

Result: blocked during fixture setup before Azents product code executed.

The Docker SDK failed while fetching the server API version because the local Unix socket did not exist. The root exception was `FileNotFoundError: [Errno 2] No such file or directory`, surfaced as `docker.errors.DockerException`. This is an execution-environment blocker rather than a product assertion failure. The focused E2E remains a required Docker-capable CI check for this stack.

## Product-path Fixture Coverage

The deterministic AIMock sequence exercises two AgentRuns in one AgentSession:

1. The first model request exposes `tool_search` and omits `rtqa_tool_search__runtime_hook_qa_probe`.
2. AIMock calls `tool_search` for the runtime-hook QA probe.
3. The immediately following request exposes the activated deferred probe.
4. AIMock calls the probe and receives a terminal result.
5. A later AgentRun reuses the same AgentSession.
6. The later Run's first model request already exposes the probe from persisted Toolkit State.

The E2E reads AIMock request journals rather than inferring membership only from scripted responses. It accepts both direct Responses-style `name` declarations and nested `function.name` declarations when extracting client tool names.

The existing runtime-hook deny and output-replacement scenarios were also updated to search for their deferred QA probe before calling it. This preserves their original hook assertions under the new exposure policy instead of making the QA Toolkit artificially direct.

## Deterministic Evidence

| Requirement | Evidence | Result |
| --- | --- | --- |
| Unknown request-path limit remains unlimited | Compatibility registry and prepared-call projection tests leave unmatched paths untruncated | Passed |
| xAI uses the verified 200 total-declaration rule | Rule matching and hosted-declaration accounting tests | Passed |
| Vertex Google/Gemini uses the conservative 128 function-declaration rule | Endpoint/family matching and counting-scope tests | Passed |
| Direct Gemini API remains unmatched | Direct Gemini compatibility-key tests | Passed |
| Vertex Anthropic does not inherit Gemini rules | Developer/family separation tests | Passed |
| Equal-specificity rule conflicts fail deterministically | Registry validation tests | Passed |
| Direct and deferred classification is explicit | Catalog classification tests, including required service control tools | Passed |
| Search ranking is deterministic | BM25 ranking, tokenization, metadata, limit, and final-name tie-break tests | Passed |
| Working-set state stores final names only | Toolkit State codec and recency tests | Passed |
| Absent names retain recency and recover | State reconciliation tests | Passed |
| First prepared call hides inactive deferred tools | Engine adapter integration tests | Passed |
| Tool Search activation affects the next prepared call | Prepared-call integration tests | Passed |
| Actual invocation refreshes MRU before hook denial or handler failure | Invocation-path tests | Passed |
| Provider-facing order is canonical by final name | Projection and lowerer regression tests | Passed |
| Explicit direct overflow fails before provider I/O | Typed preparation-failure tests with adapter spy | Passed |
| Provider-hosted declarations are counted once | Budget/projection and adapter regression tests | Passed |
| Prepared catalog, index, projection, and executor are immutable | In-flight catalog-change and executor-routing tests | Passed |
| MCP discovery remains snapshot-backed and off the run critical path | Existing MCP snapshot regression set | Passed |
| Product-path membership and persistence | New AIMock journal E2E | Locally blocked before setup; required in Docker-capable CI |

## Failures Found and Fixes Applied

### Existing runtime-hook fixtures called a newly deferred tool directly

The `runtime_hook_qa` Toolkit is an attached service Toolkit and is therefore deferred by default. Its existing deny and replace AIMock records assumed the QA probe was present in the first request. Under ADR-0147 that scripted call would no longer be valid.

The fixtures now call `tool_search` first, then call the activated probe. The hook behavior under test remains unchanged.

### Product-path persistence evidence was missing

Focused engine tests proved working-set persistence and next-call projection, but there was no product-path assertion over actual provider request journals. Validation added an E2E that checks initial absence, next-call activation, probe execution, same-Session reuse, and later-Run first-request visibility.

### E2E journal typing needed explicit runtime narrowing

AIMock and Session HTTP responses are untyped JSON. The new helpers now narrow list/object payloads before accessing request bodies and run state, keeping the E2E project strict under Pyright without weakening the assertions.

No runtime implementation defect remained after these fixture and validation additions.

## Implementation-to-ADR Comparison

| ADR-0147 decision | Implementation status | Evidence |
| --- | --- | --- |
| D1: one session-shared working set projected per prepared call | Implemented | Session Toolkit State plus model-path projection tests |
| D2: optional verified limits; absent means unlimited | Implemented | Compatibility registry and unmatched-path tests |
| D3: core tools direct; attached service operations deferred | Implemented | Classification policy and catalog tests |
| D4: search activates ranked results and updates recency | Implemented | BM25/search activation and capacity-reduction tests |
| D5: persist ordered final names and snapshot each call immutably | Implemented | State codec, reconciliation, and in-flight snapshot tests |
| D6: deterministic in-memory BM25 over current deferred catalog | Implemented | Search document, ranking, tie, and metadata-hash tests |
| D7: fixed generic Tool Search schema | Implemented | Stable schema and prepared-call tests |
| D8: apply limits to provider-counted declarations | Implemented | Hosted/client counting-scope tests |
| D9: versioned code-owned request compatibility registry | Implemented | Rule provenance, specificity, conflict, and request-key tests |

## Current-spec Comparison

| Current spec | Missing behavior requiring promotion |
| --- | --- |
| `docs/azents/spec/domain/toolkit.md` | Direct/deferred exposure classification, Tool Search searchable metadata, session Toolkit State identity and recency, and absent-name reconciliation |
| `docs/azents/spec/flow/agent-execution-loop.md` | Prepared-call budget resolution, pinned direct overflow failure, immutable catalog/index/projection/executor snapshot, next-call activation, and canonical membership ordering |
| `docs/azents/spec/domain/model-catalog.md` | Narrow call-time compatibility-registry exception to otherwise saved model-selection snapshot semantics |

No current spec requires removal of ADR-0085 deterministic ordering or snapshot-backed MCP discovery. The dedicated spec-promotion phase must add the missing contracts while preserving those rules.

## Validation Conclusion

The deterministic backend and static E2E validation sets pass. The implementation matches ADR-0147 and preserves ADR-0085 behavior. The only unavailable local evidence is Docker-backed product-path execution, blocked before setup by the absent Docker socket. The new focused E2E is ready for Docker-capable CI and must pass there before the stack is considered merge-ready.
