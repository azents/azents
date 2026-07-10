---
title: "Agent Domain Spec"
created: 2026-04-20
tags: [backend, engine]
spec_type: domain
domain: agent
owner: "@Hardtack"
code_paths:
  - python/apps/azents/src/azents/core/agent.py
  - python/apps/azents/src/azents/core/builtin_tools.py
  - python/apps/azents/src/azents/core/credentials.py
  - python/apps/azents/src/azents/core/llm_catalog.py
  - python/apps/azents/src/azents/core/llm_mapping.py
  - python/apps/azents/src/azents/core/inference_profile.py
  - python/apps/azents/src/azents/rdb/models/agent.py
  - python/apps/azents/src/azents/rdb/models/agent_admin.py
  - python/apps/azents/src/azents/rdb/models/llm_provider_integration.py
  - python/apps/azents/src/azents/rdb/models/workspace_model_settings.py
  - python/apps/azents/src/azents/repos/agent/**
  - python/apps/azents/src/azents/repos/agent_admin/**
  - python/apps/azents/src/azents/repos/llm_provider_integration/**
  - python/apps/azents/src/azents/repos/workspace_model_settings/**
  - python/apps/azents/src/azents/services/agent/**
  - python/apps/azents/src/azents/services/agent_runtime/**
  - python/apps/azents/src/azents/services/llm_provider_integration/**
  - python/apps/azents/src/azents/services/model_listing/**
  - python/apps/azents/src/azents/services/workspace_model_settings/**
  - python/apps/azents/src/azents/api/public/agent/**
  - python/apps/azents/src/azents/api/public/llm_provider_integration/**
  - python/apps/azents/src/azents/api/public/workspace_model_settings/**
  - python/apps/azents/src/azents/engine/run/contracts.py
  - python/apps/azents/src/azents/engine/context/window.py
  - python/apps/azents/src/azents/engine/tools/**
  - python/apps/azents/src/azents/worker/run/**
api_routes:
  - /agent/v1/workspaces/{handle}/agents
  - /agent/v1/workspaces/{handle}/agents/{agent_id}
  - /agent/v1/workspaces/{handle}/agents/{agent_id}/admins
  - /agent/v1/workspaces/{handle}/agents/{agent_id}/memories
  - /agent/v1/workspaces/{handle}/agents/{agent_id}/memories/{memory_id}
  - /agent/v1/workspaces/{handle}/agents/{agent_id}/avatar
  - /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations
  - /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/{integration_id}/models
  - /workspace-model-settings/v1/workspaces/{handle}
  - /llm-provider-integration/v1/workspaces/{handle}/chatgpt-oauth/device/start
  - /llm-provider-integration/v1/workspaces/{handle}/chatgpt-oauth/device/{session_id}
  - /chat/v1
last_verified_at: 2026-07-10
spec_version: 43
---

# Agent Domain Spec

Agent is central execution unit of azents. Within Workspace, it bundles an ordered selectable model option list, effective model selection snapshots, system prompt, model parameters, and toolkit access; worker resolves these into `RunRequest` and passes them to `AgentEngine` execution loop. Session-scoped subagents do not create a separate persistent Agent role; they are represented by `SessionAgent` tree nodes linked to hidden child `AgentSession` rows under the same Agent.

## 1. Core Model

### 1.1 Agent

`agents` row has following core fields.

| Field | Meaning |
|---|---|
| `workspace_id` | owning Workspace. cascades on Workspace deletion |
| `name`, `description` | display name and description |
| `selectable_model_options` | ordered JSONB array of selectable model options. Each option has a unique label and resolved `AgentModelSelection` snapshot |
| `main_model_label` | selected label from `selectable_model_options` for normal model turns |
| `lightweight_model_label` | selected label from `selectable_model_options` for compaction/lightweight model turns |
| `model_selection` | denormalized effective main runtime model selection snapshot resolved from `main_model_label`. required for every Agent |
| `lightweight_model_selection` | denormalized effective compaction/lightweight model selection snapshot resolved from `lightweight_model_label`. required for every Agent |
| `model_parameters` | Agent-local advanced model parameters. Only this value is used without default/preset merge |
| `system_prompt` | Agent system prompt |
| `enabled` | when false, runtime resolve blocks run start with `AgentDisabled` |
| `type` | `public` or `private` |
| `runtime_provider_id` | Runtime Provider logical id. If null, use server default provider policy |
| `shell_enabled` | whether builtin shell toolkit is exposed |
| `memory_enabled` | whether memory prompt/tool is exposed |
| `max_turns` | run turn limit. null means unlimited |
| `subagent_settings` | JSON settings for session-scoped subagent execution limits. Default is `{ "max_subagents": 3, "max_depth": 1 }` |
| `avatar` | Agent avatar stored image metadata |

`subagent_settings.max_subagents` is the maximum active subagent count under one root session. It is equivalent to Codex `max_concurrent_threads_per_session - 1`; the root/current agent is not counted in the stored value. `subagent_settings.max_depth` is the maximum `SessionAgent` tree depth below `/root`, where `1` allows root-to-child spawning only. Both values are non-negative integers.

`selectable_model_options` is a JSONB array rather than a separate table because option order is part of the fallback contract. The list invariants are:

- at least one option;
- at most 10 options;
- labels are trimmed, non-empty, case-sensitive, and unique within the list;
- labels are at most 80 characters;
- selected labels are normalized against the final list, and an absent selected label falls back to the first ordered option.

`model_selection` and `lightweight_model_selection` are `AgentModelSelection` JSONB snapshots and are not FK targets. They are effective runtime snapshots owned by Agent service consistency logic:

- `model_selection = selectable_model_options[main_model_label].model_selection`
- `lightweight_model_selection = selectable_model_options[lightweight_model_label].model_selection`

The denormalized snapshots remain the Agent defaults. Normal human inputs may instead request one label from the same Agent-owned option list for a single run. At run activation, the worker resolves that label against the current Agent snapshot without querying Workspace defaults or model catalogs. Clients never submit provider, integration, model, capability, or token-limit snapshots as run intent.

Required snapshot fields:

- `llm_provider_integration_id`
- `provider`
- `model_identifier`
- `model_display_name`
- `model_developer`
- `model_family`
- `normalized_capabilities`
- `model_snapshot`
- `source_metadata`
- `last_refreshed_at`

Snapshot is created by resolving submitted model identifiers through stored model catalog projection at submit time. Runtime does not query latest listing again and uses snapshot in Agent row as source of truth.

### 1.2 WorkspaceModelSettings

`workspace_model_settings` stores default values for new Agent creation in Workspace.

| Field | Meaning |
|---|---|
| `workspace_id` | Workspace PK/FK |
| `default_selectable_model_options` | ordered default selectable model option list copied by new Agents. may be null before Workspace defaults are configured |
| `default_main_model_label` | selected default main model label. may be null before Workspace defaults are configured |
| `default_lightweight_model_label` | selected default lightweight model label. may be null before Workspace defaults are configured |
| `default_model_selection` | denormalized effective default main model snapshot. may be null initially |
| `default_lightweight_model_selection` | denormalized effective default lightweight snapshot. may be null initially |

`effective_default_lightweight_model_selection` is not stored column; it is computed as `default_lightweight_model_selection ?? default_model_selection` for consumers that need the fallback projection.

Rules:

- If Workspace default selectable model options are absent, creating Agent without explicit model options fails.
- Once Workspace defaults are configured, the default selectable model list cannot be cleared to empty.
- Workspace default selectable model list uses the same label, order, cap, and fallback invariants as Agent selectable model options.
- Updating Workspace defaults recomputes the denormalized effective default snapshots from default labels.
- Workspace default change does not change existing Agent selectable model options or effective snapshots.
- During the direct-model transition, explicit legacy `default_model_selection` inputs are still accepted and converted into an equivalent default selectable option list.

### 1.3 Provider integration and model listing

`LLMProviderIntegration` is workspace-scoped credential/config. `/models` endpoint returns normalized model candidates selectable with that integration.

The stable `xai` provider uses generic encrypted API-key secrets with no plaintext provider config. It remains a separate integration identity from experimental `xai_oauth`. Generic integration CRUD persists fake or real keys without calling xAI for validation, omits secrets from every public response, and preserves the encrypted key when an alias or enabled-state update omits `secrets`.

Agent/Workspace settings API resolves each client-sent `{ llm_provider_integration_id, model_identifier }` through the stored model catalog projection and normalizes it into an `AgentModelSelection` snapshot. This applies both to direct transition fields and to every selectable model option entry.

## 2. API Contract

### 2.1 Agent create/update

Create/update requests accept selectable model options as the current model contract:

```json
{
  "selectable_model_options": [
    {
      "label": "default",
      "model_selection": {
        "llm_provider_integration_id": "int_...",
        "model_identifier": "gpt-5"
      }
    },
    {
      "label": "lightweight",
      "model_selection": {
        "llm_provider_integration_id": "int_...",
        "model_identifier": "gpt-5.5-mini"
      }
    }
  ],
  "main_model_label": "default",
  "lightweight_model_label": "lightweight",
  "model_parameters": {
    "temperature": 0.7,
    "context_window_tokens": 128000,
    "max_output_tokens": 8192,
    "reasoning_effort": "medium",
    "builtin_tools": []
  },
  "subagent_settings": {
    "max_subagents": 3,
    "max_depth": 1
  }
}
```

- `selectable_model_options` omitted on create: copy Workspace default selectable model options into Agent.
- `selectable_model_options` supplied: whole-list replacement. Every entry is resolved through stored catalog projection at submit time.
- Empty lists, more than 10 entries, empty labels, duplicate labels, and unresolved model selections are rejected.
- `main_model_label` / `lightweight_model_label` omitted, null, or absent from the final list: fallback to the first ordered option label.
- Effective `model_selection` and `lightweight_model_selection` are recomputed from the final labels and returned in responses.
- During transition, legacy direct `model_selection` and `lightweight_model_selection` inputs remain accepted. They are converted into compatible selectable model options and effective snapshots. These fields are compatibility for the direct snapshot API, not the removed `ModelConfig` API.
- `model_parameters` is whole-object replace. Unknown keys are rejected.
- `model_parameters.context_window_tokens` is an optional Agent-level input budget cap. It is stored as user intent even when larger than current model limits, and runtime/API effective context calculation clamps it with model limits.
- `model_parameters.max_output_tokens` is an optional output generation cap. When omitted/null, runtime does not set provider `max_output_tokens` and provider/model defaults apply.
- `subagent_settings` is a whole-object replace when supplied. Omitted create requests use the default `{ "max_subagents": 3, "max_depth": 1 }`; omitted update requests leave the stored settings unchanged.
- Response returns stored `selectable_model_options`, `main_model_label`, `lightweight_model_label`, effective `model_selection`, effective `lightweight_model_selection`, `model_parameters`, `subagent_settings`, and effective context window value.

### 2.2 Workspace model settings

```http
GET /workspace-model-settings/v1/workspaces/{handle}
PUT /workspace-model-settings/v1/workspaces/{handle}
```

PUT accepts Workspace default selectable model options and labels:

```json
{
  "default_selectable_model_options": [
    {
      "label": "default",
      "model_selection": {
        "llm_provider_integration_id": "int_...",
        "model_identifier": "gpt-5"
      }
    }
  ],
  "default_main_model_label": "default",
  "default_lightweight_model_label": "default"
}
```

- `default_selectable_model_options` is whole-list replacement.
- Once configured, the Workspace default list cannot be cleared to empty.
- Labels and option count use the same invariants as Agent selectable model options.
- Default labels normalize to the first option when omitted, null, or absent from the final list.
- Response returns default selectable options, default labels, and denormalized effective default snapshots.
- During transition, legacy direct `default_model_selection` and `default_lightweight_model_selection` inputs remain accepted and are converted into compatible default selectable options.

### 2.3 LLM provider integration models

```http
GET /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/{integration_id}/models
```

After verifying integration ownership and enabled state, returns normalized model candidate list. This endpoint is picker source for Agent/Workspace settings UI.

### 2.4 Agent Memory management

```http
GET /agent/v1/workspaces/{handle}/agents/{agent_id}/memories?scope={agent|user}
POST /agent/v1/workspaces/{handle}/agents/{agent_id}/memories
GET /agent/v1/workspaces/{handle}/agents/{agent_id}/memories/{memory_id}
PATCH /agent/v1/workspaces/{handle}/agents/{agent_id}/memories/{memory_id}
DELETE /agent/v1/workspaces/{handle}/agents/{agent_id}/memories/{memory_id}
```

These routes are Agent-scoped because Memory belongs to Agent. The Agent settings UI also updates `memory_enabled` through the normal Agent update endpoint. Detailed Memory visibility, conflict, and scope semantics are defined in [`memory.md`](memory.md).

Public integration model listing uses stored model catalog projections. The picker reads catalog entries for the selected integration, falling back to provider system catalog entries where applicable. Submit normalization resolves direct transition inputs and selectable model option entries through stored catalog projection and must not refetch dynamic provider listing as a fallback.

Deterministic fixture in local/test environment is development/QA support path activated only by integration name marker. It can sync deterministic catalog entries for product tests.

## 3. Runtime Resolve

Every run has a requested inference profile: an Agent-owned `model_target_label` plus nullable `reasoning_effort`. Null effort means the selected model's Default, not the Agent-level reasoning parameter. The request source is `explicit_input`, `session_last_used`, `agent_default`, `retry_original`, or `parent_run`.

Before a new normal run starts, runtime resolution:

1. Loads the Agent and rejects missing or disabled Agents.
2. Resolves the requested label against the Agent's current `selectable_model_options`; missing labels fail with `model_target_not_found` and never fall back to another option.
3. Validates non-null requested effort against the selected snapshot's normalized reasoning capabilities; unsupported effort fails with `reasoning_effort_unsupported` before provider invocation.
4. Loads and validates the selected main integration plus the Agent's lightweight integration, including provider token refresh where required.
5. Builds the main runtime model from the selected option while retaining the Agent's `lightweight_model_selection` for compaction.
6. Computes and fixes the run's effective context window and automatic compaction threshold.
7. Validates Agent model parameters, applies the requested effort, and materializes user attachments.

Successful activation stores the full selected `AgentModelSelection`, resolved effort, effective limits, and resolution timestamp on `AgentRun`. Subsequent turns, automatic retries, recovery, and worker takeover rebuild from that stored snapshot rather than resolving the label again. Resolution failures are terminal typed run failures with no fallback or automatic retry.

Runtime does not query Workspace defaults or model listing. Workspace defaults act only as copy sources at Agent create/update submit time, and model catalog changes do not mutate an activated run.

## 4. Built-in Tool Validation

`model_parameters.builtin_tools` is provider-side hosted tool opt-in declaration. Model snapshot `normalized_capabilities.built_in_tools.supported` means only selectable capability, and even when capability exists, built-in tool not included in Agent setting is not exposed to run.

Agent create/update validates following with rules in `core/builtin_tools.py`.

- snapshot capability must support that built-in tool.
- `web_search` validates only capability regardless of provider/model developer-specific native activation method. Gemini `web_search` also does not require shell disabled or no toolkit conditions.
- Each built-in tool owns additional constraints. For example: provider-specific combination limits of `image_generation`, `web_fetch`.
- built-in tool requiring reasoning effort checks snapshot reasoning capability and effort level.

Runtime passes only `BuiltinToolSpec(name, config)`. LiteLLM Responses lowerer sees `RunRequest.model_developer`, provider, model capability and lowers semantic hosted tool into native `tools`/`kwargs`; to protect stale snapshot/direct RunRequest, it performs capability validation once more.

## 5. Context Window / Compaction

`effective_context_window_tokens` in Agent response is calculated from the most restrictive value actually used by runtime among main model max input tokens, lightweight model max input tokens, and optional Agent `model_parameters.context_window_tokens`. The Agent context window cap is allowed to be larger than current model limits; in that case the current model limit still wins until the Agent model changes. `effective_auto_compaction_threshold_tokens` is 90% of effective context window.

Automatic compaction runs with `lightweight_model_selection` snapshot.

## 6. Memory / toolkit / avatar

- Agent with `memory_enabled=false` does not expose memory prompt/tool.
- Toolkit CRUD and runtime state follow `spec/domain/toolkit.md`.
- Avatar is stored as stored image metadata through upload service image handler and resolved to public URL in Agent response.

## 7. Removed Legacy

Following contracts do not exist in current system.

- `ModelConfig` table/service/repository/API
- `/model-config/v1/**`
- `agents.model_config_id`
- `agents.lightweight_model_config_id`
- `agents.model_config_inherit_mode`
- `agents.model_parameter_overrides`
- runtime `ModelConfig` lookup / default parameter merge
- legacy subagent role, junction, API, and blocking runtime delegation tool
- legacy persistent subagent-Agent model inheritance

## 8. Change History

| Date | Version | Change |
|---|---:|---|
| 2026-07-10 | 43 | Added per-run Agent-owned target resolution, nullable effort validation, and immutable activated profile semantics |
| 2026-07-10 | 42 | Added the stable xAI API-key integration contract and clarified provider-specific OAuth refresh |
| 2026-07-09 | 41 | Added selectable model option lists, label-based Agent/Workspace model selection, and effective snapshot semantics |
| 2026-07-09 | 40 | Added Agent `subagent_settings` persistence/API contract for subagent concurrency and depth limits |
| 2026-07-08 | 39 | Clarified that current subagents are session-scoped `SessionAgent` participants, not persistent Agent roles |
| 2026-07-06 | 38 | Removed legacy subagent role, junction, API, runtime delegation, and living spec surfaces |
| 2026-07-06 | 37 | Renamed Agent output token cap to `max_output_tokens` and added Agent `context_window_tokens` effective context override |
| 2026-07-02 | 36 | Added Agent Memory management routes and settings UI boundary |
| 2026-06-18 | 35 | Corrected integration model listing fetch failure to propagate original exception instead of failure variant/5xx HTTPException |
| 2026-06-18 | 34 | Reflected static catalog cache removal and integration-scoped dynamic listing restoration |
| 2026-06-17 | 33 | Reflected contract that catalog cache listing excludes legacy provider model rows |
| 2026-06-17 | 32 | Reflected materialized catalog cache-first policy and 502 fallback for integration model listing API |
| 2026-06-17 | 31 | Reflected Models.dev deprecated filtering and OpenAI GPT `web_search` capability policy |
| 2026-06-17 | 30 | Reflected provider-hosted `web_search` opt-in/lowering contract and Gemini constraint removal |
| 2026-06-16 | 29 | Updated to Agent/Workspace model selection snapshot structure after ModelConfig removal |
