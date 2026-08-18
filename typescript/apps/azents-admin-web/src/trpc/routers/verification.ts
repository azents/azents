/**
 * Verification tRPC router
 *
 * Provides email verification queries by communicating with the Azents Admin API server-side.
 * Uses the generated client (@azents/admin-client).
 */
import {
  authV1GetEmailVerification,
  authV1ListEmailVerifications,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { protectedProcedure, router } from "../init";

// --- Router ---
export const verificationRouter = router({
  /**
   * List email verifications
   */
  list: protectedProcedure.query(async ({ ctx }) => {
    const { data } = await authV1ListEmailVerifications({
      client: ctx.adminApiClient,
      throwOnError: true,
    });
    return {
      items: data.items,
      total: data.total,
    };
  }),

  /**
   * Get email verification details
   */
  get: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ ctx, input }) => {
      const { data } = await authV1GetEmailVerification({
        client: ctx.adminApiClient,
        path: { verification_id: input.id },
        throwOnError: true,
      });
      return data;
    }),
});
