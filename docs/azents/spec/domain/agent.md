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
last_verified_at: 2026-07-06
spec_version: 38
---

# Agent Domain Spec

Agent is central execution unit of azents. Within Workspace, it bundles model selection snapshot, system prompt, model parameters, and toolkit access; worker resolves these into `RunRequest` and passes them to `AgentEngine` execution loop.

## 1. Core Model

### 1.1 Agent

`agents` row has following core fields.

| Field | Meaning |
|---|---|
| `workspace_id` | owning Workspace. cascades on Workspace deletion |
| `name`, `description` | display name and description |
| `model_selection` | main runtime model selection snapshot. required for every Agent |
| `lightweight_model_selection` | compaction/lightweight model selection snapshot. required for every Agent |
| `model_parameters` | Agent-local advanced model parameters. Only this value is used without default/preset merge |
| `system_prompt` | Agent system prompt |
| `enabled` | when false, runtime resolve blocks run start with `AgentDisabled` |
| `type` | `public` or `private` |
| `runtime_provider_id` | Runtime Provider logical id. If null, use server default provider policy |
| `shell_enabled` | whether builtin shell toolkit is exposed |
| `memory_enabled` | whether memory prompt/tool is exposed |
| `max_turns` | run turn limit. null means unlimited |
| `avatar` | Agent avatar stored image metadata |

`model_selection` and `lightweight_model_selection` are `AgentModelSelection` JSONB snapshots and are not FK targets.

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

Snapshot is created by model listing service re-querying integration-scoped listing at submit time. Runtime does not query latest listing again and uses snapshot in Agent row as source of truth.

### 1.2 WorkspaceModelSettings

`workspace_model_settings` stores default values for new Agent creation in Workspace.

| Field | Meaning |
|---|---|
| `workspace_id` | Workspace PK/FK |
| `default_model_selection` | default main model snapshot. may be null initially |
| `default_lightweight_model_selection` | optional default lightweight snapshot |

`effective_default_lightweight_model_selection` is not stored column; it is computed as `default_lightweight_model_selection ?? default_model_selection`.

Rules:

- If Workspace default main model is absent, creating Agent without model fails.
- If Workspace default main model is absent and Agent is created with explicit main model, server bootstraps that snapshot as workspace default main model.
- Once configured, default main model cannot be reverted to null and can only be changed.
- default lightweight model can be cleared to null.
- Workspace default change does not change existing Agent snapshot.

### 1.3 Provider integration and model listing

`LLMProviderIntegration` is workspace-scoped credential/config. `/models` endpoint returns normalized model candidates selectable with that integration.

Agent/Workspace settings API re-queries listing on server for client-sent `{ llm_provider_integration_id, model_identifier }` and normalizes it into `AgentModelSelection` snapshot.

## 2. API Contract

### 2.1 Agent create/update

Create/update request receives only following model-related fields.

```json
{
  "model_selection": {
    "llm_provider_integration_id": "int_...",
    "model_identifier": "gpt-4o"
  },
  "lightweight_model_selection": null,
  "model_parameters": {
    "temperature": 0.7,
    "context_window_tokens": 128000,
    "max_output_tokens": 8192,
    "reasoning_effort": "medium",
    "builtin_tools": []
  }
}
```

- `model_selection` omitted/null: copy workspace default main snapshot into Agent.
- `lightweight_model_selection` omitted/null: copy workspace default lightweight if exists; otherwise copy Agent main snapshot.
- `model_parameters` is whole-object replace. Unknown keys are rejected.
- `model_parameters.context_window_tokens` is an optional Agent-level input budget cap. It is stored as user intent even when larger than current model limits, and runtime/API effective context calculation clamps it with model limits.
- `model_parameters.max_output_tokens` is an optional output generation cap. When omitted/null, runtime does not set provider `max_output_tokens` and provider/model defaults apply.
- Response returns stored `model_selection`, `lightweight_model_selection`, `model_parameters`, effective context window value.

### 2.2 Workspace model settings

