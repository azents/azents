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
  docker: false,
  storage_modes: ["none"],
};

const policy: RuntimeExecutionPolicyDocument = {
  schema_version: 1,
  docker: {
    module_id: "docker",
    version: 1,
    enabled: false,
    storage_mode: "none",
    storage_capacity_bytes: null,
  },
  resources: {
    module_id: "runtime.resources",
    version: 1,
    cpu_request_millicores: null,
    cpu_limit_millicores: null,
    memory_request_bytes: null,
    memory_limit_bytes: null,
    ephemeral_storage_bytes: null,
    persistent_storage_bytes: null,
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
  },
  target: null,
  applied: null,
  desired_generation: 1,
  governing_layers: {},
  reason_codes: [],
  required_action: "apply",
};

void test("workspace edit visibility follows the Workspace role", () => {
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

void test("Provider capabilities gate complete Docker authority", () => {
  assert.equal(isRuntimeExecutionPolicySupported(policy, capabilities), true);
  const dockerPolicy: RuntimeExecutionPolicyDocument = {
    ...policy,
    docker: {
      ...policy.docker,
      enabled: true,
      storage_mode: "ephemeral",
      storage_capacity_bytes: 16 * 1024 ** 3,
    },
  };
  assert.equal(
    isRuntimeExecutionPolicySupported(dockerPolicy, capabilities),
    false,
  );
});

void test("workspace allowance accepts only supported active Profiles", () => {
  assert.equal(
    canAllowWorkspaceRuntimeExecutionProfile(profile, capabilities),
    true,
  );
  const retired = {
    ...profile,
    lifecycle: "retired",
  } satisfies WorkspaceRuntimeExecutionProfileResponse;
  assert.equal(
    canAllowWorkspaceRuntimeExecutionProfile(retired, capabilities),
    false,
  );
  assert.equal(
    canSaveWorkspaceRuntimeExecution([profile.id], [profile], capabilities),
    true,
  );
});

void test("Agent save requires a server-available active Profile", () => {
  assert.equal(canSaveAgentRuntimeExecution(profile.id, [profile]), true);
  assert.equal(
    canSaveAgentRuntimeExecution(profile.id, [
      { ...profile, available: false, reason: "provider_module_unsupported" },
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
  assert.equal(runtimeExecutionStatusRefetchInterval(configuredStatus), false);
  assert.equal(runtimeExecutionStatusRefetchInterval(), false);
});

void test("unknown Runtime failures retain a visible fallback", () => {
  assert.equal(
    runtimePolicyReasonMessageKey("RUNTIME_POLICY_PROVIDER_EVIDENCE_MISMATCH"),
    "reasonExplanations.provider_evidence_mismatch",
  );
  assert.equal(
    runtimePolicyReasonMessageKey("unexpected_provider_failure"),
    "reasonExplanations.runtime_failure",
  );
});
