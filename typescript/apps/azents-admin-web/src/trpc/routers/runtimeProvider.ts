import {
  runtimeProviderV1CreateAuthBinding,
  runtimeProviderV1CreateContainerProfile,
  runtimeProviderV1CreateContainerProfileRecreation,
  runtimeProviderV1CreatePodProfile,
  runtimeProviderV1CreatePodProfileRecreation,
  runtimeProviderV1CreateProviderRecreation,
  runtimeProviderV1DeleteContainerProfile,
  runtimeProviderV1DeletePodProfile,
  runtimeProviderV1GetContainerProfileDeletionImpact,
  runtimeProviderV1GetPlatformRecreation,
  runtimeProviderV1GetPodProfileDeletionImpact,
  runtimeProviderV1GetRuntimeProvider,
  runtimeProviderV1GetWorkspaceProfileAdminDetail,
  runtimeProviderV1ListAuthBindingAuditEvents,
  runtimeProviderV1ListAuthBindings,
  runtimeProviderV1ListContainerProfiles,
  runtimeProviderV1ListContracts,
  runtimeProviderV1ListPodProfiles,
  runtimeProviderV1ListRuntimeProviders,
  runtimeProviderV1ReplaceContainerProfile,
  runtimeProviderV1ReplacePodProfile,
  runtimeProviderV1ReplaceRuntimeProviderAvailability,
  runtimeProviderV1RevokeAuthBinding,
  runtimeProviderV1RotateAuthBinding,
  runtimeProviderV1UpdateRuntimeProviderPolicy,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { protectedProcedure, router } from "../init";
import { infrastructureSpecSchema } from "./runtimeProviderSchemas";

const lifecycleStateSchema = z.enum([
  "active",
  "decommissioning",
  "decommissioned",
  "force_retired",
]);
const availabilityModeSchema = z.enum(["platform_wide", "selected_workspaces"]);
const profileKindSchema = z.enum(["kubernetes_pod", "docker_container"]);
const profileLifecycleSchema = z.enum(["active", "disabled"]);

export const runtimeProviderRouter = router({
  getRecreation: protectedProcedure
    .input(z.object({ operationId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProviderV1GetPlatformRecreation({
          client: ctx.adminApiClient,
          path: { operation_id: input.operationId },
          query: { offset: 0, limit: 100 },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, { 404: "NOT_FOUND" });
      }
    }),

  listInfrastructureProfiles: protectedProcedure
    .input(
      z.object({
        providerId: z.string().min(1),
        profileKind: profileKindSchema,
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const request = {
          client: ctx.adminApiClient,
          path: { provider_id: input.providerId },
          query: { include_disabled: true },
          throwOnError: true,
        } as const;
        const { data } =
          input.profileKind === "kubernetes_pod"
            ? await runtimeProviderV1ListPodProfiles(request)
            : await runtimeProviderV1ListContainerProfiles(request);
        return data;
      } catch (error) {
        throw mapExpectedError(error, { 404: "NOT_FOUND" });
      }
    }),

  getInfrastructureProfileDeletionImpact: protectedProcedure
    .input(
      z.object({
        providerId: z.string().min(1),
        profileId: z.string().min(1),
        profileKind: profileKindSchema,
        offset: z.number().int().nonnegative().default(0),
        limit: z.number().int().positive().max(100).default(50),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const request = {
          client: ctx.adminApiClient,
          path: {
            provider_id: input.providerId,
            profile_id: input.profileId,
          },
          query: { offset: input.offset, limit: input.limit },
          throwOnError: true,
        } as const;
        const { data } =
          input.profileKind === "kubernetes_pod"
            ? await runtimeProviderV1GetPodProfileDeletionImpact(request)
            : await runtimeProviderV1GetContainerProfileDeletionImpact(request);
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          404: "NOT_FOUND",
          422: "BAD_REQUEST",
        });
      }
    }),

  deleteInfrastructureProfile: protectedProcedure
    .input(
      z.object({
        providerId: z.string().min(1),
        profileId: z.string().min(1),
        profileKind: profileKindSchema,
        expectedVersion: z.number().int().positive(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const request = {
          client: ctx.adminApiClient,
          path: {
            provider_id: input.providerId,
            profile_id: input.profileId,
          },
          body: { expected_version: input.expectedVersion },
          throwOnError: true,
        } as const;
        const { data } =
          input.profileKind === "kubernetes_pod"
            ? await runtimeProviderV1DeletePodProfile(request)
            : await runtimeProviderV1DeleteContainerProfile(request);
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  getWorkspaceProfileAdminDetail: protectedProcedure
    .input(
      z.object({
        workspaceHandle: z.string().min(1),
        profileId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProviderV1GetWorkspaceProfileAdminDetail({
          client: ctx.adminApiClient,
          path: {
            handle: input.workspaceHandle,
            profile_id: input.profileId,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, { 404: "NOT_FOUND" });
      }
    }),

  createInfrastructureProfile: protectedProcedure
    .input(
      z.object({
        providerId: z.string().min(1),
        displayName: z.string().min(1).max(120),
        description: z.string().max(1000),
        lifecycle: profileLifecycleSchema,
        spec: infrastructureSpecSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const request = {
          client: ctx.adminApiClient,
          path: { provider_id: input.providerId },
          body: {
            display_name: input.displayName,
            description: input.description,
            lifecycle: input.lifecycle,
            spec: input.spec,
          },
          throwOnError: true,
        } as const;
        const { data } =
          input.spec.profile_kind === "kubernetes_pod"
            ? await runtimeProviderV1CreatePodProfile(request)
            : await runtimeProviderV1CreateContainerProfile(request);
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  replaceInfrastructureProfile: protectedProcedure
    .input(
      z.object({
        providerId: z.string().min(1),
        profileId: z.string().min(1),
        expectedVersion: z.number().int().positive(),
        displayName: z.string().min(1).max(120),
        description: z.string().max(1000),
        lifecycle: profileLifecycleSchema,
        spec: infrastructureSpecSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const request = {
          client: ctx.adminApiClient,
          path: {
            provider_id: input.providerId,
            profile_id: input.profileId,
          },
          body: {
            expected_version: input.expectedVersion,
            display_name: input.displayName,
            description: input.description,
            lifecycle: input.lifecycle,
            spec: input.spec,
          },
          throwOnError: true,
        } as const;
        const { data } =
          input.spec.profile_kind === "kubernetes_pod"
            ? await runtimeProviderV1ReplacePodProfile(request)
            : await runtimeProviderV1ReplaceContainerProfile(request);
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  createInfrastructureProfileRecreation: protectedProcedure
    .input(
      z.object({
        providerId: z.string().min(1),
        profileId: z.string().min(1),
        profileKind: profileKindSchema,
        expectedVersion: z.number().int().positive(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const request = {
          client: ctx.adminApiClient,
          path: {
            provider_id: input.providerId,
            profile_id: input.profileId,
          },
          body: { expected_version: input.expectedVersion },
          throwOnError: true,
        } as const;
        const { data } =
          input.profileKind === "kubernetes_pod"
            ? await runtimeProviderV1CreatePodProfileRecreation(request)
            : await runtimeProviderV1CreateContainerProfileRecreation(request);
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  createProviderRecreation: protectedProcedure
    .input(
      z.object({
        providerId: z.string().min(1),
        expectedVersion: z.number().int().positive(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProviderV1CreateProviderRecreation({
          client: ctx.adminApiClient,
          path: { provider_id: input.providerId },
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

  listContracts: protectedProcedure
    .input(z.object({ providerId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProviderV1ListContracts({
          client: ctx.adminApiClient,
          path: { provider_id: input.providerId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, { 404: "NOT_FOUND" });
      }
    }),

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
