import assert from "node:assert/strict";
import test from "node:test";
import { infrastructureSpecSchema } from "./runtimeProviderSchemas.ts";

const dockerV2Spec = {
  profile_kind: "docker_container",
  contract_family: "docker.container-profile",
  schema_version: 2,
  runner_resources: {
    cpu_reservation_millicores: null,
    cpu_limit_millicores: null,
    memory_reservation_bytes: null,
    memory_limit_bytes: null,
  },
  network_name: "azents-runtime",
} as const;

void test("direct v2 infrastructure Profile input is accepted", () => {
  assert.deepEqual(infrastructureSpecSchema.parse(dockerV2Spec), dockerV2Spec);
});

void test("removed containment input is rejected instead of stripped", () => {
  assert.throws(
    () =>
      infrastructureSpecSchema.parse({
        ...dockerV2Spec,
        process_containment: { schema_version: 1 },
      }),
    /Unrecognized key/,
  );
});
