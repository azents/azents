/**
 * tRPC 인스턴스 초기화
 */
import { initTRPC } from "@trpc/server";
import superjson from "superjson";
import { getServerConfig } from "@/config/server";
import type { Context } from "./context";

const t = initTRPC.context<Context>().create({
  transformer: superjson,
  errorFormatter({ shape, error }) {
    return {
      ...shape,
      data: {
        ...shape.data,
        // 개발 환경에서만 스택 트레이스 포함
        ...(getServerConfig().nodeEnv === "development" && {
          stack: error.stack,
        }),
      },
    };
  },
});

export const router = t.router;
export const publicProcedure = t.procedure;
export const createCallerFactory = t.createCallerFactory;
