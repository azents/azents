---
title: "Subagent Inherit Design-Implementation Audit Report"
tags: [process, backend, engine, frontend, audit]
created: 2026-04-24
updated: 2026-04-24
implemented: 2026-04-24
document_role: supporting
document_type: supporting-audit
migration_source: "docs/azents/design/subagent-inherit-audit-2026-04-24.md"
---

# Subagent Inherit Design-Implementation Audit Report

## 1. Audit Scope

- **Design documents**: [`docs/nointern/design/subagent-inherit.md`](./subagent-inherit.md) (final design after review #2976), [`subagent-inherit-plan.md`](./subagent-inherit-plan.md)
- **Spec documents**:
  - [`docs/nointern/spec/domain/agent.md`](../spec/domain/agent.md) (spec_version 2)
  - [`docs/nointern/spec/domain/toolkit.md`](../spec/domain/toolkit.md) (spec_version 3)
  - [`docs/nointern/spec/flow/subagent-delegation.md`](../spec/flow/subagent-delegation.md) (spec_version 2)
- **Audited commit range**: `plan/subagent-inherit..feat/subagent-inherit/phase-d`

Audited commits (Phase A-D):

| SHA | Title |
|---|---|
| `a425d12f4` | feat(nointern): add AgentSubagent toolkit_inherit_mode column |
| `3c106b692` | feat(nointern): make llm_provider_*_id nullable for subagent model inherit |
| `18a15a4eb` | feat(nointern): add subagent model pair validation ([subagent-model-pair]) |
| `c6dc8d423` | feat(nointern): add toolkit_type field to ToolkitBinding |
| `4f837d294` | feat(nointern): introduce resolve_invoke_input_with_model_source helper |
| `dc80e3df0` | feat(nointern): branch inherit mode in subagent handler |
| `ff6bf56dd` | test(nointern): unit tests for subagent inherit |
| `d52b8698a` | feat(nointern-api): add toolkit_inherit_mode to agent subagent API |
| `d5bd6e9e8` | feat(nointern-api): support nullable llm_provider_* in agent create/update request |
| `eb9e31fbf` | feat(nointern-web): subagent toolkit/model inherit UI |
| `c9a7cdafa` | docs(nointern): add model inherit rule to subagent domain spec |
| `f6efae894` | docs(nointern): add main-only / inherit section to toolkit domain spec |
| `b9551fcbf` | docs(nointern): reflect inherit branch in subagent-delegation flow spec |
| `94e1dd4b2` | docs(nointern): add subagent inherit QA runbook |

## 2. Summary by Category

| Category | Count | Meaning |
|---|---|---|
| **IMPLEMENTED** | 30 | Implementation completed according to design document (file:line evidence confirmed) |
| **TODO-DOCUMENTED** | 0 | Items left as TODO / placeholder (mentioned in docs) |
| **MISSING** | 0 | Items present in design but absent in code and without TODO |
| **MISMATCH** | 2 | doc-code mismatch (2 pre-existing stale references, fixed in this branch) |
| **DEFERRED-DOCUMENTED** | 3 | Items explicitly marked as "future" / "Follow-up" in design |

Total requirements: **35**. All confirmed. No High/Critical MISSING.

## 3. Detailed Requirements Table

### 3.1 DB / Data Model (§"Data Model" + Phase A)

| # | Design requirement | Code evidence | Severity | Category |
|---|---|---|---|---|
| D01 | `agents.toolkit_inherit_mode VARCHAR(10) NOT NULL DEFAULT 'none'` + CHECK constraint | [`db-schemas/rdb/migrations/versions/eae41783d6f5_add_subagent_inherit.py:23-41`](../../../python/apps/nointern/db-schemas/rdb/migrations/versions/eae41783d6f5_add_subagent_inherit.py) | Critical | IMPLEMENTED |
| D02 | `agents.llm_provider_*_id` DROP NOT NULL + `ck_agents_model_not_null_when_role_agent` CHECK | migration L45-68, [`rdb/models/agent.py:170-175`](../../../python/apps/nointern/src/nointern/rdb/models/agent.py) | Critical | IMPLEMENTED |
| D03 | `SubagentToolkitInheritMode` enum (`NONE`/`ALL`) | [`repos/agent_subagent/data.py:12-24`](../../../python/apps/nointern/src/nointern/repos/agent_subagent/data.py) | High | IMPLEMENTED |
| D04 | Pydantic `AgentSubagent.toolkit_inherit_mode` field + Create default `NONE` + Update TypedDict | [`repos/agent_subagent/data.py:27-63`](../../../python/apps/nointern/src/nointern/repos/agent_subagent/data.py) | High | IMPLEMENTED |
| D05 | `Agent.llm_provider_*_id: str \| None` in `repos/agent/data.py` | [`repos/agent/data.py:27-42`](../../../python/apps/nointern/src/nointern/repos/agent/data.py) | High | IMPLEMENTED |
| D06 | SQLA `RDBAgent.llm_provider_integration_id/model_id` nullable + keep FK RESTRICT | [`rdb/models/agent.py:67-80`](../../../python/apps/nointern/src/nointern/rdb/models/agent.py) | High | IMPLEMENTED |
| D07 | SQLA `RDBAgentSubagent.toolkit_inherit_mode` + `CK_INHERIT_MODE` constraint | [`rdb/models/agent_subagent.py:42-69`](../../../python/apps/nointern/src/nointern/rdb/models/agent_subagent.py) | High | IMPLEMENTED |

### 3.2 Service Layer (§"Service" + Phase B)

| # | Design requirement | Code evidence | Severity | Category |
|---|---|---|---|---|
| S01 | `InvalidModelPair` Failure type + service-layer validation | [`services/agent/data.py:274-284`](../../../python/apps/nointern/src/nointern/services/agent/data.py), [`services/agent/__init__.py:145-164, 393-412`](../../../python/apps/nointern/src/nointern/services/agent/__init__.py) | High | IMPLEMENTED |
| S02 | Create path pair validation (both NULL / both values) | `services/agent/__init__.py:150-165` | High | IMPLEMENTED |
| S03 | Update path pair validation (partial NULL prohibited) | `services/agent/__init__.py:393-412` | High | IMPLEMENTED |
| S04 | Reflect `toolkit_inherit_mode` in `services/agent_subagent/__init__.py` CRUD (create + update + response) | [`services/agent_subagent/__init__.py:108, 174`](../../../python/apps/nointern/src/nointern/services/agent_subagent/__init__.py), [`services/agent_subagent/data.py:22, 36`](../../../python/apps/nointern/src/nointern/services/agent_subagent/data.py) | High | IMPLEMENTED |
| S05 | `ParentModelUnavailable` Failure type (drift defense) | [`engine/run/input.py:78-88`](../../../python/apps/nointern/src/nointern/engine/run/input.py) | Medium | IMPLEMENTED |

### 3.3 Runtime (§"Runtime Implementation" + Phase B)

| # | Design requirement | Code evidence | Severity | Category |
|---|---|---|---|---|
| R01 | `resolve_invoke_input_with_model_source` helper — if `model_source_agent_id=None`, existing behavior; if value provided, model/integration based on model_agent, system_prompt/params/workspace_id based on subagent | [`engine/run/resolve.py:110-321`](../../../python/apps/nointern/src/nointern/engine/run/resolve.py) | Critical | IMPLEMENTED |
| R02 | `resolve_invoke_input` wrapper delegates to `resolve_invoke_input_with_model_source(model_source_agent_id=None)` | `engine/run/resolve.py:73-107` | High | IMPLEMENTED |
| R03 | Add `ToolkitBinding.toolkit_type: str \| None` field | [`engine/engine.py:144-162`](../../../python/apps/nointern/src/nointern/engine/engine.py) | High | IMPLEMENTED |
| R04 | Fill `toolkit_type` in `resolve_agent_tools` return values (DB-registered → at.toolkit_type, builtin/slack/discord/schedule → None) | `engine/run/resolve.py:449-640` | High | IMPLEMENTED |
| R05 | `MAIN_ONLY_TOOL_NAMES` constant (tool-name level, `shell_recreate_sandbox`) — rename `_EXCLUDED_TOOL_NAMES` | [`engine/tools/subagent.py:74`](../../../python/apps/nointern/src/nointern/engine/tools/subagent.py) | High | IMPLEMENTED |
| R06 | `MAIN_ONLY_TOOLKIT_TYPES` constant (toolkit-type level, currently empty) | `engine/tools/subagent.py:81` | High | IMPLEMENTED |
| R07 | Subagent handler: model inherit branch (`model_source=ctx.parent_agent_id` if `subagent.llm_provider_model_id is None`) | `engine/tools/subagent.py:260-272` | Critical | IMPLEMENTED |
| R08 | Subagent handler: toolkit source branch (`resolve_agent_tools(parent_agent_id)` if `inherit_mode=ALL`, otherwise subagent_id) | `engine/tools/subagent.py:318-349` | Critical | IMPLEMENTED |
| R09 | Filter parent main-only toolkit when `inherit_mode=ALL` (post-filter) | `engine/tools/subagent.py:353-359` | High | IMPLEMENTED |
| R10 | Share parent sandbox (`set_sandbox_agent_id(parent_agent_id)`) + `set_excluded_tools(MAIN_ONLY_TOOL_NAMES)` | `engine/tools/subagent.py:366-370` | High | IMPLEMENTED |
| R11 | Force `memory_enabled=False` (subagent resolve) | `engine/tools/subagent.py:347` | Medium | IMPLEMENTED |
| R12 | `shell_enabled` keeps subagent's own setting (not inherited) | `engine/tools/subagent.py:327-333` | Medium | IMPLEMENTED |

### 3.4 API (§"API" + Phase C)

| # | Design requirement | Code evidence | Severity | Category |
|---|---|---|---|---|
| A01 | Allow `toolkit_inherit_mode` in POST/PATCH `/agents/{id}/subagents` | [`api/public/agent/v1/data.py:213, 226, 244`](../../../python/apps/nointern/src/nointern/api/public/agent/v1/data.py), [`api/public/agent/v1/__init__.py:691`](../../../python/apps/nointern/src/nointern/api/public/agent/v1/__init__.py) | High | IMPLEMENTED |
| A02 | Allow nullable `llm_provider_*_id` when role is subagent in POST/PATCH `/agents` | `api/public/agent/v1/data.py:108-115`, `api/public/agent/v1/__init__.py:83` | High | IMPLEMENTED |
| A03 | Map `InvalidModelPair` → 400 (create + update) | `api/public/agent/v1/__init__.py:138-145, 318-325` | High | IMPLEMENTED |
| A04 | Change `llm_provider_model` optional in Response `AgentResponse` (both fields pair nullable) | `api/public/agent/v1/data.py:190-232` | High | IMPLEMENTED |
| A05 | Include `toolkit_inherit_mode` field in Response `AgentSubagentResponse` | `api/public/agent/v1/data.py:205-230` | High | IMPLEMENTED |
| A06 | Update OpenAPI spec (`specs/public/openapi.json`) | `python/apps/nointern/specs/public/openapi.json` (`toolkit_inherit_mode` = 4 occurrences) | Medium | IMPLEMENTED |

### 3.5 Frontend (§"Frontend" + Phase C)

| # | Design requirement | Code evidence | Severity | Category |
|---|---|---|---|---|
| F01 | "Use parent's toolkits" checkbox on each row in `AgentSubagentSection.tsx` | [`features/agents/components/AgentSubagentSection.tsx:220-230`](../../../typescript/apps/nointern-web/src/features/agents/components/AgentSubagentSection.tsx) | High | IMPLEMENTED |
| F02 | Same checkbox in new add form (default off) | `AgentSubagentSection.tsx:106-128` (newToolkitInherit state → createMutation) | High | IMPLEMENTED |
| F03 | "Inherit model from parent" checkbox in Agent edit form (subagent role) | [`features/agents/components/AgentForm.tsx:332-349`](../../../typescript/apps/nointern-web/src/features/agents/components/AgentForm.tsx) | High | IMPLEMENTED |
| F04 | Disable provider/model select + send null when inherit_model=true | `AgentForm.tsx:352-380`, [`useAgentFormContainer.ts:328-365`](../../../typescript/apps/nointern-web/src/features/agents/containers/useAgentFormContainer.ts) | High | IMPLEMENTED |
| F05 | tRPC `agentSubagent.ts` — `toolkitInheritMode` create/update | [`trpc/routers/agentSubagent.ts:28, 64, 76, 103, 118`](../../../typescript/apps/nointern-web/src/trpc/routers/agentSubagent.ts) | High | IMPLEMENTED |
| F06 | tRPC `agent.ts` — `llmProviderIntegrationId` / `llmProviderModelId` nullable | [`trpc/routers/agent.ts`](../../../typescript/apps/nointern-web/src/trpc/routers/agent.ts) (59 lines changed) | High | IMPLEMENTED |
| F07 | Agent list/header badge ("Inherits from parent") | [`AgentHeader.tsx:102`](../../../typescript/apps/nointern-web/src/features/agents/components/AgentHeader.tsx), [`AgentList.tsx:221`](../../../typescript/apps/nointern-web/src/features/agents/components/AgentList.tsx) | Low | IMPLEMENTED |
| F08 | i18n — `inheritModel*` + `useParentToolkits*` keys in 4 locales en-US, ko-KR, ja-JP, fr-FR | [`messages/en-US.json`](../../../typescript/apps/nointern-web/messages/en-US.json) L345-349, L390-391; same structure in ko-KR/ja-JP/fr-FR | High | IMPLEMENTED |

### 3.6 Spec Documents (Phase D)

| # | Design requirement | Code evidence | Severity | Category |
|---|---|---|---|---|
| P01 | `[subagent-model-nullable]` rule in `spec/domain/agent.md` | `spec/domain/agent.md:449-460` | High | IMPLEMENTED |
| P02 | `[subagent-model-pair]` rule in `spec/domain/agent.md` | `spec/domain/agent.md:461-468` | High | IMPLEMENTED |
| P03 | "Main-Only Toolkit" section in `spec/domain/toolkit.md` + description of `MAIN_ONLY_TOOL_NAMES` / `MAIN_ONLY_TOOLKIT_TYPES` constants | `spec/domain/toolkit.md:253-290` | High | IMPLEMENTED |
| P04 | "Toolkit Inherit (Subagent)" section in `spec/domain/toolkit.md` + agent-row-level exclusive policy | `spec/domain/toolkit.md:291-325` | High | IMPLEMENTED |
| P05 | Add model/toolkit inherit branches to sequence diagram in `spec/flow/subagent-delegation.md` | `spec/flow/subagent-delegation.md:163-176, 276-302` | High | IMPLEMENTED |
| P06 | Add 3 error cases to `spec/flow/subagent-delegation.md` (InvalidModelPair, ParentModelUnavailable, main-only filter) | `spec/flow/subagent-delegation.md:318-321` | High | IMPLEMENTED |

### 3.7 Deferred (explicitly "future")

| # | Design requirement | Current state | Category |
|---|---|---|---|
| X01 | `model_parameters` inherit (temperature, etc.) — excluded from initial scope | Explicit in Plan §"Follow-up issues" | DEFERRED-DOCUMENTED |
| X02 | Per-toolkit inherit allowlist (`mode='explicit'`) — enum extension possible | Explicit in DP3 §"B/C rejection rationale", reconfirmed in Plan §"Follow-up issues" | DEFERRED-DOCUMENTED |
| X03 | Toolkit DB `main_only` flag (workspace admin editable) | Deferred in DP4 §"B adopted", reconfirmed in Plan §"Follow-up issues" | DEFERRED-DOCUMENTED |

### 3.8 MISMATCH

| # | Location | Symptom | Fix method | Fix commit |
|---|---|---|---|---|
| M01 | `spec/domain/agent.md:239` | `_EXCLUDED_TOOL_NAMES` was renamed to `MAIN_ONLY_TOOL_NAMES` in Phase B code, but spec body still referenced `_EXCLUDED_TOOL_NAMES` | change spec to `MAIN_ONLY_TOOL_NAMES` | (fixed in this audit branch) |
| M02 | `spec/flow/subagent-delegation.md:316` | same reference to `_EXCLUDED_TOOL_NAMES` in error case table | change spec to `MAIN_ONLY_TOOL_NAMES` | (fixed in this audit branch) |

Both are cases where rename was missed during spec update in Phase D and are **fixed directly in this audit branch**. Also recorded as **SPEC-UPDATE-NEEDED** in spec-implementation sync audit report (`subagent-inherit-spec-sync-2026-04-24.md`).

## 4. Note — Other Observations Found During Audit

Items below are not "design-implementation match" issues but quality observations captured during audit.

### 4.1 `resolve.py` except statement style issue (Low)

- **Location**: [`engine/run/resolve.py:360, 389`](../../../python/apps/nointern/src/nointern/engine/run/resolve.py)
- **Symptom**: Phase A commit (`3c106b692`) removed parentheses from `except (FileNotFoundError, ValueError, OSError):` to `except FileNotFoundError, ValueError, OSError:`. Python 3.14 parses this as tuple expression and behavior is functionally identical, and both ruff/pyright pass; however, existing style with parentheses is preferable for readability/consistency. This is outside design scope, so it is recorded only in audit report.
- **Recommendation**: restore parentheses in cleanup phase (Low severity, no behavioral impact).

### 4.2 Pre-existing broken links (information)

`docs/nointern/issues/` directory referenced by `spec/domain/agent.md:296, 720` and `spec/flow/subagent-delegation.md:270, 274, 408, 410` does not exist. This drift existed before this PR series and is unrelated to subagent-inherit. Outside this audit scope.

### 4.3 testenv scenario implementation file (carried to Phase 8)

TC1-5 + TC4-B in design §"testenv QA scenarios" were documented only as runbook; actual execution code (scenario files in `python/apps/nointern-e2e/`) is written in Phase 8 (`test/subagent-inherit/testenv-qa` branch). This is as stated in Plan §"Phase 8" and outside Phase D scope. **Not MISSING.**

## 5. Re-audit Loop Result

Result of 1 rerun: no new findings. The two MISMATCH items above were detected in same loop.

## 6. Conclusion

- **All Critical / High requirements** in design document are reflected in code (IMPLEMENTED 30 / 30).
- MISSING 0, MISMATCH 2 (immediately fixed in this branch).
- All 3 DEFERRED items are explicitly stated in plan §"Follow-up" and confirmed carried to follow-up phase / issue.
- **Phase A-D matches design**, and spec sync is complete after §3.8 fix. Only testenv QA execution (Phase 8) remains.

## 7. Related Documents

- [Design document](./subagent-inherit.md)
- [Implementation plan](./subagent-inherit-plan.md)
- [Spec sync audit report](./subagent-inherit-spec-sync-2026-04-24.md)
- Spec: [agent](../spec/domain/agent.md), [toolkit](../spec/domain/toolkit.md), [subagent-delegation](../spec/flow/subagent-delegation.md)
