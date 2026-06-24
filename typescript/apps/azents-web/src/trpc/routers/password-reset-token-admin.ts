import {
  authV1CreatePasswordResetToken,
  authV1ListPasswordResetTokens,
  authV1RevokePasswordResetToken,
  createClient as createAdminClient,
  createConfig as createAdminConfig,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { getServerConfig } from "@/config/server";
import { safeFetch } from "@/shared/lib/safe-fetch";
import { mapExpectedError } from "../api-error";
import { getFreshAccessToken } from "../context";
import { publicProcedure, router } from "../init";

async function createPasswordResetTokenAdminClient(
  resHeaders: Headers,
): Promise<ReturnType<typeof createAdminClient>> {
  const config = getServerConfig();
  const client = createAdminClient(
    createAdminConfig({ baseUrl: config.internalApiUrl, fetch: safeFetch }),
  );
  const accessToken = await getFreshAccessToken(resHeaders);
  if (accessToken) {
    client.interceptors.request.use((request) => {
      request.headers.set("Authorization", `Bearer ${accessToken}`);
      return request;
    });
  }
  return client;
}

export const passwordResetTokenAdminRouter = router({
  list: publicProcedure.query(async ({ ctx }) => {
    try {
      const { data } = await authV1ListPasswordResetTokens({
        client: await createPasswordResetTokenAdminClient(ctx.resHeaders),
        throwOnError: true,
      });
      return data;
    } catch (e) {
      throw mapExpectedError(e, { 401: "UNAUTHORIZED", 403: "FORBIDDEN" });
    }
  }),

  create: publicProcedure
    .input(
      z.object({
        email: z.string().email().optional(),
        userId: z.string().min(1).optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await authV1CreatePasswordResetToken({
          client: await createPasswordResetTokenAdminClient(ctx.resHeaders),
          body: {
            email: input.email ?? null,
            user_id: input.userId ?? null,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          422: "BAD_REQUEST",
        });
      }
    }),

  revoke: publicProcedure
    .input(z.object({ tokenId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        await authV1RevokePasswordResetToken({
          client: await createPasswordResetTokenAdminClient(ctx.resHeaders),
          path: { token_id: input.tokenId },
          throwOnError: true,
        });
        return { success: true };
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),
});
