import {
  chatV1GetAgentSessionRoutine,
  chatV1ListAgentSessionRoutines,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const sessionInput = z.object({
  agentId: z.string().min(1),
  sessionId: z.string().min(1),
});

function mapRoutineError(error: unknown): unknown {
  return mapExpectedError(error, {
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    422: "BAD_REQUEST",
  });
}

export const routineRouter = router({
  list: publicProcedure.input(sessionInput).query(async ({ ctx, input }) => {
    try {
      const { data } = await chatV1ListAgentSessionRoutines({
        client: ctx.apiClient,
        path: { agent_id: input.agentId, session_id: input.sessionId },
        throwOnError: true,
      });
      return data;
    } catch (error) {
      throw mapRoutineError(error);
    }
  }),
  detail: publicProcedure
    .input(sessionInput.extend({ slug: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatV1GetAgentSessionRoutine({
          client: ctx.apiClient,
          path: {
            agent_id: input.agentId,
            session_id: input.sessionId,
            slug: input.slug,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapRoutineError(error);
      }
    }),
});
