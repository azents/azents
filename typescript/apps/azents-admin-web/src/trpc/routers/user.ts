/**
 * User tRPC router
 *
 * Provides user management by communicating with the Azents Admin API server-side.
 * Uses the generated client (@azents/admin-client).
 */
import {
  type UserResponse,
  userV1DeleteUser,
  userV1GetUser,
  userV1ListUsers,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { protectedProcedure, router } from "../init";

const USER_PAGE_SIZE = 200;

// --- Router ---
export const userRouter = router({
  /**
   * List users
   */
  list: protectedProcedure.query(async ({ ctx }) => {
    const { data } = await userV1ListUsers({
      client: ctx.adminApiClient,
      throwOnError: true,
    });

    return {
      items: data.items,
      total: data.total,
    };
  }),

  /**
   * List every user for Admin selectors
   */
  listAll: protectedProcedure.query(async ({ ctx }) => {
    const items: UserResponse[] = [];
    let offset = 0;
    let total = 0;

    do {
      const { data } = await userV1ListUsers({
        client: ctx.adminApiClient,
        query: { offset, limit: USER_PAGE_SIZE },
        throwOnError: true,
      });
      items.push(...data.items);
      total = data.total;
      if (data.items.length === 0) {
        break;
      }
      offset += data.items.length;
    } while (items.length < total);

    return { items, total };
  }),

  /**
   * Get user details
   */
  get: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ ctx, input }) => {
      const { data } = await userV1GetUser({
        client: ctx.adminApiClient,
        path: { user_id: input.id },
        throwOnError: true,
      });
      return data;
    }),

  /**
   * Delete a user
   */
  delete: protectedProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ ctx, input }) => {
      try {
        await userV1DeleteUser({
          client: ctx.adminApiClient,
          path: { user_id: input.id },
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
