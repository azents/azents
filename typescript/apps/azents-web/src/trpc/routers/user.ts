/**
 * User tRPC router
 *
 * current user information fetch.
 */
import { userV1Me } from "@azents/public-client";
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
});
