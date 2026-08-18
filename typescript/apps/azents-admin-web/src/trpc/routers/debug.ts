/**
 * Debug tRPC router
 *
 * Provides debug operations for validating Sentry and logging integration.
 */
import { debugV1FireException, debugV1FireLog } from "@azents/admin-client";
import { z } from "zod/v4";
import { protectedProcedure, router } from "../init";

export const debugRouter = router({
  /**
   * Emit a log at the specified level
   */
  fireLog: protectedProcedure
    .input(
      z.object({
        level: z.enum(["warning", "error", "critical"]),
        message: z.string(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const { data } = await debugV1FireLog({
        client: ctx.adminApiClient,
        query: { level: input.level, message: input.message },
        throwOnError: true,
      });
      return data;
    }),

  /**
   * Raise an unhandled exception (500 error)
   */
  fireException: protectedProcedure
    .input(z.object({ message: z.string() }))
    .mutation(async ({ ctx, input }) => {
      const { data } = await debugV1FireException({
        client: ctx.adminApiClient,
        query: { message: input.message },
        throwOnError: true,
      });
      return data;
    }),
});
