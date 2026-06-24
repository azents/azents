/**
 * WorkspaceMember tRPC router
 *
 * workspace member fetch, role change, delete:
 * - list: workspace member list fetch (auth required, member or higher)
 * - updateRole: member role change (auth required, manager or higher)
 * - remove: member delete (auth required, manager or higher)
 */
import {
  workspaceuserV1DeleteWorkspaceUser,
  workspaceuserV1GetCurrentMember,
  workspaceuserV1ListWorkspaceUsers,
  workspaceuserV1UpdateWorkspaceUserRole,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const workspaceMemberRouter = router({
  /**
   * current user of workspace member information fetch
   */
  me: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await workspaceuserV1GetCurrentMember({
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
   * workspace member list fetch
   * - Bearer token auth required
   * - member or higher permission required
   */
  list: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await workspaceuserV1ListWorkspaceUsers({
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
   * member role change
   * - Bearer token auth required
   * - manager or higher permission required
   */
  updateRole: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        workspaceUserId: z.string().min(1),
        role: z.enum(["owner", "manager", "member"]),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await workspaceuserV1UpdateWorkspaceUserRole({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            workspace_user_id: input.workspaceUserId,
          },
          body: {
            role: input.role,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /**
   * member delete
   * - Bearer token auth required
   * - manager or higher permission required
   */
  remove: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        workspaceUserId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await workspaceuserV1DeleteWorkspaceUser({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            workspace_user_id: input.workspaceUserId,
          },
          throwOnError: true,
        });
        return null;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),
});
