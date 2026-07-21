---
title: "Subagent Inherit testenv QA Report"
tags: [testing, backend, engine]
created: 2026-04-24
updated: 2026-04-24
implemented: 2026-04-24
document_role: supporting
document_type: supporting-validation-report
migration_source: "docs/azents/design/subagent-inherit-testenv-report-2026-04-24.md"
---

# Subagent Inherit testenv QA Report

Records QA result performed in Phase 8 based on design document [`subagent-inherit.md`](./subagent-inherit.md) §"testenv QA scenarios".

## 1. QA Strategy

- **Prioritize integration/unit level verification**. Actual LLM end-to-end calls were not performed due to session time/cost constraints. All non-deterministic I/O of Handler (DB / engine / event store) was replaced with mocks and only **pure branch decision logic** was fixed with unit tests.
- **Extract internal branch helpers from Handler**. Refactored 3 branches in `engine/tools/subagent.py` — model source / toolkit source / main-only filter — into pure functions to secure testability.
- **Snapshot verification requiring actual LLM calls** (live tool list check, actual model identifier check) is recommended to be manually executed in user environment exactly following runbook §5 order (⚠️ MANUAL-RECOMMENDED).

## 2. TC Verdict Matrix

| TC | Title | Verdict | Evidence |
|----|------|---------|------|
| TC1 | Toolkit inherit (`mode='all'`) | ✅ PASS-BY-UNIT + ⚠️ MANUAL (LLM) | §3.1 |
| TC2 | Model inherit (NULL = inherit) | ✅ PASS-BY-UNIT + ⚠️ MANUAL (LLM) | §3.2 |
| TC3 | Exclude main-only toolkit | ⏸ DEFERRED | §3.3 |
| TC4 | Exclusive inherit (ignore own toolkit) | ✅ PASS-BY-UNIT + ⚠️ MANUAL (LLM) | §3.4 |
| TC4-B | `mode='none'` — use own toolkit | ✅ PASS-BY-UNIT | §3.5 |
| TC5 | Default regression | ✅ PASS-BY-UNIT | §3.6 |

## 3. Evidence by TC

### 3.1 TC1 — Toolkit inherit (`mode='all'`)

**Branch logic verification**:

- `engine/tools/subagent.py::resolve_toolkit_source_agent_id` helper — returns `parent_agent_id` or `subagent_id` depending on subagent.`toolkit_inherit_mode`.
- Test:
  `src/nointern/engine/tools/subagent_inherit_test.py::TestResolveToolkitSourceAgentId::test_returns_parent_when_mode_all`
  — confirms parent_agent_id is returned when mode=ALL.

**Handler path verification**:

- Handler (`engine/tools/subagent.py:335-348`) passes return value of this helper as first argument to `resolve_agent_tools(toolkit_source_agent_id, ...)`.
- `resolve_agent_tools` queries only DB-registered toolkit of that agent with `agent_toolkit_repository.list_by_agent(session, agent_id)` (`services/engine/run/resolve.py:449`).
- Therefore, when mode=ALL, only parent's `agent_toolkits` are resolved and subagent's own toolkit is not queried.

**Execution result**: `uv run pytest src/nointern/engine/tools/subagent_inherit_test.py -v` all pass (8/8).

**Recommended auxiliary verification (⚠️ MANUAL)**: After attaching GitHub toolkit to Parent, call mode=ALL subagent and confirm actual `github_*` tool call appears in LLM log following runbook §4 TC1.

### 3.2 TC2 — Model inherit (subagent `llm_provider_*_id IS NULL`)

**Branch logic verification**:

- `engine/tools/subagent.py::resolve_model_source_agent_id` helper — returns `parent_agent_id` if subagent `llm_provider_model_id` is NULL, otherwise returns `None`.
- Test:
  `subagent_inherit_test.py::TestResolveModelSourceAgentId` (2 cases — NULL + NOT NULL).

**Resolve helper verification**:

- `engine/run/resolve.py::resolve_invoke_input_with_model_source` loads integration/model from subagent or parent depending on `model_source_agent_id` branch.
- Test: `services/agent_runtime/resolve_test.py::TestResolveInvokeInputWithModelSource`
  — 4 cases (subagent-only / parent-source / parent NULL error / parent missing).
- Wrapper regression:
  `TestResolveInvokeInputWrapper::test_wrapper_delegates_with_null_model_source`.

**Pair validation (auxiliary — `[subagent-model-pair]` rule)**:

- Whether partial NULL returns 400 `InvalidModelPair`:
  `services/agent/service_test.py::TestAgentServiceSubagentModelPairValidation`
  — 6 cases (integration only / model only / partial fields / all null success / update partial / update all null success).

**Execution result**: all related tests pass.

**Recommended auxiliary verification (⚠️ MANUAL)**: After actual subagent call with Opus parent + NULL subagent, confirm model identifier in `RunComplete` event is `claude-opus-4-7` (runbook §4 TC2 procedure).

### 3.3 TC3 — Exclude Main-only toolkit

