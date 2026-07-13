import {
  systemBootstrapV1BootstrapFirstSystemAdmin,
  systemBootstrapV1GetSystemBootstrapStatus,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { createBootstrapAdminApiClient } from "@/shared/lib/api-clients";
import { setAdminAuthCookies } from "@/shared/lib/auth-cookies";
import { mapExpectedError, withApiErrorInterceptor } from "../api-error";
import { bootstrapProcedure, router } from "../init";

function createBootstrapClient(): ReturnType<
  typeof createBootstrapAdminApiClient
> {
  return withApiErrorInterceptor(createBootstrapAdminApiClient());
}

export const bootstrapRouter = router({
  status: bootstrapProcedure.query(async () => {
    const { data } = await systemBootstrapV1GetSystemBootstrapStatus({
      client: createBootstrapClient(),
      throwOnError: true,
    });
    return data;
  }),

  firstAdmin: bootstrapProcedure
    .input(
      z.object({
        setupToken: z.string().min(1),
        email: z.string().email(),
        password: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await systemBootstrapV1BootstrapFirstSystemAdmin({
          client: createBootstrapClient(),
          headers: { "X-Azents-Setup-Token": input.setupToken },
          body: {
            email: input.email,
            password: input.password,
          },
          throwOnError: true,
        });
        setAdminAuthCookies(ctx.responseHeaders, {
          accessToken: data.access_token,
          refreshToken: data.refresh_token,
          expiresInSeconds: data.expires_in,
        });
        return { success: true };
      } catch (error) {
        throw mapExpectedError(error, {
          400: "BAD_REQUEST",
          403: "FORBIDDEN",
          422: "BAD_REQUEST",
        });
      }
    }),
});
