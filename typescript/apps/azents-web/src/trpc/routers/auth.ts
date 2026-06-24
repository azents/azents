/**
 * Auth tRPC router
 *
 * email auth login flow:
 * 1. email auth code send
 * 2. auth code verify and JWT issue
 * 3. token refresh (interceptor in automatically handled, manual call also possible)
 * 4. logout
 */
import {
  authV1GetLoginMethods,
  authV1GetSignupStatus,
  authV1LoginWithPassword,
  authV1Logout,
  authV1PreviewPasswordResetToken,
  authV1PreviewSignupToken,
  authV1RedeemPasswordResetToken,
  authV1RedeemSignupToken,
  authV1RefreshToken,
  authV1RequestSignupEmail,
  authV1SendCode,
  authV1VerifyCode,
} from "@azents/public-client";
import { z } from "zod/v4";
import {
  clearAuthCookiesToHeaders,
  getRefreshToken,
  setAuthCookiesToHeaders,
} from "@/shared/lib/cookies";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const authRouter = router({
  /**
   * email auth code send
   */
  sendCode: publicProcedure
    .input(z.object({ email: z.string().email() }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await authV1SendCode({
          client: ctx.apiClient,
          body: { email: input.email },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, { 400: "BAD_REQUEST", 422: "BAD_REQUEST" });
      }
    }),

  /**
   * auth code verify and JWT issue
   * - on success az-token, az-refresh, az-token-expires-at set cookies
   */
  verify: publicProcedure
    .input(
      z.object({
        email: z.string().email(),
        code: z.string(),
        csrfToken: z.string(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await authV1VerifyCode({
          client: ctx.apiClient,
          body: {
            email: input.email,
            code: input.code,
            csrf_token: input.csrfToken,
          },
          throwOnError: true,
        });

        // resHeaders through set cookies
        setAuthCookiesToHeaders(ctx.resHeaders, {
          accessToken: data.access_token,
          refreshToken: data.refresh_token,
          expiresInSeconds: data.expires_in,
        });

        return { success: true };
      } catch (e) {
        throw mapExpectedError(e, { 400: "BAD_REQUEST" });
      }
    }),

  /**
   * Token refresh (manual call)
   * - Usually handled automatically by request interceptor
   * - Used when client explicitly needs refresh
   */
  refreshToken: publicProcedure.mutation(async ({ ctx }) => {
    const refreshToken = await getRefreshToken();
    if (!refreshToken) {
      throw mapExpectedError(new Error("No refresh token"), {
        401: "UNAUTHORIZED",
      });
    }

    try {
      const { data } = await authV1RefreshToken({
        client: ctx.apiClient,
        body: { refresh_token: refreshToken },
        throwOnError: true,
      });

      setAuthCookiesToHeaders(ctx.resHeaders, {
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        expiresInSeconds: data.expires_in,
      });

      return { success: true };
    } catch (e) {
      // Delete cookies when refresh fails
      clearAuthCookiesToHeaders(ctx.resHeaders);
      throw mapExpectedError(e, { 401: "UNAUTHORIZED" });
    }
  }),

  /**
   * email to use available login methods fetch
   */
  getLoginMethods: publicProcedure
    .input(z.object({ email: z.string().email() }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await authV1GetLoginMethods({
          client: ctx.apiClient,
          query: { email: input.email },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, { 422: "BAD_REQUEST" });
      }
    }),

  /**
   * Password login
   * - on success az-token, az-refresh, az-token-expires-at set cookies
   */
  passwordLogin: publicProcedure
    .input(
      z.object({
        email: z.string().email(),
        password: z.string(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await authV1LoginWithPassword({
          client: ctx.apiClient,
          body: {
            email: input.email,
            password: input.password,
          },
          throwOnError: true,
        });

        setAuthCookiesToHeaders(ctx.resHeaders, {
          accessToken: data.access_token,
          refreshToken: data.refresh_token,
          expiresInSeconds: data.expires_in,
        });

        return { success: true };
      } catch (e) {
        throw mapExpectedError(e, { 400: "BAD_REQUEST", 401: "UNAUTHORIZED" });
      }
    }),

  getSignupStatus: publicProcedure.query(async ({ ctx }) => {
    try {
      const { data } = await authV1GetSignupStatus({
        client: ctx.apiClient,
        throwOnError: true,
      });
      return data;
    } catch (e) {
      throw mapExpectedError(e, { 422: "BAD_REQUEST" });
    }
  }),

  requestSignupEmail: publicProcedure
    .input(z.object({ email: z.string().email() }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await authV1RequestSignupEmail({
          client: ctx.apiClient,
          body: { email: input.email },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          422: "BAD_REQUEST",
          503: "PRECONDITION_FAILED",
        });
      }
    }),

  previewSignupToken: publicProcedure
    .input(z.object({ token: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await authV1PreviewSignupToken({
          client: ctx.apiClient,
          body: { token: input.token },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, { 400: "BAD_REQUEST", 422: "BAD_REQUEST" });
      }
    }),

  redeemSignupToken: publicProcedure
    .input(
      z.object({
        token: z.string().min(1),
        email: z.string().email(),
        password: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await authV1RedeemSignupToken({
          client: ctx.apiClient,
          body: {
            token: input.token,
            email: input.email,
            password: input.password,
          },
          throwOnError: true,
        });

        setAuthCookiesToHeaders(ctx.resHeaders, {
          accessToken: data.access_token,
          refreshToken: data.refresh_token,
          expiresInSeconds: data.expires_in,
        });

        return { success: true };
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  previewPasswordResetToken: publicProcedure
    .input(z.object({ token: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await authV1PreviewPasswordResetToken({
          client: ctx.apiClient,
          body: { token: input.token },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, { 400: "BAD_REQUEST", 422: "BAD_REQUEST" });
      }
    }),

  redeemPasswordResetToken: publicProcedure
    .input(
      z.object({
        token: z.string().min(1),
        password: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await authV1RedeemPasswordResetToken({
          client: ctx.apiClient,
          body: {
            token: input.token,
            password: input.password,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          422: "BAD_REQUEST",
        });
      }
    }),

  /**
   * logout
   * - Request session revocation to server, then delete cookies
   */
  logout: publicProcedure.mutation(async ({ ctx }) => {
    try {
      await authV1Logout({
        client: ctx.apiClient,
        throwOnError: true,
      });
    } catch {
      // Delete cookies even when logout fails
    }

    clearAuthCookiesToHeaders(ctx.resHeaders);

    return { success: true };
  }),
});
