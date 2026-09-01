import {
  terminalV1GetTerminalProjection,
  terminalV1IssueTerminalTicket,
} from "@azents/public-client";
import { z } from "zod/v4";
import { getServerConfig } from "@/config/server";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const resourceSchema = z.object({
  handle: z.string().min(1),
  agentId: z.string().min(1),
  sessionId: z.string().min(1),
});

function terminalWebSocketUrl(
  handle: string,
  agentId: string,
  sessionId: string,
): string {
  const base = getServerConfig().publicApiUrl.replace(/^http/, "ws");
  const resource = [handle, agentId, sessionId].map(encodeURIComponent);
  return `${base}/terminal/v1/workspaces/${resource[0]}/agents/${resource[1]}/sessions/${resource[2]}/ws`;
}

export const terminalRouter = router({
  projection: publicProcedure
    .input(resourceSchema)
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await terminalV1GetTerminalProjection({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            session_id: input.sessionId,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  ticket: publicProcedure
    .input(resourceSchema)
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await terminalV1IssueTerminalTicket({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            session_id: input.sessionId,
          },
          throwOnError: true,
        });
        return {
          ...data,
          websocketUrl: terminalWebSocketUrl(
            input.handle,
            input.agentId,
            input.sessionId,
          ),
        };
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
