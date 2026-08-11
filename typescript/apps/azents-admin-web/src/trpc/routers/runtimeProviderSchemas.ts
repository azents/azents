import { z } from "zod/v4";

const resourceSchema = z.object({
  cpu_request_millicores: z.number().int().nonnegative().nullable(),
  cpu_limit_millicores: z.number().int().nonnegative().nullable(),
  memory_request_bytes: z.number().int().nonnegative().nullable(),
  memory_limit_bytes: z.number().int().nonnegative().nullable(),
});
const dockerResourceSchema = z.object({
  cpu_reservation_millicores: z.number().int().nonnegative().nullable(),
  cpu_limit_millicores: z.number().int().nonnegative().nullable(),
  memory_reservation_bytes: z.number().int().nonnegative().nullable(),
  memory_limit_bytes: z.number().int().nonnegative().nullable(),
});
const networkPolicySchema = z.object({
  allowed_cidrs: z.array(z.string().min(1)).optional(),
  denied_cidrs: z.array(z.string().min(1)).optional(),
});
const kubernetesSpecBaseSchema = z.object({
  profile_kind: z.literal("kubernetes_pod"),
  contract_family: z.literal("kubernetes.pod-profile"),
  runner_resources: resourceSchema,
  workspace_volume: z.object({
    storage_class_name: z.string().min(1),
    storage_request_bytes: z.number().int().positive(),
  }),
  network_policy: networkPolicySchema,
  service_account_name: z.string().min(1).nullable(),
  scheduling: z.object({
    node_selector: z.record(z.string(), z.string()).optional(),
    tolerations: z
      .array(
        z.object({
          key: z.string(),
          operator: z.enum(["Equal", "Exists"]),
          value: z.string().nullable(),
          effect: z
            .enum(["NoSchedule", "PreferNoSchedule", "NoExecute"])
            .nullable(),
          toleration_seconds: z.number().int().nonnegative().nullable(),
        }),
      )
      .optional(),
  }),
  dind: z
    .object({
      engine_resources: resourceSchema,
      docker_storage_bytes: z.number().int().positive(),
      shared_temporary_storage_bytes: z.number().int().positive(),
    })
    .nullable(),
});
const kubernetesSpecSchema = z.union([
  kubernetesSpecBaseSchema
    .extend({
      schema_version: z.literal(1),
    })
    .strict(),
  kubernetesSpecBaseSchema
    .extend({
      schema_version: z.literal(2),
    })
    .strict(),
]);
const dockerSpecBaseSchema = z.object({
  profile_kind: z.literal("docker_container"),
  contract_family: z.literal("docker.container-profile"),
  runner_resources: dockerResourceSchema,
  network_name: z.string().min(1).nullable(),
});
const dockerSpecSchema = z.union([
  dockerSpecBaseSchema
    .extend({
      schema_version: z.literal(1),
    })
    .strict(),
  dockerSpecBaseSchema
    .extend({
      schema_version: z.literal(2),
    })
    .strict(),
]);

export const infrastructureSpecSchema = z.union([
  kubernetesSpecSchema,
  dockerSpecSchema,
]);
