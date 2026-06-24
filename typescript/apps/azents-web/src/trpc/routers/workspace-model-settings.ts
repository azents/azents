/** Workspace model settings tRPC router */

import {
  workspaceModelSettingsV1GetWorkspaceModelSettings,
  workspaceModelSettingsV1UpdateWorkspaceModelSettings,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const agentModelSelectionInputSchema = z
  .object({
    llm_provider_integration_id: z.string().min(1),
    model_identifier: z.string().min(1),
  })
  .nullable();

export const workspaceModelSettingsRouter = router({
  get: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } =
          await workspaceModelSettingsV1GetWorkspaceModelSettings({
            client: ctx.apiClient,
            path: { handle: input.handle },
            throwOnError: true,
          });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  update: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        default_model_selection: agentModelSelectionInputSchema.optional(),
        default_lightweight_model_selection:
          agentModelSelectionInputSchema.optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } =
          await workspaceModelSettingsV1UpdateWorkspaceModelSettings({
            client: ctx.apiClient,
            path: { handle: input.handle },
            body: {
              default_model_selection: input.default_model_selection,
              default_lightweight_model_selection:
                input.default_lightweight_model_selection,
            },
            throwOnError: true,
          });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          422: "BAD_REQUEST",
        });
      }
    }),
});
