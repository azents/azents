/**
 * GitHub PAT tRPC router
 *
 * Per-workspace GitHub PAT management:
 * - getStatus: PAT register status fetch
 * - getSetupStatus: settings page PAT status fetch
 * - register: PAT register (GitHub API verify then save)
 * - remove: PAT delete
 */
import {
  githubPatV1DeletePat,
  githubPatV1GetPatStatus,
  githubPatV1GetSetupStatus,
  githubPatV1RegisterPat,
} from "@azents/public-client";
import { z } from "zod/v4";

import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const githubPatRouter = router({
  /** PAT register status fetch */
  getStatus: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await githubPatV1GetPatStatus({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),

  /** settings page status fetch */
  getSetupStatus: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await githubPatV1GetSetupStatus({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),

  /** PAT register */
  register: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        token: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await githubPatV1RegisterPat({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: { token: input.token },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          422: "BAD_REQUEST",
        });
      }
    }),

  /** PAT delete */
  remove: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        await githubPatV1DeletePat({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        });
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),
});
