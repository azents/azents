/**
 * UserEmail tRPC 라우터
 *
 * azents admin API 서버와 서버사이드 통신하여 UserEmail 관리 기능을 제공합니다.
 * Generated client (@azents/admin-client)를 사용합니다.
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
   * User별 이메일 목록 조회
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
   * UserEmail 생성
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
   * UserEmail 삭제
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
