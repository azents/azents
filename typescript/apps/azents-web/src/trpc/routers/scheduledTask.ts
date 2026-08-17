import {
  type AgentSessionResponse,
  chatV1ListAgentSessions,
  scheduledTaskV1CreateScheduledTask,
  scheduledTaskV1DeleteScheduledTask,
  scheduledTaskV1GetScheduledTask,
  scheduledTaskV1GetScheduledTaskCycle,
  scheduledTaskV1ListScheduledTasks,
  scheduledTaskV1ReplaceScheduledTask,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const scheduleFieldsSchema = z.object({
  title: z.string().trim().min(1).max(120),
  objective: z.string().trim().min(1).max(3_000),
  at: z.string().max(64).nullable(),
  cron: z.string().max(256).nullable(),
  timezone: z.string().max(128).nullable(),
  channelId: z.string().min(1).max(256).nullable(),
});

const sessionPageSize = 100;

function mapScheduledTaskError(error: unknown): unknown {
  return mapExpectedError(error, {
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "BAD_REQUEST",
  });
}

export const scheduledTaskRouter = router({
  listSelectableTeamSessions: publicProcedure
    .input(z.object({ agentId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const items: AgentSessionResponse[] = [];
        let offset = 0;
        for (;;) {
          const { data } = await chatV1ListAgentSessions({
            client: ctx.apiClient,
            path: { agent_id: input.agentId },
            query: {
              status: "active",
              offset,
              limit: sessionPageSize,
            },
            throwOnError: true,
          });
          items.push(...data.items);
          if (items.length >= data.total_count || data.items.length === 0) {
            return { items };
          }
          offset += data.items.length;
        }
      } catch (error) {
        throw mapScheduledTaskError(error);
      }
    }),

  list: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        sessionId: z.string().min(1).nullable(),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await scheduledTaskV1ListScheduledTasks({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          query: { session_id: input.sessionId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapScheduledTaskError(error);
      }
    }),

  get: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        taskId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await scheduledTaskV1GetScheduledTask({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            task_id: input.taskId,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapScheduledTaskError(error);
      }
    }),

  getCycle: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        taskId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await scheduledTaskV1GetScheduledTaskCycle({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            task_id: input.taskId,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapScheduledTaskError(error);
      }
    }),

  create: publicProcedure
    .input(
      scheduleFieldsSchema.extend({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await scheduledTaskV1CreateScheduledTask({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: {
            session_id: input.sessionId,
            title: input.title,
            objective: input.objective,
            at: input.at,
            cron: input.cron,
            timezone: input.timezone,
            channel_id: input.channelId,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapScheduledTaskError(error);
      }
    }),

  replace: publicProcedure
    .input(
      scheduleFieldsSchema.extend({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        taskId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await scheduledTaskV1ReplaceScheduledTask({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            task_id: input.taskId,
          },
          body: {
            title: input.title,
            objective: input.objective,
            at: input.at,
            cron: input.cron,
            timezone: input.timezone,
            channel_id: input.channelId,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapScheduledTaskError(error);
      }
    }),

  delete: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        taskId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await scheduledTaskV1DeleteScheduledTask({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            task_id: input.taskId,
          },
          throwOnError: true,
        });
      } catch (error) {
        throw mapScheduledTaskError(error);
      }
    }),
});
