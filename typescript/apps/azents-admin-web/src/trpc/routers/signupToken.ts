import {
  authV1CreateSignupToken,
  authV1ListSignupTokens,
  authV1RevokeSignupToken,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { getServerConfig } from "@/config/server";
import { mapExpectedError } from "../api-error";
import { protectedProcedure, router } from "../init";

function buildSignupUrl(publicWebUrl: string, plaintextToken: string): string {
  const baseUrl = publicWebUrl.replace(/\/$/, "");
  return `${baseUrl}/signup?token=${encodeURIComponent(plaintextToken)}`;
}

export const signupTokenRouter = router({
  list: protectedProcedure.query(async ({ ctx }) => {
    try {
      const { data } = await authV1ListSignupTokens({
        client: ctx.adminApiClient,
        throwOnError: true,
      });
      return data;
    } catch (e) {
      throw mapExpectedError(e, { 401: "UNAUTHORIZED", 403: "FORBIDDEN" });
    }
  }),

  create: protectedProcedure
    .input(
      z.object({
        email: z.string().email(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await authV1CreateSignupToken({
          client: ctx.adminApiClient,
          body: {
            email: input.email,
            delivery_method: "manual",
          },
          throwOnError: true,
        });
        return {
          ...data,
          signupUrl: buildSignupUrl(
            getServerConfig().publicWebUrl,
            data.plaintext_token,
          ),
        };
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          422: "BAD_REQUEST",
        });
      }
    }),

  revoke: protectedProcedure
    .input(z.object({ tokenId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        await authV1RevokeSignupToken({
          client: ctx.adminApiClient,
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
