/**
 * Debug tRPC 라우터
 *
 * Sentry/로깅 연동 검증을 위한 디버그 기능을 제공합니다.
 */
import { debugV1FireException, debugV1FireLog } from "@azents/admin-client";
import { z } from "zod/v4";
import { protectedProcedure, router } from "../init";

export const debugRouter = router({
  /**
   * 지정 레벨로 로그 발생
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
   * 미처리 예외 발생 (500 에러)
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
