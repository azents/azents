import {
  systemSettingsV1CancelPlatformGithubAppCandidate,
  systemSettingsV1CheckPlatformGithubAppHealth,
  systemSettingsV1ConfirmPlatformGithubAppCandidate,
  systemSettingsV1GetPlatformGithubAppSetting,
  systemSettingsV1ListSystemSettingAuditEvents,
  systemSettingsV1PatchPlatformGithubAppSetting,
  systemSettingsV1ValidatePlatformGithubAppCandidate,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { protectedProcedure, router } from "../init";
import type { PlatformGitHubAppPatchRequest } from "@azents/admin-client";

const secretActionSchema = z.discriminatedUnion("action", [
  z.object({ action: z.literal("replace"), value: z.string().min(1) }),
  z.object({ action: z.literal("clear") }),
]);

export const systemSettingsRouter = router({
  getPlatformGitHubApp: protectedProcedure.query(async ({ ctx }) => {
    const { data } = await systemSettingsV1GetPlatformGithubAppSetting({
      client: ctx.adminApiClient,
      throwOnError: true,
    });
    return data;
  }),

  patchPlatformGitHubApp: protectedProcedure
    .input(
      z.object({
        expectedVersion: z.number().int().nonnegative(),
        appId: z.string().nullable().optional(),
        clientId: z.string().nullable().optional(),
        privateKey: secretActionSchema.optional(),
        clientSecret: secretActionSchema.optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const body: PlatformGitHubAppPatchRequest = {
          expected_version: input.expectedVersion,
        };
        if (Object.hasOwn(input, "appId")) {
          body.app_id = input.appId ?? null;
        }
        if (Object.hasOwn(input, "clientId")) {
          body.client_id = input.clientId ?? null;
        }
        if (input.privateKey) {
          body.private_key = input.privateKey;
        }
        if (input.clientSecret) {
          body.client_secret = input.clientSecret;
        }
        const { data } = await systemSettingsV1PatchPlatformGithubAppSetting({
          client: ctx.adminApiClient,
          body,
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

  validatePlatformGitHubAppCandidate: protectedProcedure.mutation(
    async ({ ctx }) => {
      try {
        const { data } =
          await systemSettingsV1ValidatePlatformGithubAppCandidate({
            client: ctx.adminApiClient,
            throwOnError: true,
          });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    },
  ),

  confirmPlatformGitHubAppCandidate: protectedProcedure
    .input(
      z.object({
        candidateId: z.string().min(1),
        expectedVersion: z.number().int().nonnegative(),
        confirmationAction: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } =
          await systemSettingsV1ConfirmPlatformGithubAppCandidate({
            client: ctx.adminApiClient,
            body: {
              candidate_id: input.candidateId,
              expected_version: input.expectedVersion,
              confirmation_action: input.confirmationAction,
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

  cancelPlatformGitHubAppCandidate: protectedProcedure
    .input(z.object({ candidateId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        await systemSettingsV1CancelPlatformGithubAppCandidate({
          client: ctx.adminApiClient,
          query: { candidate_id: input.candidateId },
          throwOnError: true,
        });
        return null;
      } catch (error) {
        throw mapExpectedError(error, {
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  checkPlatformGitHubAppHealth: protectedProcedure.mutation(async ({ ctx }) => {
    try {
      const { data } = await systemSettingsV1CheckPlatformGithubAppHealth({
        client: ctx.adminApiClient,
        throwOnError: true,
      });
      return data;
    } catch (error) {
      throw mapExpectedError(error, {
        409: "CONFLICT",
      });
    }
  }),

  listAuditEvents: protectedProcedure
    .input(
      z
        .object({
          offset: z.number().int().nonnegative().default(0),
          limit: z.number().int().positive().max(100).default(20),
        })
        .default({ offset: 0, limit: 20 }),
    )
    .query(async ({ ctx, input }) => {
      const { data } = await systemSettingsV1ListSystemSettingAuditEvents({
        client: ctx.adminApiClient,
        query: input,
        throwOnError: true,
      });
      return data;
    }),
});