```http
GET /workspace-model-settings/v1/workspaces/{handle}
PUT /workspace-model-settings/v1/workspaces/{handle}
```

PUT receives `default_model_selection` and `default_lightweight_model_selection` input. Each input is same selection key as Agent, and response returns snapshot.

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

Public integration model listing API does not use materialized DB catalog cache. Even in production, request path calls integration-scoped dynamic listing adapter. Providers for which public catalog is enough, such as OpenAI, Anthropic, Google Gemini, ChatGPT OAuth, can use Models.dev based adapter; providers where exposed models differ by account/project/region, such as AWS Bedrock and Google Vertex AI, use integration credential/config-based provider API adapter. Listing result is not saved to DB and is used only for snapshot normalization at Agent/Workspace submit time.

Deterministic fixture in local/test environment is development/QA support path activated only by integration name marker. General integration listing fetch failure is not modeled as service result failure variant and is propagated as original exception. Route code does not directly raise 5xx `HTTPException`; FastAPI/server error handling treats unexpected/internal failure as 500.

Models.dev backed listing excludes candidates where adapter `available` value is false. Adapter excludes models with source `status=deprecated` and models included in internal custom deprecated model policy from user-visible listing. OpenAI custom deprecated list is managed as provider-specific hardcoded set from intersection of Deprecated badge in OpenAI API All models doc and Models.dev OpenAI `gpt-*` response; later, non-GPT provider/model can be added with same structure.

When Models.dev does not provide provider-hosted tool capability, internal capability policy supplements it. OpenAI `gpt-*` text models include `web_search` in `normalized_capabilities.built_in_tools.supported`. GPT Image models (`gpt-image-*`) are not LLM text hosted search targets, so they are excluded from this supplement.

## 3. Runtime Resolve

`resolve_invoke_input()` performs following before run start.

1. Load Agent with `AgentRepository.get_by_id()`.
2. Return `AgentNotFound` if Agent absent, `AgentDisabled` if disabled.
3. Read Agent `model_selection` and `lightweight_model_selection` snapshots.
4. Load integration including secrets by `llm_provider_integration_id` of each snapshot.
5. Return `IntegrationNotFound` if integration absent, `IntegrationDisabled` if disabled.
6. ChatGPT OAuth integration refreshes near-expiry token with `ensure_runtime_tokens()`.
7. Convert `provider` + `model_identifier` into LiteLLM runtime model string.
8. Compute max input token from `normalized_capabilities.context_window.max_input_tokens`.
9. Validate Agent `model_parameters` by capability and pass to runtime request fields.
10. Materialize user input attachment into runtime attachment/FilePart.

Runtime does not query workspace default or model listing. Workspace default acts only as copy source at create/update submit time.

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
- subagent role, junction, API, and runtime delegation tool
- subagent model runtime inheritance

## 8. Change History

| Date | Version | Change |
|---|---:|---|
| 2026-07-06 | 38 | Removed subagent role, junction, API, runtime delegation, and living spec surfaces |
| 2026-07-06 | 37 | Renamed Agent output token cap to `max_output_tokens` and added Agent `context_window_tokens` effective context override |
| 2026-07-02 | 36 | Added Agent Memory management routes and settings UI boundary |
| 2026-06-18 | 35 | Corrected integration model listing fetch failure to propagate original exception instead of failure variant/5xx HTTPException |
| 2026-06-18 | 34 | Reflected static catalog cache removal and integration-scoped dynamic listing restoration |
| 2026-06-17 | 33 | Reflected contract that catalog cache listing excludes legacy provider model rows |
| 2026-06-17 | 32 | Reflected materialized catalog cache-first policy and 502 fallback for integration model listing API |
| 2026-06-17 | 31 | Reflected Models.dev deprecated filtering and OpenAI GPT `web_search` capability policy |
| 2026-06-17 | 30 | Reflected provider-hosted `web_search` opt-in/lowering contract and Gemini constraint removal |
| 2026-06-16 | 29 | Updated to Agent/Workspace model selection snapshot structure after ModelConfig removal |
