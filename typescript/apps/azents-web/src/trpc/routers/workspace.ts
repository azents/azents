/**
 * Workspace tRPC router
 *
 * workspace fetch/create:
 * - list: current user belongs to workspace list fetch (auth required)
 * - create: workspace create (auth required)
 */
import {
  workspaceV1CreateWorkspace,
  workspaceV1GetAgentEnvironmentSelection,
  workspaceV1GetWorkspaceByHandle,
  workspaceV1GetWorkspaceEnvironment,
  workspaceV1ListWorkspaces,
  workspaceV1ReplaceAgentEnvironmentSelection,
  workspaceV1ReplaceWorkspaceEnvironment,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const workspaceRouter = router({
  getEnvironment: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        return (
          await workspaceV1GetWorkspaceEnvironment({
            client: ctx.apiClient,
            path: { handle: input.handle },
            throwOnError: true,
          })
        ).data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),
  replaceEnvironment: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        entries: z
          .array(
            z.object({
              id: z.string().nullable(),
              name: z.string().min(1).max(64),
              value: z.discriminatedUnion("type", [
                z.object({ type: z.literal("stored"), name: z.string() }),
                z.object({
                  type: z.literal("replace"),
                  value: z.string().max(4096),
                }),
              ]),
            }),
          )
          .max(50),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        return (
          await workspaceV1ReplaceWorkspaceEnvironment({
            client: ctx.apiClient,
            path: { handle: input.handle },
            body: { entries: input.entries },
            throwOnError: true,
          })
        ).data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          422: "BAD_REQUEST",
        });
      }
    }),
  getAgentEnvironmentSelection: publicProcedure
    .input(z.object({ handle: z.string().min(1), agentId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        return (
          await workspaceV1GetAgentEnvironmentSelection({
            client: ctx.apiClient,
            path: { handle: input.handle, agent_id: input.agentId },
            throwOnError: true,
          })
        ).data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),
  replaceAgentEnvironmentSelection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        selectedIds: z.array(z.string()).max(50),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        return (
          await workspaceV1ReplaceAgentEnvironmentSelection({
            client: ctx.apiClient,
            path: { handle: input.handle, agent_id: input.agentId },
            body: { selected_ids: input.selectedIds },
            throwOnError: true,
          })
        ).data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          422: "BAD_REQUEST",
        });
      }
    }),
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
