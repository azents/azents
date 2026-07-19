import {
  systemV1GetArchiveRetentionApplication,
  systemV1GetFileLifecycleSettings,
  systemV1PreviewArchiveRetentionUpdate,
  systemV1UpdateFileLifecycleSettings,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { protectedProcedure, router } from "../init";

const retentionDaysSchema = z.number().int().nonnegative().nullable();
const applicationScopeSchema = z.enum([
  "new_archives_only",
  "recalculate_existing",
]);

export const retentionRouter = router({
  getSettings: protectedProcedure.query(async ({ ctx }) => {
    const { data } = await systemV1GetFileLifecycleSettings({
      client: ctx.adminApiClient,
      throwOnError: true,
    });
    return data;
  }),

  preview: protectedProcedure
    .input(z.object({ retentionDays: retentionDaysSchema }))
    .mutation(async ({ ctx, input }) => {
      const { data } = await systemV1PreviewArchiveRetentionUpdate({
        client: ctx.adminApiClient,
        body: {
          archived_session_retention_days: input.retentionDays,
        },
        throwOnError: true,
      });
      return data;
    }),

  updateSettings: protectedProcedure
    .input(
      z.object({
        expectedRevision: z.number().int().positive(),
        retentionDays: retentionDaysSchema,
        applicationScope: applicationScopeSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await systemV1UpdateFileLifecycleSettings({
          client: ctx.adminApiClient,
          body: {
            expected_revision: input.expectedRevision,
            archived_session_retention_days: input.retentionDays,
            application_scope: input.applicationScope,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          409: "CONFLICT",
        });
      }
    }),

  getApplication: protectedProcedure
    .input(z.object({ applicationId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await systemV1GetArchiveRetentionApplication({
          client: ctx.adminApiClient,
          path: { application_id: input.applicationId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          404: "NOT_FOUND",
        });
      }
    }),
});
