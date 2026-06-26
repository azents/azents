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
  chatV1ApproveAgentProjectRegistrationRequest,
  chatV1CreateCommand,
  chatV1CreateMessage,
  chatV1CreateTeamAgentSession,
  chatV1DeleteAgentProject,
  chatV1DeleteInputBuffer,
  chatV1EditMessage,
  chatV1GetAgentSession,
  chatV1GetAgentSessionContext,
  chatV1GetAgentWorkspace,
  chatV1GetTeamPrimaryAgentSession,
  chatV1IssueWsTicket,
  chatV1ListAgentProjectRegistrationRequests,
  chatV1ListAgentProjects,
  chatV1ListAgentSessions,
  chatV1ListHistoryEvents,
  chatV1ListLiveEvents,
  chatV1ListSlashCommands,
  chatV1ReadAgentWorkspacePath,
  chatV1RegisterAgentProject,
  chatV1RejectAgentProjectRegistrationRequest,
  chatV1StopSessionRun,
  chatV1UpdateAgentSessionTitle,
  chatV1UpdateSessionGoal,
  chatV1UpdateSessionGoalStatus,
} from "@azents/public-client";
import { z } from "zod/v4";
import { getServerConfig } from "@/config/server";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const chatRouter = router({
  /**
   * Team primary session fetch. If absent, backend creates it.
   */
  getTeamPrimaryAgentSession: publicProcedure
    .input(z.object({ agentId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1GetTeamPrimaryAgentSession({
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
    .input(z.object({ agentId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1CreateTeamAgentSession({
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

  listAgentProjectRegistrationRequests: publicProcedure
    .input(
      z.object({ agentId: z.string().min(1), sessionId: z.string().min(1) }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1ListAgentProjectRegistrationRequests({
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

  approveAgentProjectRegistrationRequest: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
        requestId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1ApproveAgentProjectRegistrationRequest({
          client: ctx.apiClient,
          path: {
            agent_id: input.agentId,
            session_id: input.sessionId,
            request_id: input.requestId,
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

  rejectAgentProjectRegistrationRequest: publicProcedure
    .input(
      z.object({
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
        requestId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await chatV1RejectAgentProjectRegistrationRequest({
          client: ctx.apiClient,
          path: {
            agent_id: input.agentId,
            session_id: input.sessionId,
            request_id: input.requestId,
          },
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

  listSlashCommands: publicProcedure.query(async ({ ctx }) => {
    const { data } = await chatV1ListSlashCommands({
      client: ctx.apiClient,
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

  sendMessage: publicProcedure
    .input(
      z.object({
        sessionId: z.string().min(1),
        agentId: z.string().min(1),
        clientRequestId: z.string().min(1).max(64),
        message: z.string().min(1),
        attachments: z.array(z.string().min(1)).optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1CreateMessage({
          client: ctx.apiClient,
          path: { session_id: input.sessionId },
          body: {
            agent_id: input.agentId,
            client_request_id: input.clientRequestId,
            message: input.message,
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

  sendCommand: publicProcedure
    .input(
      z.object({
        sessionId: z.string().min(1),
        agentId: z.string().min(1),
        clientRequestId: z.string().min(1).max(64),
        command: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1CreateCommand({
          client: ctx.apiClient,
          path: { session_id: input.sessionId },
          body: {
            agent_id: input.agentId,
            client_request_id: input.clientRequestId,
            command: input.command,
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
   * Agent team primary session context inspector fetch
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
        sessionId: z.string().min(1),
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
});
