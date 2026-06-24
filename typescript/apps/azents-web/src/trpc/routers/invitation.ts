/**
 * Invitation tRPC router
 *
 * workspace invitation create, received invitation fetch, accept, decline:
 * - create: workspace to user invitation (auth required, manager or higher)
 * - listReceived: received invitation list fetch (auth required)
 * - accept: invitation accept (auth required)
 * - decline: invitation decline (auth required)
 */
import {
  invitationV1AcceptInvitation,
  invitationV1CancelInvitation,
  invitationV1CreateInvitation,
  invitationV1DeclineInvitation,
  invitationV1GetMyInvitation,
  invitationV1ListReceivedInvitations,
  invitationV1ListWorkspaceInvitations,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const invitationRouter = router({
  /**
   * workspace to user invitation
   * - Bearer token auth required
   * - manager or higher permission required
   */
  create: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        email: z.email(),
        role: z.enum(["member", "manager"]).optional().default("member"),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await invitationV1CreateInvitation({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: {
            email: input.email,
            role: input.role,
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
   * received invitation list fetch
   */
  listReceived: publicProcedure.query(async ({ ctx }) => {
    try {
      const { data } = await invitationV1ListReceivedInvitations({
        client: ctx.apiClient,
        throwOnError: true,
      });
      return data;
    } catch (e) {
      throw mapExpectedError(e, { 401: "UNAUTHORIZED" });
    }
  }),

  /**
   * invitation accept
   */
  accept: publicProcedure
    .input(z.object({ invitationId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await invitationV1AcceptInvitation({
          client: ctx.apiClient,
          path: { invitation_id: input.invitationId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  /**
   * invitation decline
   */
  decline: publicProcedure
    .input(z.object({ invitationId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await invitationV1DeclineInvitation({
          client: ctx.apiClient,
          path: { invitation_id: input.invitationId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  /**
   * Per-workspace invitation list fetch
   * - Bearer token auth required
   * - member or higher permission required
   */
  listByWorkspace: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await invitationV1ListWorkspaceInvitations({
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
   * Per-workspace my invitation fetch
   * - Bearer token auth required
   */
  getMyInvitation: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await invitationV1GetMyInvitation({
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
   * invitation cancel
   * - Bearer token auth required
   * - manager or higher permission required
   */
  cancel: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        invitationId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await invitationV1CancelInvitation({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            invitation_id: input.invitationId,
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
