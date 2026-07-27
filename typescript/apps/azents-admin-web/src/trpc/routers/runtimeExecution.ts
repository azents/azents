import {
  runtimeExecutionV1CreateProfile,
  runtimeExecutionV1ListAuditEvents,
  runtimeExecutionV1ListProfiles,
  runtimeExecutionV1ReplaceProfile,
  runtimeExecutionV1RetireProfile,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { protectedProcedure, router } from "../init";

const booleanModuleSchema = z.object({
  module_id: z.enum([
    "container.image_build",
    "container.run",
    "container.compose",
  ]),
  version: z.literal(1),
  enabled: z.boolean(),
});

const policySchema = z.object({
  schema_version: z.literal(1),
  image_build: booleanModuleSchema,
  container_run: booleanModuleSchema,
  compose: booleanModuleSchema,
  resources: z.object({
    module_id: z.literal("container.resources"),
    version: z.literal(1),
    cpu_request_millicores: z.number().int().positive().nullable(),
    cpu_limit_millicores: z.number().int().positive().nullable(),
    memory_request_bytes: z.number().int().positive().nullable(),
    memory_limit_bytes: z.number().int().positive().nullable(),
    pids: z.number().int().positive().nullable(),
    container_count: z.number().int().positive().nullable(),
    ephemeral_storage_bytes: z.number().int().positive().nullable(),
    persistent_storage_bytes: z.number().int().positive().nullable(),
  }),
  engine_storage: z.object({
    module_id: z.literal("engine.storage"),
    version: z.literal(1),
    mode: z.enum(["none", "ephemeral", "persistent"]),
    capacity_bytes: z.number().int().positive().nullable(),
  }),
  network_egress: z.object({
    module_id: z.literal("network.egress"),
    version: z.literal(1),
    mode: z.enum(["none", "restricted", "direct"]),
    allowed_destinations: z.array(z.string()),
    denied_destinations: z.array(z.string()),
  }),
});

export const runtimeExecutionRouter = router({
  listProfiles: protectedProcedure.query(async ({ ctx }) => {
    const { data } = await runtimeExecutionV1ListProfiles({
      client: ctx.adminApiClient,
      query: { include_retired: true, offset: 0, limit: 100 },
      throwOnError: true,
    });
    return data;
  }),

  listAuditEvents: protectedProcedure.query(async ({ ctx }) => {
    const { data } = await runtimeExecutionV1ListAuditEvents({
      client: ctx.adminApiClient,
      query: { offset: 0, limit: 100 },
      throwOnError: true,
    });
    return data;
  }),

  createProfile: protectedProcedure
    .input(
      z.object({
        profileId: z
          .string()
          .min(1)
          .max(32)
          .regex(/^[a-z0-9][a-z0-9-]*$/),
        displayName: z.string().min(1).max(120),
        description: z.string().max(4000),
        policy: policySchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeExecutionV1CreateProfile({
          client: ctx.adminApiClient,
          body: {
            profile_id: input.profileId,
            display_name: input.displayName,
            description: input.description,
            policy: input.policy,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  replaceProfile: protectedProcedure
    .input(
      z.object({
        profileId: z.string().min(1),
        expectedVersion: z.number().int().positive(),
        displayName: z.string().min(1).max(120),
        description: z.string().max(4000),
        policy: policySchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeExecutionV1ReplaceProfile({
          client: ctx.adminApiClient,
          path: { profile_id: input.profileId },
          body: {
            expected_version: input.expectedVersion,
            display_name: input.displayName,
            description: input.description,
            policy: input.policy,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  retireProfile: protectedProcedure
    .input(
      z.object({
        profileId: z.string().min(1),
        expectedVersion: z.number().int().positive(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeExecutionV1RetireProfile({
          client: ctx.adminApiClient,
          path: { profile_id: input.profileId },
          body: { expected_version: input.expectedVersion },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),
});
