/**
 * User tRPC router
 *
 * current user information fetch.
 */
import {
  userV1GetMySystemRoles,
  userV1Me,
  userV1UpdateMe,
} from "@azents/public-client";
import { z } from "zod/v4";
import { getServerConfig } from "@/config/server";
import { getAdminWebUrl } from "@/shared/lib/admin-access";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const userRouter = router({
  /**
   * current user information fetch
   */
  me: publicProcedure.query(async ({ ctx }) => {
    try {
      const { data } = await userV1Me({
        client: ctx.apiClient,
        throwOnError: true,
      });
      return data;
    } catch (e) {
      throw mapExpectedError(e, { 401: "UNAUTHORIZED" });
    }
  }),

  updateMe: publicProcedure
    .input(
      z.object({
        locale: z.enum(["en-US", "ko-KR", "ja-JP", "fr-FR"]),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await userV1UpdateMe({
          client: ctx.apiClient,
          body: { locale: input.locale },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          404: "NOT_FOUND",
          422: "BAD_REQUEST",
        });
      }
    }),

  /** Return the configured Admin Web URL only to system administrators. */
  adminAccess: publicProcedure.input(z.object({})).query(async ({ ctx }) => {
    const { adminWebUrl } = getServerConfig();
    if (!adminWebUrl) {
      return { url: null };
    }

    try {
      const { data } = await userV1GetMySystemRoles({
        client: ctx.apiClient,
        throwOnError: true,
      });
      return { url: getAdminWebUrl(adminWebUrl, data.roles) };
    } catch (e) {
      throw mapExpectedError(e, { 401: "UNAUTHORIZED" });
    }
  }),
});
