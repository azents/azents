/**
 * WorkspaceMember tRPC router
 *
 * Provides WorkspaceUser (workspace member) management by communicating with the Azents Admin API server-side.
 * Uses the generated client (@azents/admin-client).
 */
import {
  workspaceuserV1CreateWorkspaceUser,
  workspaceuserV1DeleteWorkspaceUser,
  workspaceuserV1GetWorkspaceUser,
  workspaceuserV1ListWorkspaceUsers,
  workspaceuserV1UpdateWorkspaceUser,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { protectedProcedure, router } from "../init";

// --- Input Schemas ---
const WorkspaceMemberCreateInput = z.object({
  workspace_handle: z.string(),
  user_id: z.string(),
  name: z.string().min(1).max(100),
  role: z.enum(["owner", "manager", "member"]),
});

const WorkspaceMemberUpdateInput = z.object({
  workspace_user_id: z.string(),
  name: z.string().min(1).max(100).optional(),
});

// --- Router ---
export const workspaceMemberRouter = router({
  /**
   * List members for a workspace
   */
  listByWorkspace: protectedProcedure
    .input(z.object({ workspace_handle: z.string() }))
    .query(async ({ ctx, input }) => {
      const { data } = await workspaceuserV1ListWorkspaceUsers({
        client: ctx.adminApiClient,
        path: { handle: input.workspace_handle },
        throwOnError: true,
      });

      return {
        items: data.items,
        total: data.items.length,
      };
    }),

  /**
   * Get WorkspaceUser details
   */
  get: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ ctx, input }) => {
      const { data } = await workspaceuserV1GetWorkspaceUser({
        client: ctx.adminApiClient,
        path: { workspace_user_id: input.id },
        throwOnError: true,
      });
      return data;
    }),

  /**
   * Create a WorkspaceUser
   */
  create: protectedProcedure
    .input(WorkspaceMemberCreateInput)
    .mutation(async ({ ctx, input }) => {
      const { data } = await workspaceuserV1CreateWorkspaceUser({
        client: ctx.adminApiClient,
        body: input,
        throwOnError: true,
      });
      return data;
    }),

  /**
   * Update a WorkspaceUser
   */
  update: protectedProcedure
    .input(WorkspaceMemberUpdateInput)
    .mutation(async ({ ctx, input }) => {
      const { workspace_user_id, ...body } = input;
      const { data } = await workspaceuserV1UpdateWorkspaceUser({
        client: ctx.adminApiClient,
        path: { workspace_user_id },
        body,
        throwOnError: true,
      });
      return data;
    }),

  /**
   * Delete a WorkspaceUser
   */
  delete: protectedProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ ctx, input }) => {
      await workspaceuserV1DeleteWorkspaceUser({
        client: ctx.adminApiClient,
        path: { workspace_user_id: input.id },
        throwOnError: true,
      });

      return { success: true };
    }),
});
