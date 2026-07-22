import {
  runtimeProviderV1GetRuntimeProvider,
  runtimeProviderV1ListRuntimeProviders,
  runtimeProviderV1ReplaceRuntimeProviderAvailability,
  runtimeProviderV1UpdateRuntimeProviderPolicy,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { protectedProcedure, router } from "../init";

const lifecycleStateSchema = z.enum([
  "active",
  "decommissioning",
  "decommissioned",
  "force_retired",
]);
const availabilityModeSchema = z.enum(["platform_wide", "selected_workspaces"]);

export const runtimeProviderRouter = router({
  list: protectedProcedure.query(async ({ ctx }) => {
    const { data } = await runtimeProviderV1ListRuntimeProviders({
      client: ctx.adminApiClient,
      throwOnError: true,
    });
    return data;
  }),

  get: protectedProcedure
    .input(z.object({ providerId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProviderV1GetRuntimeProvider({
          client: ctx.adminApiClient,
          path: { provider_id: input.providerId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, { 404: "NOT_FOUND" });
      }
    }),

  updatePolicy: protectedProcedure
    .input(
      z.object({
        providerId: z.string().min(1),
        enabled: z.boolean(),
        lifecycleState: lifecycleStateSchema,
        availabilityMode: availabilityModeSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProviderV1UpdateRuntimeProviderPolicy({
          client: ctx.adminApiClient,
          path: { provider_id: input.providerId },
          body: {
            enabled: input.enabled,
            lifecycle_state: input.lifecycleState,
            availability_mode: input.availabilityMode,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, { 404: "NOT_FOUND", 409: "CONFLICT" });
      }
    }),

  replaceAvailability: protectedProcedure
    .input(
      z.object({
        providerId: z.string().min(1),
        workspaceIds: z.array(z.string().min(1)),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } =
          await runtimeProviderV1ReplaceRuntimeProviderAvailability({
            client: ctx.adminApiClient,
            path: { provider_id: input.providerId },
            body: { workspace_ids: input.workspaceIds },
            throwOnError: true,
          });
        return data;
      } catch (error) {
        throw mapExpectedError(error, { 404: "NOT_FOUND", 409: "CONFLICT" });
      }
    }),
});
