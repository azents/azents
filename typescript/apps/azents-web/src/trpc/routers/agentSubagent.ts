/**
 * AgentSubagent tRPC router
 *
 * Agent-Subagent attach CRUD:
 * - list: attach list fetch
 * - create: attach add
 * - update: attach update
 * - remove: attach delete
 */
import {
  agentV1CreateAgentSubagent,
  agentV1DeleteAgentSubagent,
  agentV1ListAgentSubagents,
  agentV1UpdateAgentSubagent,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const agentSubagentRouter = router({
  /**
   * Agent to attach Subagent list fetch
   */
  list: publicProcedure
    .input(z.object({ handle: z.string().min(1), agentId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1ListAgentSubagents({
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

  /**
   * Subagent attach add
   */
  create: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        subagentId: z.string().min(1),
        description: z.string().min(1),
        enabled: z.boolean().optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1CreateAgentSubagent({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: {
            subagent_id: input.subagentId,
            description: input.description,
            enabled: input.enabled ?? true,
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
          422: "BAD_REQUEST",
        });
      }
    }),

  /**
   * Subagent attach update (description, enabled)
   */
  update: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        agentSubagentId: z.string().min(1),
        description: z.string().optional(),
        enabled: z.boolean().optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1UpdateAgentSubagent({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            agent_subagent_id: input.agentSubagentId,
          },
          body: {
            description: input.description,
            enabled: input.enabled,
          },
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
   * Subagent attach delete
   */
  remove: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        agentSubagentId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await agentV1DeleteAgentSubagent({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            agent_subagent_id: input.agentSubagentId,
          },
          throwOnError: true,
        });
        return null;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),
});
