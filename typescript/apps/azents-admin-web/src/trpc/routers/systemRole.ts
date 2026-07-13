import {
  systemV1GetSystemAdminMe,
  systemV1GrantSystemAdmin,
  systemV1ListSystemRoleAssignments,
  systemV1RevokeSystemAdmin,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { protectedProcedure, router } from "../init";

export const systemRoleRouter = router({
  me: protectedProcedure.input(z.object({})).query(async ({ ctx }) => {
    try {
      const { data } = await systemV1GetSystemAdminMe({
        client: ctx.adminApiClient,
        throwOnError: true,
      });
      return data;
    } catch (error) {
      throw mapExpectedError(error, {
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
      });
    }
  }),

  list: protectedProcedure.input(z.object({})).query(async ({ ctx }) => {
    try {
      const { data } = await systemV1ListSystemRoleAssignments({
        client: ctx.adminApiClient,
        query: { offset: 0, limit: 1000 },
        throwOnError: true,
      });
      return data;
    } catch (error) {
      throw mapExpectedError(error, {
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
      });
    }
  }),

  grantAdmin: protectedProcedure
    .input(z.object({ userId: z.string() }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await systemV1GrantSystemAdmin({
          client: ctx.adminApiClient,
          path: { user_id: input.userId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  revokeAdmin: protectedProcedure
    .input(z.object({ userId: z.string() }))
    .mutation(async ({ ctx, input }) => {
      try {
        await systemV1RevokeSystemAdmin({
          client: ctx.adminApiClient,
          path: { user_id: input.userId },
          throwOnError: true,
        });
        return { success: true };
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),
});
