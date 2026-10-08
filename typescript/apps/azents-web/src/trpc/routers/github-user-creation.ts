import {
  githubUserCreationV1AgentCreationCancel,
  githubUserCreationV1AgentCreationConfirm,
  githubUserCreationV1AgentCreationConnect,
  githubUserCreationV1AgentCreationExchange,
  githubUserCreationV1AgentCreationReview,
  githubUserCreationV1SharedCreationCancel,
  githubUserCreationV1SharedCreationConfirm,
  githubUserCreationV1SharedCreationConnect,
  githubUserCreationV1SharedCreationExchange,
  githubUserCreationV1SharedCreationReview,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const scope = z.object({
  handle: z.string().min(1),
  agentId: z.string().min(1).optional(),
});
const attempt = scope.extend({ attemptId: z.string().min(1).max(64) });
async function request<T>(operation: () => Promise<T>): Promise<T> {
  try {
    return await operation();
  } catch (error) {
    throw mapExpectedError(error, {
      400: "BAD_REQUEST",
      401: "UNAUTHORIZED",
      403: "FORBIDDEN",
      404: "NOT_FOUND",
      409: "CONFLICT",
      422: "BAD_REQUEST",
    });
  }
}

export const githubUserCreationRouter = router({
  connect: publicProcedure
    .input(
      scope.extend({
        toolkitType: z.literal("github"),
        name: z.string().optional(),
        slug: z.string().optional(),
        description: z.string().nullable(),
        prompt: z.string().nullable(),
        config: z.record(z.string(), z.unknown()),
        credentials: z.record(z.string(), z.unknown()).optional(),
        enabled: z.boolean(),
        alwaysExposeTools: z.boolean(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const body = {
        toolkit_type: input.toolkitType,
        name: input.name,
        slug: input.slug,
        description: input.description,
        prompt: input.prompt,
        config: input.config,
        credentials: input.credentials,
        enabled: input.enabled,
        always_expose_tools: input.alwaysExposeTools,
      };
      const { data } = await request(() =>
        input.agentId == null
          ? githubUserCreationV1SharedCreationConnect({
              client: ctx.apiClient,
              path: { handle: input.handle },
              body,
              throwOnError: true,
            })
          : githubUserCreationV1AgentCreationConnect({
              client: ctx.apiClient,
              path: { handle: input.handle, agent_id: input.agentId },
              body,
              throwOnError: true,
            }),
      );
      return data;
    }),
  exchange: publicProcedure
    .input(
      scope.extend({
        code: z.string().min(1).max(4096),
        state: z.string().min(1).max(4096),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const body = { code: input.code, state: input.state };
      const { data } = await request(() =>
        input.agentId == null
          ? githubUserCreationV1SharedCreationExchange({
              client: ctx.apiClient,
              path: { handle: input.handle },
              body,
              throwOnError: true,
            })
          : githubUserCreationV1AgentCreationExchange({
              client: ctx.apiClient,
              path: { handle: input.handle, agent_id: input.agentId },
              body,
              throwOnError: true,
            }),
      );
      return data;
    }),
  review: publicProcedure.input(attempt).query(async ({ ctx, input }) => {
    const { data } = await request(() =>
      input.agentId == null
        ? githubUserCreationV1SharedCreationReview({
            client: ctx.apiClient,
            path: { handle: input.handle, attempt_id: input.attemptId },
            throwOnError: true,
          })
        : githubUserCreationV1AgentCreationReview({
            client: ctx.apiClient,
            path: {
              handle: input.handle,
              agent_id: input.agentId,
              attempt_id: input.attemptId,
            },
            throwOnError: true,
          }),
    );
    return data;
  }),
  confirm: publicProcedure.input(attempt).mutation(async ({ ctx, input }) => {
    const body = { attempt_id: input.attemptId };
    const { data } = await request(() =>
      input.agentId == null
        ? githubUserCreationV1SharedCreationConfirm({
            client: ctx.apiClient,
            path: { handle: input.handle },
            body,
            throwOnError: true,
          })
        : githubUserCreationV1AgentCreationConfirm({
            client: ctx.apiClient,
            path: { handle: input.handle, agent_id: input.agentId },
            body,
            throwOnError: true,
          }),
    );
    return data;
  }),
  cancel: publicProcedure.input(attempt).mutation(async ({ ctx, input }) => {
    await request(() =>
      input.agentId == null
        ? githubUserCreationV1SharedCreationCancel({
            client: ctx.apiClient,
            path: { handle: input.handle, attempt_id: input.attemptId },
            throwOnError: true,
          })
        : githubUserCreationV1AgentCreationCancel({
            client: ctx.apiClient,
            path: {
              handle: input.handle,
              agent_id: input.agentId,
              attempt_id: input.attemptId,
            },
            throwOnError: true,
          }),
    );
    return null;
  }),
});
