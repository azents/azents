import assert from "node:assert/strict";
import test from "node:test";
import {
  getRuntimeExecutionPolicyIssue,
  isRuntimeExecutionPolicySupported,
  updateRuntimeExecutionDockerCapability,
  updateRuntimeExecutionNetworkMode,
  withRuntimeExecutionDockerDefaults,
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
    version: 2,
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
  assert.equal(withCompose.resources.pids, null);
  assert.equal(withCompose.resources.container_count, null);
  assert.equal(withCompose.engine_storage.capacity_bytes, 17_179_869_184);

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

void test("existing Docker policies receive a storage default only", () => {
  const withDefaults = withRuntimeExecutionDockerDefaults({
    ...policy,
    image_build: { ...policy.image_build, enabled: true },
    resources: {
      ...policy.resources,
      pids: 1_024,
    },
    engine_storage: {
      ...policy.engine_storage,
      mode: "none",
    },
  });

  assert.equal(withDefaults.resources.pids, 1_024);
  assert.equal(withDefaults.resources.container_count, null);
  assert.equal(withDefaults.engine_storage.mode, "ephemeral");
  assert.equal(withDefaults.engine_storage.capacity_bytes, 17_179_869_184);
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

void test("Docker profiles require ephemeral storage only", () => {
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
    "Set the ephemeral storage value before enabling Docker.",
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
    "Set the ephemeral storage value before enabling Docker.",
  );

  const complete: RuntimeExecutionPolicyDocument = {
    ...withStorage,
    resources: {
      ...withStorage.resources,
      ephemeral_storage_bytes: 8_589_934_592,
    },
  };
  assert.equal(
    getRuntimeExecutionPolicyIssue(complete, dockerCapabilities),
    null,
  );
});
