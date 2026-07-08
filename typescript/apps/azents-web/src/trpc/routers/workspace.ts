/**
 * Workspace tRPC router
 *
 * workspace fetch/create:
 * - list: current user belongs to workspace list fetch (auth required)
 * - create: workspace create (auth required)
 */
import {
  workspaceV1BootstrapFirstOwner,
  workspaceV1CreateWorkspace,
  workspaceV1GetBootstrapStatus,
  workspaceV1ListWorkspaces,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const workspaceRouter = router({
  bootstrapStatus: publicProcedure.query(async ({ ctx }) => {
    try {
      const { data } = await workspaceV1GetBootstrapStatus({
        client: ctx.apiClient,
        throwOnError: true,
      });
      return data;
    } catch (e) {
      throw mapExpectedError(e, { 422: "BAD_REQUEST" });
    }
  }),

  bootstrapFirstOwner: publicProcedure
    .input(
      z.object({
        email: z.string().email(),
        password: z.string().min(1),
        ownerName: z.string().min(1).max(50),
        workspaceName: z.string().min(1).max(50),
        workspaceHandle: z.string().min(1).max(30),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await workspaceV1BootstrapFirstOwner({
          client: ctx.apiClient,
          body: {
            email: input.email,
            password: input.password,
            owner_name: input.ownerName,
            workspace_name: input.workspaceName,
            workspace_handle: input.workspaceHandle,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          403: "FORBIDDEN",
          409: "CONFLICT",
          422: "BAD_REQUEST",
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
        locale: z.string().optional(),
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
            locale: input.locale,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, { 400: "BAD_REQUEST", 409: "CONFLICT" });
      }
    }),
});
