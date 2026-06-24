/**
 * Verification tRPC 라우터
 *
 * azents admin API 서버와 서버사이드 통신하여 이메일 인증 레코드 조회 기능을 제공합니다.
 * Generated client (@azents/admin-client)를 사용합니다.
 */
import {
  authV1GetEmailVerification,
  authV1ListEmailVerifications,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { publicProcedure, router } from "../init";

// --- Router ---
export const verificationRouter = router({
  /**
   * 이메일 인증 목록 조회
   */
  list: publicProcedure.query(async ({ ctx }) => {
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
   * 이메일 인증 상세 조회
   */
  get: publicProcedure
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
