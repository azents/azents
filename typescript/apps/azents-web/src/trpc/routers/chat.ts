/**
 * Chat tRPC router
 *
 * WebSocket for attachment ticket issue, message history fetch.
 */
import {
  agentRuntimeV1ResetAgentRuntime,
  agentRuntimeV1RestartAgentRuntime,
  agentRuntimeV1StartAgentRuntime,
  agentRuntimeV1StopAgentRuntime,
  chatV1ArchiveAgentSession,
  chatV1BulkDeleteAgentWorkspacePaths,
  chatV1BulkMoveAgentWorkspacePaths,
  chatV1CleanupSessionGitWorktree,
  chatV1CreateAgentWorkspaceDirectory,
  chatV1CreateInput,
  chatV1CreateTeamAgentSession,
  chatV1CreateTeamAgentSessionMessage,
  chatV1DeleteAgentProject,
  chatV1DeleteAgentWorkspacePath,
  chatV1DeleteInputBuffer,
  chatV1DiscardActionExecution,
  chatV1EditMessage,
  chatV1GetAgentSession,
  chatV1GetAgentSessionContext,
  chatV1GetAgentSessionProjectDefaults,
  chatV1GetAgentWorkspace,
  chatV1GetSessionProjectBrowserManifest,
  chatV1GetSubagentTree,
  chatV1IssueWsTicket,
  chatV1ListAgentProjectPresets,
  chatV1ListAgentProjects,
  chatV1ListAgentSessions,
  chatV1ListHistoryEvents,
  chatV1ListInputActions,
  chatV1ListLiveEvents,
  chatV1MoveAgentWorkspacePath,
  chatV1PreviewAgentGitRefs,
  chatV1PreviewProjectBrowserManifest,
  chatV1ReadAgentWorkspacePath,
  chatV1RegisterAgentProject,
  chatV1RetryActionExecution,
  chatV1RetryFailedRun,
  chatV1StatAgentWorkspacePath,
  chatV1StopSessionRun,
  chatV1UpdateAgentSessionTitle,
  chatV1UpdateSessionGoal,
  chatV1UpdateSessionGoalStatus,
} from "@azents/public-client";
import { z } from "zod/v4";
import { getServerConfig } from "@/config/server";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const inputActionSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("command"), name: z.string().min(1) }),
  z.object({ type: z.literal("goal") }),
  z.object({ type: z.literal("skill"), skill_path: z.string().min(1) }),
]);

const inferenceProfileSchema = z.object({
  model_target_label: z.string().min(1),
  reasoning_effort: z
    .enum(["none", "minimal", "low", "medium", "high", "xhigh", "max"])
    .nullable(),
});

const setupActionSchema = z.object({
  type: z.literal("create_git_worktree"),
  source_project_path: z.string().min(1),
  starting_ref: z.string().min(1),
});

