import assert from "node:assert/strict";
import test from "node:test";
import {
  canAllowWorkspaceRuntimeExecutionProfile,
  canApplyRuntimeExecution,
  canEditWorkspaceRuntimeExecution,
  canSaveAgentRuntimeExecution,
  canSaveWorkspaceRuntimeExecution,
  isRuntimeExecutionPolicySupported,
  RUNTIME_EXECUTION_STATUS_REFETCH_INTERVAL_MS,
  runtimeExecutionStatusRefetchInterval,
  runtimePolicyReasonMessageKey,
} from "./runtimeExecutionPresentation.ts";
import type {
  AgentRuntimeExecutionPolicyStatusResponse,
  RuntimeExecutionManagementCapabilitiesResponse,
  RuntimeExecutionPolicyDocument,
  WorkspaceRuntimeExecutionProfileResponse,
} from "@azents/public-client";

const capabilities: RuntimeExecutionManagementCapabilitiesResponse = {
  image_build: false,
  container_run: false,
  compose: false,
  storage_modes: ["none"],
  network_modes: ["none"],
};

const policy: RuntimeExecutionPolicyDocument = {
  schema_version: 1,
  image_build: {
    module_id: "container.image_build",
    version: 1,
    enabled: false,
  },
  container_run: {
    module_id: "container.run",
    version: 1,
    enabled: false,
  },
  compose: {
    module_id: "container.compose",
    version: 1,
    enabled: false,
  },
  resources: {
    module_id: "container.resources",
    version: 1,
    cpu_request_millicores: null,
    cpu_limit_millicores: null,
    memory_request_bytes: null,
    memory_limit_bytes: null,
    pids: null,
    container_count: null,
    ephemeral_storage_bytes: null,
    persistent_storage_bytes: null,
  },
  engine_storage: {
    module_id: "engine.storage",
    version: 1,
    mode: "none",
    capacity_bytes: null,
  },
  network_egress: {
    module_id: "network.egress",
    version: 1,
    mode: "none",
    allowed_destinations: [],
    denied_destinations: [],
  },
};

const profile: WorkspaceRuntimeExecutionProfileResponse = {
  id: "standard",
  display_name: "Standard",
  description: "Standard",
  lifecycle: "active",
  version: 1,
  policy,
  digest: "digest",
  reserved: true,
  allowed: true,
  available: true,
  reason: null,
};

const configuredStatus: AgentRuntimeExecutionPolicyStatusResponse = {
  status: "configured",
  configured: {
    profile_id: "standard",
    digest: "digest",
    capabilities: [],
    storage_mode: "none",
    storage_capacity_bytes: null,
    network_mode: "none",
  },
  target: null,
  applied: null,
  desired_generation: 1,
  governing_layers: {},
  reason_codes: [],
  required_action: "apply",
};

void test("workspace Runtime Execution edit visibility follows the workspace role", () => {
  assert.equal(canEditWorkspaceRuntimeExecution("owner"), true);
  assert.equal(canEditWorkspaceRuntimeExecution("manager"), true);
  assert.equal(canEditWorkspaceRuntimeExecution("member"), false);
});

void test("Apply visibility follows only the server-required action", () => {
  assert.equal(canApplyRuntimeExecution("apply"), true);
  assert.equal(canApplyRuntimeExecution("none"), false);
  assert.equal(canApplyRuntimeExecution("wait"), false);
  assert.equal(canApplyRuntimeExecution("administrator_action"), false);
});

void test("server management capabilities reject unsupported authority", () => {
  assert.equal(isRuntimeExecutionPolicySupported(policy, capabilities), true);
  assert.equal(
    isRuntimeExecutionPolicySupported(
      {
        ...policy,
        container_run: { ...policy.container_run, enabled: true },
      },
      capabilities,
    ),
    false,
  );
  assert.equal(
    isRuntimeExecutionPolicySupported(
      {
        ...policy,
        network_egress: { ...policy.network_egress, mode: "direct" },
      },
      capabilities,
    ),
    false,
  );
});

void test("workspace allowance permits supported blocked Profiles only", () => {
  assert.equal(
    canAllowWorkspaceRuntimeExecutionProfile(
      {
        ...profile,
        allowed: false,
        available: false,
        reason: "profile_not_allowed",
      },
      capabilities,
    ),
    true,
  );
  const unsupportedProfile = {
    ...profile,
    id: "engine",
    allowed: false,
    available: false,
    reason: "profile_not_allowed",
    policy: {
      ...policy,
      container_run: { ...policy.container_run, enabled: true },
    },
  } satisfies WorkspaceRuntimeExecutionProfileResponse;
  assert.equal(
    canAllowWorkspaceRuntimeExecutionProfile(unsupportedProfile, capabilities),
    false,
  );
  assert.equal(
    canSaveWorkspaceRuntimeExecution(
      [profile.id],
      [profile, unsupportedProfile],
      capabilities,
    ),
    true,
  );
  assert.equal(
    canSaveWorkspaceRuntimeExecution(
      [unsupportedProfile.id],
      [profile, unsupportedProfile],
      capabilities,
    ),
    false,
  );
});

void test("Agent save requires a server-available active Profile", () => {
  assert.equal(canSaveAgentRuntimeExecution(profile.id, [profile]), true);
  assert.equal(
    canSaveAgentRuntimeExecution(profile.id, [
      { ...profile, available: false, reason: "provider_engine_unsupported" },
    ]),
    false,
  );
  assert.equal(canSaveAgentRuntimeExecution(null, [profile]), false);
});

void test("status polling follows wait and stops at terminal actions", () => {
  assert.equal(
    runtimeExecutionStatusRefetchInterval({
      ...configuredStatus,
      status: "pending",
      required_action: "wait",
    }),
    RUNTIME_EXECUTION_STATUS_REFETCH_INTERVAL_MS,
  );
  for (const requiredAction of [
    "none",
    "apply",
    "administrator_action",
  ] as const) {
    assert.equal(
      runtimeExecutionStatusRefetchInterval({
        ...configuredStatus,
        required_action: requiredAction,
      }),
      false,
    );
  }
  assert.equal(runtimeExecutionStatusRefetchInterval(), false);
});

void test("every Runtime policy reason has a visible message fallback", () => {
  assert.equal(
    runtimePolicyReasonMessageKey("applied_snapshot_unverified"),
    "reasonExplanations.applied_snapshot_unverified",
  );
  assert.equal(
    runtimePolicyReasonMessageKey("RUNTIME_POLICY_PROVIDER_EVIDENCE_MISMATCH"),
    "reasonExplanations.provider_evidence_mismatch",
  );
  assert.equal(
    runtimePolicyReasonMessageKey("unexpected_provider_failure"),
    "reasonExplanations.runtime_failure",
  );
});
