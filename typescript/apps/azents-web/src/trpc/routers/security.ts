/**
 * Security tRPC router
 *
 * Security settings:
 * 1. auth method fetch
 * 2. Step-up auth (elevation) — email OTP / password
 * 3. password set/delete
 */
import {
  securityV1ElevateWithEmail,
  securityV1ElevateWithPassword,
  securityV1GetAuthMethods,
  securityV1GetElevationMethods,
  securityV1RemovePassword,
  securityV1SendElevationCode,
  securityV1SetPassword,
} from "@azents/public-client";
import { z } from "zod/v4";
import { getRefreshToken, setAuthCookiesToHeaders } from "@/shared/lib/cookies";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const securityRouter = router({
  /**
   * auth method fetch
   */
  getAuthMethods: publicProcedure.query(async ({ ctx }) => {
    try {
      const { data } = await securityV1GetAuthMethods({
        client: ctx.apiClient,
        throwOnError: true,
      });
      return data;
    } catch (e) {
      throw mapExpectedError(e, { 401: "UNAUTHORIZED", 403: "FORBIDDEN" });
    }
  }),

  /**
   * Elevation to use available auth method fetch (elevation not required)
   */
  getElevationMethods: publicProcedure.query(async ({ ctx }) => {
    try {
      const { data } = await securityV1GetElevationMethods({
        client: ctx.apiClient,
        throwOnError: true,
      });
      return data;
    } catch (e) {
      throw mapExpectedError(e, { 401: "UNAUTHORIZED" });
    }
  }),

  /**
   * Send email OTP for step-up auth
   */
  sendElevationCode: publicProcedure.mutation(async ({ ctx }) => {
    try {
      const { data } = await securityV1SendElevationCode({
        client: ctx.apiClient,
        throwOnError: true,
      });
      return data;
    } catch (e) {
      throw mapExpectedError(e, { 401: "UNAUTHORIZED" });
    }
  }),

  /**
   * email OTP with elevation
   * - on success, replace cookies with elevated access token
   */
  elevateWithEmail: publicProcedure
    .input(
      z.object({
        code: z.string(),
        csrfToken: z.string(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await securityV1ElevateWithEmail({
          client: ctx.apiClient,
          body: {
            code: input.code,
            csrf_token: input.csrfToken,
          },
          throwOnError: true,
        });

        const refreshToken = await getRefreshToken();
        if (refreshToken) {
          setAuthCookiesToHeaders(ctx.resHeaders, {
            accessToken: data.access_token,
            refreshToken,
            expiresInSeconds: data.expires_in,
          });
        }

        return { success: true };
      } catch (e) {
        throw mapExpectedError(e, { 400: "BAD_REQUEST", 401: "UNAUTHORIZED" });
      }
    }),

  /**
   * password with elevation
   * - on success, replace cookies with elevated access token
   */
  elevateWithPassword: publicProcedure
    .input(z.object({ password: z.string() }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await securityV1ElevateWithPassword({
          client: ctx.apiClient,
          body: { password: input.password },
          throwOnError: true,
        });

        const refreshToken = await getRefreshToken();
        if (refreshToken) {
          setAuthCookiesToHeaders(ctx.resHeaders, {
            accessToken: data.access_token,
            refreshToken,
            expiresInSeconds: data.expires_in,
          });
        }

        return { success: true };
      } catch (e) {
        throw mapExpectedError(e, { 400: "BAD_REQUEST", 401: "UNAUTHORIZED" });
      }
    }),

  /**
   * password set/change
   */
  setPassword: publicProcedure
    .input(z.object({ password: z.string() }))
    .mutation(async ({ ctx, input }) => {
      try {
        await securityV1SetPassword({
          client: ctx.apiClient,
          body: { password: input.password },
          throwOnError: true,
        });
        return { success: true };
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          403: "FORBIDDEN",
        });
      }
    }),

  /**
   * password delete
   */
  removePassword: publicProcedure.mutation(async ({ ctx }) => {
    try {
      await securityV1RemovePassword({
        client: ctx.apiClient,
        throwOnError: true,
      });
      return { success: true };
    } catch (e) {
      throw mapExpectedError(e, { 403: "FORBIDDEN" });
    }
  }),
});
