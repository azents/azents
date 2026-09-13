/** Workspace model settings tRPC router */

import {
  workspaceModelSettingsV1GetWorkspaceModelSettings,
  workspaceModelSettingsV1UpdateWorkspaceModelSettings,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";
import { workspaceModelSettingsUpdateInputSchema } from "../model-settings-input-schemas";

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
    .input(workspaceModelSettingsUpdateInputSchema)
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } =
          await workspaceModelSettingsV1UpdateWorkspaceModelSettings({
            client: ctx.apiClient,
            path: { handle: input.handle },
            body: {
              default_selectable_model_options:
                input.default_selectable_model_options,
              default_main_model_label: input.default_main_model_label,
              default_lightweight_model_label:
                input.default_lightweight_model_label,
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
