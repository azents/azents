/**
 * JoinRequest tRPC router
 *
 * workspace join request create, fetch, approve, decline, mute, delete:
 * - create: join request create (auth required)
 * - getMyRequest: my join request fetch (auth required)
 * - list: workspace join request list fetch (manager or higher)
 * - approve: join request approve (manager or higher)
 * - reject: join request decline (manager or higher)
 * - mute: join request mute (manager or higher)
 * - delete: join request delete (manager or higher)
 */
import {
  joinRequestV1ApproveJoinRequest,
  joinRequestV1CreateJoinRequest,
  joinRequestV1DeleteJoinRequest,
  joinRequestV1GetMyJoinRequest,
  joinRequestV1ListJoinRequests,
  joinRequestV1MuteJoinRequest,
  joinRequestV1RejectJoinRequest,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const joinRequestRouter = router({
  /**
   * join request create
   * - Bearer token auth required
   */
  create: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        message: z.string().nullable().optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await joinRequestV1CreateJoinRequest({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: {
            message: input.message ?? null,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          403: "FORBIDDEN",
          409: "CONFLICT",
        });
      }
    }),

  /**
   * my join request fetch
   * - Bearer token auth required
   */
  getMyRequest: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await joinRequestV1GetMyJoinRequest({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          404: "NOT_FOUND",
        });
      }
    }),

  /**
   * workspace join request list fetch
   * - Bearer token auth required
   * - manager or higher permission required
   */
  list: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await joinRequestV1ListJoinRequests({
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

  /**
   * join request approve
   * - Bearer token auth required
   * - manager or higher permission required
   */
  approve: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        joinRequestId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await joinRequestV1ApproveJoinRequest({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            join_request_id: input.joinRequestId,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /**
   * join request decline
   * - Bearer token auth required
   * - manager or higher permission required
   */
  reject: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        joinRequestId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await joinRequestV1RejectJoinRequest({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            join_request_id: input.joinRequestId,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /**
   * join request mute
   * - Bearer token auth required
   * - manager or higher permission required
   */
  mute: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        joinRequestId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await joinRequestV1MuteJoinRequest({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            join_request_id: input.joinRequestId,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /**
   * join request delete
   * - Bearer token auth required
   * - manager or higher permission required
   */
  delete: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        joinRequestId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await joinRequestV1DeleteJoinRequest({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            join_request_id: input.joinRequestId,
          },
          throwOnError: true,
        });
        return null;
      } catch (e) {
        throw mapExpectedError(e, {
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),
});
