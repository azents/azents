import {
  browserV1CloseBrowserPage,
  browserV1GetBrowserProjection,
  chatV1IssueWsTicket,
} from "@azents/public-client";
import { z } from "zod/v4";
import { getServerConfig } from "@/config/server";
import { browserSocketUrl } from "@/features/session-browser/socketUrl";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const resource = z.object({
  handle: z.string().min(1),
  agentId: z.string().min(1),
  sessionId: z.string().min(1),
});
const expectedErrors = {
  401: "UNAUTHORIZED",
  403: "FORBIDDEN",
  404: "NOT_FOUND",
  409: "CONFLICT",
} as const;

export const browserRouter = router({
  connectionInfo: publicProcedure
    .input(resource)
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1IssueWsTicket({
          client: ctx.apiClient,
          throwOnError: true,
        });
        return {
          ticket: data.ticket,
          websocketUrl: browserSocketUrl(getServerConfig().publicApiUrl, input),
        };
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),
  projection: publicProcedure.input(resource).query(async ({ ctx, input }) => {
    try {
      const { data } = await browserV1GetBrowserProjection({
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
      throw mapExpectedError(error, expectedErrors);
    }
  }),
  closePage: publicProcedure
    .input(
      resource.extend({
        taskId: z.string().min(1).max(128),
        pageId: z.string().min(1).max(128),
        resourceIncarnation: z.string().min(1).max(128),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await browserV1CloseBrowserPage({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            session_id: input.sessionId,
            page_id: input.pageId,
          },
          body: {
            task_id: input.taskId,
            resource_incarnation: input.resourceIncarnation,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),
});
