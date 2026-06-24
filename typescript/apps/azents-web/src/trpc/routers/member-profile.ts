/**
 * MemberProfile tRPC router
 *
 * workspace my own profile fetch/update:
 * - getMyProfile: current member of profile fetch (auth required)
 * - updateMyProfile: current member of profile update (auth required)
 */
import {
  workspaceuserV1GetMyProfile,
  workspaceuserV1UpdateMyProfile,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const memberProfileRouter = router({
  /**
   * current member of workspace profile fetch
   */
  getMyProfile: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await workspaceuserV1GetMyProfile({
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

  /**
   * current member of workspace profile update
   */
  updateMyProfile: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        name: z.string().min(1).optional(),
        locale: z.string().min(1).optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const body: Record<string, string> = {};
        if (input.name != null) {
          body.name = input.name;
        }
        if (input.locale != null) {
          body.locale = input.locale;
        }

        const { data } = await workspaceuserV1UpdateMyProfile({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body,
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),
});
