/**
 * User tRPC router
 *
 * current user information fetch.
 */
import { userV1GetMySystemRoles, userV1Me } from "@azents/public-client";
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
