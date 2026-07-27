import type {
  AgentResponse,
  AgentRuntimeExecutionPolicyResponse,
  AgentRuntimeExecutionPolicyStatusResponse,
  RuntimeExecutionManagementCapabilitiesResponse,
  RuntimeExecutionPolicyDocument,
  RuntimeExecutionPolicyRestriction,
  WorkspaceRuntimeExecutionPolicyResponse,
  WorkspaceRuntimeExecutionProfileResponse,
} from "@azents/public-client";

export const runtimeExecutionManagementCapabilities: RuntimeExecutionManagementCapabilitiesResponse =
  {
    docker: true,
    storage_modes: ["none", "ephemeral"],
  };

export const runtimeExecutionAgent: AgentResponse = {
  id: "agent-runtime-policy",
  name: "Release Operator",
  description: "Coordinates release operations.",
  model_selection: null,
  lightweight_model_selection: null,
  selectable_model_options: [],
  main_model_label: "default",
  lightweight_model_label: "default",
  effective_context_window_tokens: 128_000,
  effective_auto_compaction_threshold_tokens: 96_000,
  model_parameters: null,
  system_prompt: null,
  enabled: true,
  type: "private",
  runtime_provider_id: null,
  shell_enabled: true,
  memory_enabled: true,
  tool_search_enabled: false,
  max_turns: null,
  auto_archive_ttl_days: 30,
  subagent_settings: { max_subagents: 3, max_depth: 1 },
  avatar: null,
  created_at: "2026-07-26T00:00:00Z",
  updated_at: "2026-07-26T00:00:00Z",
};

export const runtimeExecutionPolicy: RuntimeExecutionPolicyDocument = {
  schema_version: 1,
  docker: {
    module_id: "docker",
    version: 1,
    enabled: true,
    storage_mode: "ephemeral",
    storage_capacity_bytes: 10_737_418_240,
  },
  resources: {
    module_id: "runtime.resources",
    version: 1,
    cpu_request_millicores: 1_000,
    cpu_limit_millicores: 2_000,
    memory_request_bytes: 2_147_483_648,
    memory_limit_bytes: 4_294_967_296,
    ephemeral_storage_bytes: 10_737_418_240,
    persistent_storage_bytes: 21_474_836_480,
  },
};

export const emptyRuntimeExecutionRestriction: RuntimeExecutionPolicyRestriction =
  {
    schema_version: 1,
    docker: null,
    resources: null,
  };

export const runtimeExecutionProfile: WorkspaceRuntimeExecutionProfileResponse =
  {
    id: "standard",
    display_name: "Standard",
    description: "General-purpose restricted execution.",
    lifecycle: "active",
    version: 3,
    policy: runtimeExecutionPolicy,
    digest: "profile-digest-0123456789",
    reserved: true,
    allowed: true,
    available: true,
    reason: null,
  };

export const workspaceRuntimeExecutionPolicy: WorkspaceRuntimeExecutionPolicyResponse =
  {
    workspace_id: "workspace-engineering",
    version: 2,
    restriction: emptyRuntimeExecutionRestriction,
    digest: "workspace-digest-0123456789",
    allowed_profile_ids: ["standard"],
    updated_at: "2026-07-26T00:00:00Z",
    capabilities: runtimeExecutionManagementCapabilities,
  };

export const agentRuntimeExecutionPolicy: AgentRuntimeExecutionPolicyResponse =
  {
    agent_id: runtimeExecutionAgent.id,
    version: 4,
    profile_id: "standard",
    profile_version: 3,
    profile_lifecycle: "active",
    restriction: emptyRuntimeExecutionRestriction,
    digest: "agent-configured-digest-0123456789",
    effective_preview: {
      available: true,
      effective_policy: runtimeExecutionPolicy,
      digest: "effective-digest-0123456789",
      source_versions: {
        profile: 3,
        workspace: 2,
        agent: 4,
      },
      governing_layers: {
        "docker.enabled": "workspace",
      },
      reductions: [],
      change: { direction: "metadata_only", fields: [] },
      availability_reason: null,
      availability_detail: null,
    },
    provider_compatibility_evaluated: false,
    updated_at: "2026-07-26T00:00:00Z",
    capabilities: runtimeExecutionManagementCapabilities,
  };

export const configuredRuntimeExecutionStatus: AgentRuntimeExecutionPolicyStatusResponse =
  {
    status: "configured",
    configured: {
      profile_id: "standard",
      digest: "configured-digest-0123456789",
      capabilities: [{ module_id: "docker", version: 1, enabled: true }],
      storage_mode: "ephemeral",
      storage_capacity_bytes: 10_737_418_240,
    },
    target: null,
    applied: null,
    desired_generation: 3,
    governing_layers: {
      "docker.enabled": "workspace",
    },
    reason_codes: ["explicit_apply_required"],
    required_action: "apply",
  };
