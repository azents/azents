/**
 * Workspace tRPC router
 *
 * Provides workspace management by communicating with the Azents Admin API server-side.
 * Uses the generated client (@azents/admin-client).
 */
import {
  workspaceV1CreateWorkspace,
  workspaceV1GetWorkspace,
  workspaceV1ListWorkspaces,
  workspaceV1UpdateWorkspace,
} from "@azents/admin-client";
import { z } from "zod/v4";
import { protectedProcedure, router } from "../init";

// --- Input Schemas ---
const WorkspaceCreateInput = z.object({
  name: z.string().min(1).max(100),
  handle: z.string().min(1).max(100),
});

const WorkspaceUpdateInput = z.object({
  handle: z.string(),
  name: z.string().min(1).max(100),
  new_handle: z.string().min(1).max(100),
});

// --- Router ---
export const workspaceRouter = router({
  /**
   * List workspaces
   */
  list: protectedProcedure.query(async ({ ctx }) => {
    const { data } = await workspaceV1ListWorkspaces({
      client: ctx.adminApiClient,
      throwOnError: true,
    });
    return {
      items: data.items,
      total: data.items.length,
    };
  }),

  /**
   * Get workspace details
   */
  get: protectedProcedure
    .input(z.object({ handle: z.string() }))
    .query(async ({ ctx, input }) => {
      const { data } = await workspaceV1GetWorkspace({
        client: ctx.adminApiClient,
        path: { handle: input.handle },
        throwOnError: true,
      });
      return data;
    }),

  /**
   * Create a workspace
   */
  create: protectedProcedure
    .input(WorkspaceCreateInput)
    .mutation(async ({ ctx, input }) => {
      const { data } = await workspaceV1CreateWorkspace({
        client: ctx.adminApiClient,
        body: input,
        throwOnError: true,
      });
      return data;
    }),

  /**
   * Update a workspace
   */
  update: protectedProcedure
    .input(WorkspaceUpdateInput)
    .mutation(async ({ ctx, input }) => {
      const { handle, ...body } = input;
      const { data } = await workspaceV1UpdateWorkspace({
        client: ctx.adminApiClient,
        path: { handle },
        body: { name: body.name, handle: body.new_handle },
        throwOnError: true,
      });
      return data;
    }),
});
