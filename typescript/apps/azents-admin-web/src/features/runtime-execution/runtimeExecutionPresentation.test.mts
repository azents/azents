import assert from "node:assert/strict";
import test from "node:test";
import { isRuntimeExecutionPolicySupported } from "./runtimeExecutionPresentation.ts";
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