export const chatRouter = router({
  getAgentSession: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1GetAgentSession({
          client: ctx.apiClient,
          path: { agent_id: input.agentId, session_id: input.sessionId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          404: "NOT_FOUND",
        });
      }
    }),

  getSubagentTree: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1GetSubagentTree({
          client: ctx.apiClient,
          path: { agent_id: input.agentId, session_id: input.sessionId },
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

  listAgentSessions: publicProcedure
    .input(z.object({ agentId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1ListAgentSessions({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          404: "NOT_FOUND",
        });
      }
    }),

  createTeamAgentSession: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        existingProjectPaths: z.array(z.string().min(1)),
        setupActions: z.array(setupActionSchema),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1CreateTeamAgentSession({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          body: {
            existing_project_paths: input.existingProjectPaths,
            setup_actions: input.setupActions,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  createTeamAgentSessionMessage: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        clientRequestId: z.string().min(1).max(64),
        message: z.string().min(1),
        inferenceProfile: inferenceProfileSchema,
        attachments: z.array(z.string().min(1)).optional(),
        existingProjectPaths: z.array(z.string().min(1)),
        setupActions: z.array(setupActionSchema),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1CreateTeamAgentSessionMessage({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          body: {
            client_request_id: input.clientRequestId,
            message: input.message,
            inference_profile: input.inferenceProfile,
            existing_project_paths: input.existingProjectPaths,
            setup_actions: input.setupActions,
            attachments: input.attachments,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  updateAgentSessionTitle: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
        title: z.string().min(1).max(200).nullable(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1UpdateAgentSessionTitle({
          client: ctx.apiClient,
          path: { session_id: input.sessionId },
          body: { title: input.title },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  archiveAgentSession: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await chatV1ArchiveAgentSession({
          client: ctx.apiClient,
          path: { agent_id: input.agentId, session_id: input.sessionId },
          throwOnError: true,
        });
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  listAgentProjects: publicProcedure
    .input(
      z.object({ agentId: z.string().min(1), sessionId: z.string().min(1) }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1ListAgentProjects({
          client: ctx.apiClient,
          path: { agent_id: input.agentId, session_id: input.sessionId },
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

  listAgentProjectPresets: publicProcedure
    .input(z.object({ agentId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1ListAgentProjectPresets({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          404: "NOT_FOUND",
        });
      }
    }),

  getAgentSessionProjectDefaults: publicProcedure
    .input(z.object({ agentId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1GetAgentSessionProjectDefaults({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          404: "NOT_FOUND",
        });
      }
    }),

  previewAgentGitRefs: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sourceProjectPath: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1PreviewAgentGitRefs({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          query: { source_project_path: input.sourceProjectPath },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  getSessionProjectBrowserManifest: publicProcedure
    .input(
      z.object({ agentId: z.string().min(1), sessionId: z.string().min(1) }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1GetSessionProjectBrowserManifest({
          client: ctx.apiClient,
          path: { agent_id: input.agentId, session_id: input.sessionId },
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

  previewProjectBrowserManifest: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        projectPaths: z.array(z.string().min(1)),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1PreviewProjectBrowserManifest({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          body: { project_paths: input.projectPaths },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  registerAgentProject: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
        path: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1RegisterAgentProject({
          client: ctx.apiClient,
          path: { agent_id: input.agentId, session_id: input.sessionId },
          body: {
            path: input.path,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  createSessionGitWorktreeProject: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
        clientRequestId: z.string().min(1).max(64),
        sourceProjectPath: z.string().min(1),
        startingRef: z.string().min(1),
        inferenceProfile: inferenceProfileSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1CreateInput({
          client: ctx.apiClient,
          path: { session_id: input.sessionId },
          body: {
            agent_id: input.agentId,
            client_request_id: input.clientRequestId,
            message: "",
            inference_profile: input.inferenceProfile,
            action: {
              type: "create_git_worktree",
              source_project_path: input.sourceProjectPath,
              starting_ref: input.startingRef,
            },
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  deleteAgentProject: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
        projectId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await chatV1DeleteAgentProject({
          client: ctx.apiClient,
          path: {
            agent_id: input.agentId,
            session_id: input.sessionId,
            project_id: input.projectId,
          },
          throwOnError: true,
        });
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /**
   * WebSocket attach information fetch
   * - Receive short-lived HMAC ticket issued by backend and return it (prevents JWT exposure)
   */
  getConnectionInfo: publicProcedure.query(async ({ ctx }) => {
    const config = getServerConfig();

    // public URL for browser → WS URL convert
    const wsUrl = config.publicApiUrl
      .replace(/^https:/, "wss:")
      .replace(/^http:/, "ws:");

    try {
      const { data } = await chatV1IssueWsTicket({
        client: ctx.apiClient,
        throwOnError: true,
      });
      return { wsUrl, ticket: data.ticket };
    } catch {
      // auth even on failure wsUrl is return (unauthenticated status)
      return { wsUrl, ticket: null };
    }
  }),

  listInputActions: publicProcedure
    .input(z.object({ sessionId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      const { data } = await chatV1ListInputActions({
        client: ctx.apiClient,
        path: { session_id: input.sessionId },
        throwOnError: true,
      });
      return data;
    }),

  listSessionEvents: publicProcedure
    .input(
      z.object({
        sessionId: z.string().min(1),
        limit: z.number().min(1).max(100).optional(),
        before: z.string().optional(),
        after: z.string().optional(),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const [history, live] = await Promise.all([
          chatV1ListHistoryEvents({
            client: ctx.apiClient,
            path: { session_id: input.sessionId },
            query: {
              limit: input.limit,
              before: input.before,
              after: input.after,
            },
            throwOnError: true,
          }),
          chatV1ListLiveEvents({
            client: ctx.apiClient,
            path: { session_id: input.sessionId },
            throwOnError: true,
          }),
        ]);
        return {
          history: history.data,
          live: live.data,
        };
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  retryActionExecution: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
        actionExecutionId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1RetryActionExecution({
          client: ctx.apiClient,
          path: {
            agent_id: input.agentId,
            session_id: input.sessionId,
            action_execution_id: input.actionExecutionId,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  discardActionExecution: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
        actionExecutionId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1DiscardActionExecution({
          client: ctx.apiClient,
          path: {
            agent_id: input.agentId,
            session_id: input.sessionId,
            action_execution_id: input.actionExecutionId,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  cleanupSessionGitWorktree: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
        projectId: z.string().min(1).nullable(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await chatV1CleanupSessionGitWorktree({
          client: ctx.apiClient,
          path: { agent_id: input.agentId, session_id: input.sessionId },
          body: { project_id: input.projectId },
          throwOnError: true,
        });
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  deleteInputBuffer: publicProcedure
    .input(
      z.object({
        sessionId: z.string().min(1),
        bufferId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      await chatV1DeleteInputBuffer({
        client: ctx.apiClient,
        path: {
          session_id: input.sessionId,
          buffer_id: input.bufferId,
        },
        throwOnError: true,
      });
    }),

  sendInput: publicProcedure
    .input(
      z.object({
        sessionId: z.string().min(1),
        agentId: z.string().min(1),
        clientRequestId: z.string().min(1).max(64),
        message: z.string(),
        action: inputActionSchema.nullable().optional(),
        inferenceProfile: inferenceProfileSchema.nullable(),
        attachments: z.array(z.string().min(1)).optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1CreateInput({
          client: ctx.apiClient,
          path: { session_id: input.sessionId },
          body: {
            agent_id: input.agentId,
            client_request_id: input.clientRequestId,
            message: input.message,
            action: input.action ?? null,
            inference_profile: input.inferenceProfile,
            attachments: input.attachments,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  editMessage: publicProcedure
    .input(
      z.object({
        sessionId: z.string().min(1),
        agentId: z.string().min(1),
        clientRequestId: z.string().min(1).max(64),
        messageId: z.string().min(1),
        message: z.string().min(1),
        inferenceProfile: inferenceProfileSchema,
        attachments: z.array(z.string().min(1)).optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1EditMessage({
          client: ctx.apiClient,
          path: { session_id: input.sessionId },
          body: {
            agent_id: input.agentId,
            client_request_id: input.clientRequestId,
            message_id: input.messageId,
            message: input.message,
            inference_profile: input.inferenceProfile,
            attachments: input.attachments,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  retryFailedRun: publicProcedure
    .input(
      z.object({
        sessionId: z.string().min(1),
        agentId: z.string().min(1),
        failedEventId: z.string().min(1),
        clientRequestId: z.string().min(1).max(64),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1RetryFailedRun({
          client: ctx.apiClient,
          path: { session_id: input.sessionId },
          body: {
            agent_id: input.agentId,
            failed_event_id: input.failedEventId,
            client_request_id: input.clientRequestId,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  updateSessionGoal: publicProcedure
    .input(
      z.object({
        sessionId: z.string().min(1),
        objective: z.string().min(1).max(4000).nullable(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1UpdateSessionGoal({
          client: ctx.apiClient,
          path: { session_id: input.sessionId },
          body: { objective: input.objective },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  updateSessionGoalStatus: publicProcedure
    .input(
      z.object({
        sessionId: z.string().min(1),
        status: z.enum(["active", "paused"]),
        resumeHint: z.string().trim().max(2000).optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1UpdateSessionGoalStatus({
          client: ctx.apiClient,
          path: { session_id: input.sessionId },
          body: { status: input.status, resume_hint: input.resumeHint },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  stopSessionRun: publicProcedure
    .input(z.object({ sessionId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1StopSessionRun({
          client: ctx.apiClient,
          path: { session_id: input.sessionId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /**
   * Agent session context inspector fetch.
   */
  getAgentSessionContext: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
        limit: z.number().min(1).max(500).optional(),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1GetAgentSessionContext({
          client: ctx.apiClient,
          path: { agent_id: input.agentId, session_id: input.sessionId },
          query: { limit: input.limit },
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
   * Agent workspace bootstrap status fetch
   */
  getAgentWorkspace: publicProcedure
    .input(z.object({ agentId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1GetAgentWorkspace({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
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

  startAgentRuntime: publicProcedure
    .input(z.object({ handle: z.string().min(1), agentId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentRuntimeV1StartAgentRuntime({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
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

  stopAgentRuntime: publicProcedure
    .input(z.object({ handle: z.string().min(1), agentId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentRuntimeV1StopAgentRuntime({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
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

  restartAgentRuntime: publicProcedure
    .input(z.object({ handle: z.string().min(1), agentId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentRuntimeV1RestartAgentRuntime({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
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

  resetAgentRuntime: publicProcedure
    .input(z.object({ handle: z.string().min(1), agentId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentRuntimeV1ResetAgentRuntime({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: { final_desired_state: "running" },
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
   * Agent workspace directory or file preview fetch
   */
  readAgentWorkspacePath: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1).optional(),
        path: z.string().min(1),
        limit: z.number().min(1).max(1_048_576).optional(),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1ReadAgentWorkspacePath({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          query: { path: input.path, limit: input.limit },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          413: "PAYLOAD_TOO_LARGE",
        });
      }
    }),

  statAgentWorkspacePath: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        path: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1StatAgentWorkspacePath({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          query: { path: input.path },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  createAgentWorkspaceDirectory: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        path: z.string().min(1),
        parents: z.boolean().optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1CreateAgentWorkspaceDirectory({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          body: { path: input.path, parents: input.parents },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  deleteAgentWorkspacePath: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        path: z.string().min(1),
        recursive: z.boolean().optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1DeleteAgentWorkspacePath({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          body: { path: input.path, recursive: input.recursive },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  bulkDeleteAgentWorkspacePaths: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        paths: z.array(z.string().min(1)).min(1),
        recursive: z.boolean().optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1BulkDeleteAgentWorkspacePaths({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          body: { paths: input.paths, recursive: input.recursive },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  moveAgentWorkspacePath: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sourcePath: z.string().min(1),
        destinationPath: z.string().min(1),
        overwrite: z.boolean().optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1MoveAgentWorkspacePath({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          body: {
            source_path: input.sourcePath,
            destination_path: input.destinationPath,
            overwrite: input.overwrite,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  bulkMoveAgentWorkspacePaths: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sourcePaths: z.array(z.string().min(1)).min(1),
        destinationDirectory: z.string().min(1),
        overwrite: z.boolean().optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1BulkMoveAgentWorkspacePaths({
          client: ctx.apiClient,
          path: { agent_id: input.agentId },
          body: {
            source_paths: input.sourcePaths,
            destination_directory: input.destinationDirectory,
            overwrite: input.overwrite,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),
});