**Reason DEFERRED**:

- `MAIN_ONLY_TOOLKIT_TYPES` is currently `frozenset()` (empty set) — filter has no effect in actual execution.
- By design, `memory` / `schedule` / `subagent` / `background_task` are already structurally blocked by worker dynamic injection or automatic binding path, not DB-registered (see design document DP7).
- When MCP-based main-only toolkit is added, fill constant and reactivate TC3.

**Filter behavior contract verification**:

- `engine/tools/subagent.py::filter_main_only_toolkits` helper — excludes main-only type only when `mode=ALL`. If `mode=NONE`, returns as-is.
- Test: `subagent_inherit_test.py::TestFilterMainOnlyToolkits` — 4 cases
  (mode=NONE return all / mode=ALL empty constant return all / mode=ALL constant monkey-patched to include "memory" filters it / mode=NONE ignores constant).

**Execution result**: all 4 cases pass. When constant is later filled, mode=ALL branch filtering is fixed with monkey-patch based test.

### 3.4 TC4 — Exclusive inherit

**Branch logic verification**:

- `resolve_toolkit_source_agent_id(mode=ALL)` → `parent_agent_id`. Because `resolve_agent_tools` target is parent, subagent's own `agent_toolkits` are **not included in query path at all**.
- No merge / dedup path (DP6 exclusive design).
- Test:
  `subagent_inherit_test.py::TestResolveToolkitSourceAgentId::test_returns_parent_when_mode_all`.

**Execution result**: Pass. Exclusion of subagent own toolkit is structurally guaranteed because "target agent_id is parent, so subagent's DB row is not queried."

**Recommended auxiliary verification (⚠️ MANUAL)**: With Parent `github:org-A`, Subagent `github:personal` + `notion:x` attached and called in mode=ALL, confirm tool list has no `notion_*` and credential is `org-A` (runbook §4 TC4).

### 3.5 TC4-B — `mode='none'` (use own toolkit)

**Branch logic verification**:

- `resolve_toolkit_source_agent_id(mode=NONE)` → `subagent_id`.
  `resolve_agent_tools` queries subagent's own `agent_toolkits` — same as existing behavior.
- Test:
  `subagent_inherit_test.py::TestResolveToolkitSourceAgentId::test_returns_subagent_when_mode_none`.

**Execution result**: Pass. No regression in existing subagent behavior.

### 3.6 TC5 — Default regression

**Default value verification**:

- `AgentSubagentCreate.toolkit_inherit_mode` default `SubagentToolkitInheritMode.NONE`
  (`repos/agent_subagent/data.py:49-52`).
- Pair validation — allow only both NULL (inherit) or both NOT NULL (own model), partial NULL is 400.
- Test: `services/agent/service_test.py::TestAgentServiceSubagentModelPairValidation`
  — 6 cases pass.

**Execution result**: Pass. Subagent created with default takes helper branch toolkit = subagent_id, model = subagent itself.

## 4. Regression Check

```
$ cd python/apps/nointern && uv run pytest src/nointern/
```

Full pytest passed (except warnings). Main related test files:

- `src/nointern/engine/tools/subagent_inherit_test.py` — **new** (8 tests)
- `src/nointern/services/agent_runtime/resolve_test.py` — 5 tests (existing)
- `src/nointern/services/agent/service_test.py` — 13 tests including 6 pair validation cases (existing)

## 5. New Test File

**`python/apps/nointern/src/nointern/engine/tools/subagent_inherit_test.py`**
(new, 8 tests):

- `TestResolveModelSourceAgentId` (2)
- `TestResolveToolkitSourceAgentId` (2)
- `TestFilterMainOnlyToolkits` (4)

**Handler refactor** (secure testability):

- `engine/tools/subagent.py` — added 3 helpers: `resolve_model_source_agent_id`, `resolve_toolkit_source_agent_id`, `filter_main_only_toolkits`. Handler internal branches replaced with calls to these helpers. Behavior unchanged.

## 6. Scenarios Recommended for Manual Execution

The following require actual LLM call + actual toolkit integration and were not performed in this Phase. Recommended to execute in user environment with runbook §4-5 procedure:

- **TC1**: Parent GitHub toolkit → after subagent inherit, verify actual `github_*` tool exposure.
- **TC2**: Opus parent + NULL subagent → verify parent model identifier is recorded in subagent `RunComplete` event.
- **TC4**: Verify subagent's own toolkit does not actually appear in live.chat tool registration.

## 7. Related Documents

- Design: [`subagent-inherit.md`](./subagent-inherit.md)
- Audit: [`subagent-inherit-audit-2026-04-24.md`](./subagent-inherit-audit-2026-04-24.md)
- Flow spec: [`../spec/flow/subagent-delegation.md`](../spec/flow/subagent-delegation.md)
- Domain spec: [`../spec/domain/agent.md`](../spec/domain/agent.md),
  [`../spec/domain/toolkit.md`](../spec/domain/toolkit.md)
