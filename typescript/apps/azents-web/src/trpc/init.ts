/**
 * Initialize tRPC instance
 */
import * as Sentry from "@sentry/nextjs";
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
        // Include stack trace only in development environment
        ...(getServerConfig().nodeEnv === "development" && {
          stack: error.stack,
        }),
      },
    };
  },
});

/** Error logging middleware */
const loggerMiddleware = t.middleware(async ({ path, type, next }) => {
  const start = Date.now();
  const result = await next();
  const durationMs = Date.now() - start;

  if (result.ok) {
    console.log(`tRPC ${type} ${path} OK (${durationMs}ms)`);
  } else if (result.error.code === "INTERNAL_SERVER_ERROR") {
    const cause = result.error.cause;
    console.error(`tRPC failed on ${path}:`, {
      code: result.error.code,
      message: result.error.message,
      // Original response information on hey-api throwOnError
      ...(cause && {
        cause: cause instanceof Error ? cause.message : cause,
        ...(typeof cause === "object" &&
          "status" in cause && {
            status: (cause as { status: unknown }).status,
          }),
        ...(typeof cause === "object" &&
          "body" in cause && { body: (cause as { body: unknown }).body }),
      }),
      durationMs,
    });

    Sentry.captureException(cause ?? result.error, {
      extra: { path, type, durationMs },
    });
  }

  return result;
});

export const router = t.router;
export const publicProcedure = t.procedure.use(loggerMiddleware);
export const createCallerFactory = t.createCallerFactory;
