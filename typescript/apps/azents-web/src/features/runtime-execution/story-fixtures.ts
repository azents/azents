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
    image_build: false,
    container_run: false,
    compose: false,
    storage_modes: ["none"],
    network_modes: ["none"],
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
  image_build: {
    module_id: "container.image_build",
    version: 1,
    enabled: false,
  },
  container_run: {
    module_id: "container.run",
    version: 1,
    enabled: true,
  },
  compose: {
    module_id: "container.compose",
    version: 1,
    enabled: false,
  },
  resources: {
    module_id: "container.resources",
    version: 1,
    cpu_millicores: 2_000,
    memory_bytes: 4_294_967_296,
    pids: 512,
    container_count: 8,
    ephemeral_storage_bytes: 10_737_418_240,
  },
  engine_storage: {
    module_id: "engine.storage",
    version: 1,
    mode: "ephemeral",
    capacity_bytes: 10_737_418_240,
  },
  network_egress: {
    module_id: "network.egress",
    version: 1,
    mode: "restricted",
    allowed_destinations: ["registry.example.com"],
    denied_destinations: ["metadata.internal"],
  },
};

export const emptyRuntimeExecutionRestriction: RuntimeExecutionPolicyRestriction =
  {
    schema_version: 1,
    image_build: null,
    container_run: null,
    compose: null,
    resources: null,
    engine_storage: null,
    network_egress: null,
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
        platform: 2,
        profile: 3,
        workspace: 2,
        agent: 4,
      },
      governing_layers: {
        "container.image_build.enabled": "workspace",
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
      capabilities: [
        { module_id: "container.image_build", version: 1, enabled: false },
        { module_id: "container.run", version: 1, enabled: true },
        { module_id: "container.compose", version: 1, enabled: false },
      ],
      storage_mode: "ephemeral",
      storage_capacity_bytes: 10_737_418_240,
      network_mode: "restricted",
    },
    target: null,
    applied: null,
    desired_generation: 3,
    governing_layers: {
      "container.image_build.enabled": "workspace",
    },
    reason_codes: ["explicit_apply_required"],
    required_action: "apply",
  };
