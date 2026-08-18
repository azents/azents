/**
 * UserEmail tRPC router
 *
 * Provides UserEmail management by communicating with the Azents Admin API server-side.
 * Uses the generated client (@azents/admin-client).
 */
import {
  useremailV1CreateEmail,
  useremailV1DeleteEmail,
  useremailV1ListEmailsByUser,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { protectedProcedure, router } from "../init";

// --- Router ---
export const userEmailRouter = router({
  /**
   * List emails by user
   */
  listByUser: protectedProcedure
    .input(z.object({ user_id: z.string() }))
    .query(async ({ ctx, input }) => {
      const { data } = await useremailV1ListEmailsByUser({
        client: ctx.adminApiClient,
        path: { user_id: input.user_id },
        throwOnError: true,
      });

      return {
        items: data.items,
        total: data.total,
      };
    }),

  /**
   * Create a UserEmail
   */
  create: protectedProcedure
    .input(
      z.object({
        user_id: z.string(),
        email: z.string().email(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const { data } = await useremailV1CreateEmail({
        client: ctx.adminApiClient,
        path: { user_id: input.user_id },
        body: { email: input.email },
        throwOnError: true,
      });
      return data;
    }),

  /**
   * Delete a UserEmail
   */
  delete: protectedProcedure
    .input(z.object({ email_id: z.string() }))
    .mutation(async ({ ctx, input }) => {
      await useremailV1DeleteEmail({
        client: ctx.adminApiClient,
        path: { email_id: input.email_id },
        throwOnError: true,
      });

      return { success: true };
    }),
});
