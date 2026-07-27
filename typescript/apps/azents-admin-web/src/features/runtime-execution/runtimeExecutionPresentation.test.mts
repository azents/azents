import assert from "node:assert/strict";
import test from "node:test";
import {
  getRuntimeExecutionPolicyIssue,
  isRuntimeExecutionPolicySupported,
  updateRuntimeExecutionDockerCapability,
  updateRuntimeExecutionNetworkMode,
} from "./runtimeExecutionPresentation.ts";
import type {
  RuntimeExecutionManagementCapabilitiesResponse,
  RuntimeExecutionPolicyDocument,
} from "@azents/admin-client";

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
    cpu_millicores: null,
    memory_bytes: null,
    pids: null,
    container_count: null,
    ephemeral_storage_bytes: null,
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

void test("Admin policy saves only server-supported authority", () => {
  assert.equal(isRuntimeExecutionPolicySupported(policy, capabilities), true);
  assert.equal(
    isRuntimeExecutionPolicySupported(
      {
        ...policy,
        image_build: { ...policy.image_build, enabled: true },
      },
      capabilities,
    ),
    false,
  );
  assert.equal(
    isRuntimeExecutionPolicySupported(
      {
        ...policy,
        engine_storage: {
          ...policy.engine_storage,
          mode: "ephemeral",
        },
      },
      capabilities,
    ),
    false,
  );
});

void test("Docker capabilities and temporary storage stay consistent", () => {
  const withCompose = updateRuntimeExecutionDockerCapability(
    policy,
    "compose",
    true,
  );
  assert.equal(withCompose.container_run.enabled, true);
  assert.equal(withCompose.compose.enabled, true);
  assert.equal(withCompose.engine_storage.mode, "ephemeral");

  const withoutContainerRun = updateRuntimeExecutionDockerCapability(
    withCompose,
    "container_run",
    false,
  );
  assert.equal(withoutContainerRun.container_run.enabled, false);
  assert.equal(withoutContainerRun.compose.enabled, false);
  assert.equal(withoutContainerRun.engine_storage.mode, "none");
  assert.equal(withoutContainerRun.engine_storage.capacity_bytes, null);
});

void test("Docker storage remains enabled while image builds require it", () => {
  const withImageBuild = updateRuntimeExecutionDockerCapability(
    {
      ...policy,
      engine_storage: {
        ...policy.engine_storage,
        capacity_bytes: 8_589_934_592,
      },
    },
    "image_build",
    true,
  );
  const withoutContainerRun = updateRuntimeExecutionDockerCapability(
    withImageBuild,
    "container_run",
    false,
  );

  assert.equal(withoutContainerRun.image_build.enabled, true);
  assert.equal(withoutContainerRun.engine_storage.mode, "ephemeral");
  assert.equal(
    withoutContainerRun.engine_storage.capacity_bytes,
    8_589_934_592,
  );
});

void test("network modes clear fields that the selected policy does not use", () => {
  const policyWithCidrs: RuntimeExecutionPolicyDocument = {
    ...policy,
    network_egress: {
      ...policy.network_egress,
      mode: "restricted",
      allowed_destinations: ["140.82.112.0/20"],
      denied_destinations: ["140.82.120.0/24"],
    },
  };

  const direct = updateRuntimeExecutionNetworkMode(policyWithCidrs, "direct");
  assert.deepEqual(direct.network_egress.allowed_destinations, []);
  assert.deepEqual(direct.network_egress.denied_destinations, [
    "140.82.120.0/24",
  ]);

  const systemOnly = updateRuntimeExecutionNetworkMode(direct, "none");
  assert.deepEqual(systemOnly.network_egress.allowed_destinations, []);
  assert.deepEqual(systemOnly.network_egress.denied_destinations, []);
});

void test("Docker profiles require storage and positive Runtime limits", () => {
  const dockerCapabilities: RuntimeExecutionManagementCapabilitiesResponse = {
    image_build: true,
    container_run: true,
    compose: true,
    storage_modes: ["none", "ephemeral"],
    network_modes: ["none", "direct"],
  };
  const withDocker = updateRuntimeExecutionDockerCapability(
    policy,
    "container_run",
    true,
  );
  assert.equal(
    getRuntimeExecutionPolicyIssue(withDocker, dockerCapabilities),
    "Enter a temporary Docker storage capacity before saving.",
  );

  const withStorage: RuntimeExecutionPolicyDocument = {
    ...withDocker,
    engine_storage: {
      ...withDocker.engine_storage,
      capacity_bytes: 8_589_934_592,
    },
  };
  assert.equal(
    getRuntimeExecutionPolicyIssue(withStorage, dockerCapabilities),
    "Set every Kubernetes and nested-container limit to a positive value before enabling Docker.",
  );

  const complete: RuntimeExecutionPolicyDocument = {
    ...withStorage,
    resources: {
      ...withStorage.resources,
      cpu_millicores: 1_000,
      memory_bytes: 4_294_967_296,
      pids: 256,
      container_count: 4,
      ephemeral_storage_bytes: 8_589_934_592,
    },
  };
  assert.equal(
    getRuntimeExecutionPolicyIssue(complete, dockerCapabilities),
    null,
  );
});
