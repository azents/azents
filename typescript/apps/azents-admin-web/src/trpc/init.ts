import { initTRPC, TRPCError } from "@trpc/server";
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
        ...(getServerConfig().nodeEnv === "development" && {
          stack: error.stack,
        }),
      },
    };
  },
});

const requireAuthenticatedAdmin = t.middleware(({ ctx, next }) => {
  if (!ctx.authenticated || !ctx.accessToken || !ctx.adminApiClient) {
    throw new TRPCError({
      code: "UNAUTHORIZED",
      message: "An authenticated Admin session is required.",
    });
  }
  return next({
    ctx: {
      ...ctx,
      accessToken: ctx.accessToken,
      adminApiClient: ctx.adminApiClient,
    },
  });
});

export const router = t.router;
export const bootstrapProcedure = t.procedure;
export const protectedProcedure = t.procedure.use(requireAuthenticatedAdmin);
export const createCallerFactory = t.createCallerFactory;
