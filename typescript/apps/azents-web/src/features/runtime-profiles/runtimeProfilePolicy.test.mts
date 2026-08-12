import assert from "node:assert/strict";
import test from "node:test";
import {
  policySchemaVersionForInfrastructure,
  proxyDomainModeForInfrastructure,
  runtimeProfileMutationPolicy,
} from "./runtimeProfilePolicy.ts";
import type { RuntimeProfileFormValues } from "./schemas.ts";

const baseValues: RuntimeProfileFormValues = {
  displayName: "Runtime",
  description: "",
  infrastructureProfileId: "profile",
  lifecycle: "active",
  policySchemaVersion: 2,
  networkMode: "inherit",
  allowedCidrs: "",
  deniedCidrs: "",
  proxyDomainMode: "unrestricted",
  allowedDomains: "",
  deniedDomains: "",
};

void test("Docker infrastructure selects and serializes the legacy policy contract", () => {
  assert.equal(
    policySchemaVersionForInfrastructure({
      profile_kind: "docker_container",
    }),
    1,
  );
  assert.deepEqual(
    runtimeProfileMutationPolicy({
      ...baseValues,
      policySchemaVersion: 1,
    }),
    {
      schemaVersion: 1,
      networkRestriction: null,
    },
  );
});

void test("Kubernetes infrastructure selects the hierarchical policy contract", () => {
  assert.equal(
    policySchemaVersionForInfrastructure({
      profile_kind: "kubernetes_pod",
    }),
    2,
  );
});

void test("an infrastructure domain allowlist selects and serializes an allowlist restriction", () => {
  assert.equal(
    proxyDomainModeForInfrastructure({ domain_mode: "allowlist" }),
    "allowlist",
  );
  assert.deepEqual(
    runtimeProfileMutationPolicy({
      ...baseValues,
      networkMode: "proxy_required",
      proxyDomainMode: "allowlist",
      allowedCidrs: "10.0.0.0/8",
      allowedDomains: "*.example.com",
      deniedDomains: "blocked.example.com",
    }),
    {
      schemaVersion: 2,
      networkRestriction: {
        mode: "proxy_required",
        allowedCidrs: ["10.0.0.0/8"],
        deniedCidrs: [],
        domainPolicy: {
          mode: "allowlist",
          allowedDomains: ["*.example.com"],
          deniedDomains: ["blocked.example.com"],
        },
      },
    },
  );
});
