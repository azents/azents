/**
 * User tRPC 라우터
 *
 * azents admin API 서버와 서버사이드 통신하여 User 관리 기능을 제공합니다.
 * Generated client (@azents/admin-client)를 사용합니다.
 */
import {
  userV1DeleteUser,
  userV1GetUser,
  userV1ListUsers,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { protectedProcedure, router } from "../init";

// --- Router ---
export const userRouter = router({
  /**
   * User 목록 조회
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
   * User 상세 조회
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
   * User 삭제
   */
  delete: protectedProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ ctx, input }) => {
      await userV1DeleteUser({
        client: ctx.adminApiClient,
        path: { user_id: input.id },
        throwOnError: true,
      });

      return { success: true };
    }),
});
