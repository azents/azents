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
  workspaceuserV1TransferWorkspaceOwnership,
  workspaceuserV1UpdateWorkspaceUser,
  workspaceuserV1UpdateWorkspaceUserRole,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { protectedProcedure, router } from "../init";

// --- Input Schemas ---
const WorkspaceMemberCreateInput = z.object({
  workspace_handle: z.string(),
  user_id: z.string(),
  name: z.string().min(1).max(255),
  role: z.enum(["owner", "manager", "member"]),
});

const WorkspaceMemberUpdateInput = z.object({
  workspace_user_id: z.string(),
  name: z.string().min(1).max(255).optional(),
});

const WorkspaceMemberRoleUpdateInput = z.object({
  workspace_user_id: z.string(),
  role: z.enum(["manager", "member"]),
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
      try {
        const { data } = await workspaceuserV1CreateWorkspaceUser({
          client: ctx.adminApiClient,
          body: input,
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  /**
   * Update a WorkspaceUser
   */
  update: protectedProcedure
    .input(WorkspaceMemberUpdateInput)
    .mutation(async ({ ctx, input }) => {
      try {
        const { workspace_user_id, ...body } = input;
        const { data } = await workspaceuserV1UpdateWorkspaceUser({
          client: ctx.adminApiClient,
          path: { workspace_user_id },
          body,
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          422: "BAD_REQUEST",
        });
      }
    }),

  /**
   * Update a non-Owner WorkspaceUser role
   */
  updateRole: protectedProcedure
    .input(WorkspaceMemberRoleUpdateInput)
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await workspaceuserV1UpdateWorkspaceUserRole({
          client: ctx.adminApiClient,
          path: { workspace_user_id: input.workspace_user_id },
          body: { role: input.role },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  /**
   * Transfer ownership to an existing Workspace member
   */
  transferOwnership: protectedProcedure
    .input(
      z.object({
        workspace_handle: z.string(),
        new_owner_workspace_user_id: z.string(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await workspaceuserV1TransferWorkspaceOwnership({
          client: ctx.adminApiClient,
          path: { handle: input.workspace_handle },
          body: {
            new_owner_workspace_user_id: input.new_owner_workspace_user_id,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  /**
   * Delete a WorkspaceUser
   */
  delete: protectedProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ ctx, input }) => {
      try {
        await workspaceuserV1DeleteWorkspaceUser({
          client: ctx.adminApiClient,
          path: { workspace_user_id: input.id },
          throwOnError: true,
        });
        return { success: true };
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),
});
