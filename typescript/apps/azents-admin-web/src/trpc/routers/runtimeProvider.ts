import {
  runtimeProviderV1CreateAuthBinding,
  runtimeProviderV1GetRuntimeProvider,
  runtimeProviderV1ListAuthBindingAuditEvents,
  runtimeProviderV1ListAuthBindings,
  runtimeProviderV1ListRuntimeProviders,
  runtimeProviderV1ReplaceRuntimeProviderAvailability,
  runtimeProviderV1RevokeAuthBinding,
  runtimeProviderV1RotateAuthBinding,
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
  listAuthBindings: protectedProcedure
    .input(z.object({ providerId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProviderV1ListAuthBindings({
          client: ctx.adminApiClient,
          path: { provider_id: input.providerId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, { 404: "NOT_FOUND" });
      }
    }),

  listAuthBindingAuditEvents: protectedProcedure
    .input(
      z.object({
        bindingId: z.string().min(1),
        offset: z.number().int().nonnegative(),
        limit: z.number().int().positive().max(100),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProviderV1ListAuthBindingAuditEvents({
          client: ctx.adminApiClient,
          path: { binding_id: input.bindingId },
          query: { offset: input.offset, limit: input.limit },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, { 404: "NOT_FOUND" });
      }
    }),

  createAuthBinding: protectedProcedure
    .input(
      z.object({
        providerId: z.string().min(1),
        subject: z.string().min(1).max(255),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProviderV1CreateAuthBinding({
          client: ctx.adminApiClient,
          path: { provider_id: input.providerId },
          body: {
            auth_method: "azents_issued_token",
            subject: input.subject,
            config: null,
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

  rotateAuthBinding: protectedProcedure
    .input(
      z.object({
        bindingId: z.string().min(1),
        expectedAdminVersion: z.number().int().positive(),
        expiresAt: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProviderV1RotateAuthBinding({
          client: ctx.adminApiClient,
          path: { binding_id: input.bindingId },
          body: {
            expected_admin_version: input.expectedAdminVersion,
            expires_at: input.expiresAt,
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

  revokeAuthBinding: protectedProcedure
    .input(
      z.object({
        bindingId: z.string().min(1),
        expectedAdminVersion: z.number().int().positive(),
        reason: z.string().max(255).nullable(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProviderV1RevokeAuthBinding({
          client: ctx.adminApiClient,
          path: { binding_id: input.bindingId },
          body: {
            expected_admin_version: input.expectedAdminVersion,
            reason: input.reason,
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
