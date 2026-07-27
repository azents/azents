import assert from "node:assert/strict";
import test from "node:test";
import {
  getRuntimeExecutionPolicyIssue,
  isRuntimeExecutionPolicySupported,
  updateRuntimeExecutionDocker,
  withRuntimeExecutionDockerDefaults,
} from "./runtimeExecutionPresentation.ts";
import type {
  RuntimeExecutionManagementCapabilitiesResponse,
  RuntimeExecutionPolicyDocument,
} from "@azents/admin-client";

const capabilities: RuntimeExecutionManagementCapabilitiesResponse = {
  docker: true,
  storage_modes: ["none", "ephemeral"],
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

void test("Admin policy exposes Docker as one complete capability", () => {
  const enabled = updateRuntimeExecutionDocker(policy, true);

  assert.equal(enabled.docker.enabled, true);
  assert.equal(enabled.docker.storage_mode, "ephemeral");
  assert.equal(enabled.docker.storage_capacity_bytes, 16 * 1024 ** 3);
  assert.equal(enabled.resources.ephemeral_storage_bytes, 16 * 1024 ** 3);
  assert.equal(isRuntimeExecutionPolicySupported(enabled, capabilities), true);

  const disabled = updateRuntimeExecutionDocker(enabled, false);
  assert.equal(disabled.docker.enabled, false);
  assert.equal(disabled.docker.storage_mode, "none");
  assert.equal(disabled.docker.storage_capacity_bytes, null);
  assert.equal(disabled.resources.ephemeral_storage_bytes, null);
});

void test("Existing enabled Docker policies receive enforceable defaults", () => {
  const withDefaults = withRuntimeExecutionDockerDefaults({
    ...policy,
    docker: {
      ...policy.docker,
      enabled: true,
      storage_mode: "ephemeral",
    },
  });

  assert.equal(withDefaults.docker.storage_capacity_bytes, 16 * 1024 ** 3);
  assert.equal(withDefaults.resources.ephemeral_storage_bytes, 16 * 1024 ** 3);
});

void test("Docker validation explains missing storage", () => {
  const incomplete: RuntimeExecutionPolicyDocument = {
    ...policy,
    docker: {
      ...policy.docker,
      enabled: true,
      storage_mode: "ephemeral",
      storage_capacity_bytes: 8 * 1024 ** 3,
    },
  };

  assert.equal(
    getRuntimeExecutionPolicyIssue(incomplete, capabilities),
    "Set the Kubernetes ephemeral-storage value before enabling Docker.",
  );
});
