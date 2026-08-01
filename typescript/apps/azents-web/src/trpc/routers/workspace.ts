/**
 * Workspace tRPC router
 *
 * workspace fetch/create:
 * - list: current user belongs to workspace list fetch (auth required)
 * - create: workspace create (auth required)
 */
import {
  workspaceV1CreateWorkspace,
  workspaceV1GetWorkspaceByHandle,
  workspaceV1ListWorkspaces,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const workspaceRouter = router({
  get: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await workspaceV1GetWorkspaceByHandle({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /**
   * workspace list fetch
   * - Bearer token auth required (context.apiClient to included)
   */
  list: publicProcedure.query(async ({ ctx }) => {
    try {
      const { data } = await workspaceV1ListWorkspaces({
        client: ctx.apiClient,
        throwOnError: true,
      });
      return data;
    } catch (e) {
      throw mapExpectedError(e, { 401: "UNAUTHORIZED" });
    }
  }),

  /**
   * workspace create
   */
  create: publicProcedure
    .input(
      z.object({
        workspaceName: z.string().min(1).max(50),
        workspaceHandle: z.string().min(1).max(30),
        ownerName: z.string().min(1).max(50),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await workspaceV1CreateWorkspace({
          client: ctx.apiClient,
          body: {
            workspace_name: input.workspaceName,
            workspace_handle: input.workspaceHandle,
            owner_name: input.ownerName,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, { 400: "BAD_REQUEST", 409: "CONFLICT" });
      }
    }),
});
