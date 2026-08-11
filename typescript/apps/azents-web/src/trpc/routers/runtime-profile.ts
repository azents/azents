import {
  runtimeProfileV1CreateProfileRecreation,
  runtimeProfileV1CreateWorkspaceRuntimeProfile,
  runtimeProfileV1DeleteWorkspaceRuntimeProfile,
  runtimeProfileV1GetWorkspaceRuntimeProfileDefault,
  runtimeProfileV1GetWorkspaceRuntimeProfileRecreation,
  runtimeProfileV1ListSelectableInfrastructureProfiles,
  runtimeProfileV1ListWorkspaceRuntimeProfiles,
  runtimeProfileV1ReplaceWorkspaceRuntimeProfile,
  runtimeProfileV1ReplaceWorkspaceRuntimeProfileDefault,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const lifecycleSchema = z.enum(["active", "disabled"]);
const networkPolicySchema = z.object({
  allowedCidrs: z.array(z.string().min(1)),
  deniedCidrs: z.array(z.string().min(1)),
});

export const runtimeProfileRouter = router({
  list: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        includeDisabled: z.boolean().optional(),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProfileV1ListWorkspaceRuntimeProfiles({
          client: ctx.apiClient,
          path: { handle: input.handle },
          query: { include_disabled: input.includeDisabled ?? false },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),

  listInfrastructureProfiles: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } =
          await runtimeProfileV1ListSelectableInfrastructureProfiles({
            client: ctx.apiClient,
            path: { handle: input.handle },
            throwOnError: true,
          });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),

  getDefault: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } =
          await runtimeProfileV1GetWorkspaceRuntimeProfileDefault({
            client: ctx.apiClient,
            path: { handle: input.handle },
            throwOnError: true,
          });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),

  create: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        infrastructureProfileId: z.string().min(1),
        displayName: z.string().min(1).max(120),
        description: z.string().max(1000),
        lifecycle: lifecycleSchema,
        networkPolicy: networkPolicySchema.nullable(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProfileV1CreateWorkspaceRuntimeProfile({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: {
            infrastructure_profile_id: input.infrastructureProfileId,
            display_name: input.displayName,
            description: input.description,
            lifecycle: input.lifecycle,
            policy: {
              schema_version: 1,
              network_restriction:
                input.networkPolicy === null
                  ? null
                  : {
                      allowed_cidrs: input.networkPolicy.allowedCidrs,
                      denied_cidrs: input.networkPolicy.deniedCidrs,
                    },
            },
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  replace: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        profileId: z.string().min(1),
        expectedVersion: z.number().int().positive(),
        infrastructureProfileId: z.string().min(1),
        displayName: z.string().min(1).max(120),
        description: z.string().max(1000),
        lifecycle: lifecycleSchema,
        networkPolicy: networkPolicySchema.nullable(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProfileV1ReplaceWorkspaceRuntimeProfile({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            profile_id: input.profileId,
          },
          body: {
            expected_version: input.expectedVersion,
            infrastructure_profile_id: input.infrastructureProfileId,
            display_name: input.displayName,
            description: input.description,
            lifecycle: input.lifecycle,
            policy: {
              schema_version: 1,
              network_restriction:
                input.networkPolicy === null
                  ? null
                  : {
                      allowed_cidrs: input.networkPolicy.allowedCidrs,
                      denied_cidrs: input.networkPolicy.deniedCidrs,
                    },
            },
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  delete: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        profileId: z.string().min(1),
        expectedVersion: z.number().int().positive(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProfileV1DeleteWorkspaceRuntimeProfile({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            profile_id: input.profileId,
          },
          body: {
            expected_version: input.expectedVersion,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  replaceDefault: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        expectedVersion: z.number().int().positive(),
        profileId: z.string().min(1).nullable(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } =
          await runtimeProfileV1ReplaceWorkspaceRuntimeProfileDefault({
            client: ctx.apiClient,
            path: { handle: input.handle },
            body: {
              expected_version: input.expectedVersion,
              runtime_profile_id: input.profileId,
            },
            throwOnError: true,
          });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  createRecreation: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        profileId: z.string().min(1),
        expectedVersion: z.number().int().positive(),
        concurrencyLimit: z.number().int().min(1).max(32).optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProfileV1CreateProfileRecreation({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            profile_id: input.profileId,
          },
          body: {
            expected_version: input.expectedVersion,
            ...(input.concurrencyLimit
              ? { concurrency_limit: input.concurrencyLimit }
              : {}),
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  getRecreation: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        operationId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } =
          await runtimeProfileV1GetWorkspaceRuntimeProfileRecreation({
            client: ctx.apiClient,
            path: {
              handle: input.handle,
              operation_id: input.operationId,
            },
            query: { offset: 0, limit: 100 },
            throwOnError: true,
          });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),
});
