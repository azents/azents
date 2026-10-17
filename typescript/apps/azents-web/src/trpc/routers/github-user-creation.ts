import {
  githubUserCreationV1AgentCreationApp,
  githubUserCreationV1AgentCreationCancel,
  githubUserCreationV1AgentCreationConfirm,
  githubUserCreationV1AgentCreationConnect,
  githubUserCreationV1AgentCreationExchange,
  githubUserCreationV1AgentCreationReview,
  githubUserCreationV1SharedCreationApp,
  githubUserCreationV1SharedCreationCancel,
  githubUserCreationV1SharedCreationConfirm,
  githubUserCreationV1SharedCreationConnect,
  githubUserCreationV1SharedCreationExchange,
  githubUserCreationV1SharedCreationReview,
  personalGithubToolkitV1PersonalGithubCreationApp,
  personalGithubToolkitV1PersonalGithubCreationCancel,
  personalGithubToolkitV1PersonalGithubCreationConfirm,
  personalGithubToolkitV1PersonalGithubCreationConnect,
  personalGithubToolkitV1PersonalGithubCreationExchange,
  personalGithubToolkitV1PersonalGithubCreationReview,
} from "@azents/public-client";
import { z } from "zod/v4";
import { toolkitScopedInput } from "@/shared/toolkits/toolkit-owner-scope";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const attemptFields = { attemptId: z.string().min(1).max(64) };
const attempt = toolkitScopedInput(attemptFields);
const finalSettings = z
  .object({
    name: z.string().nullable(),
    slug: z.string().nullable(),
    description: z.string().nullable(),
    prompt: z.string().nullable(),
    enabled: z.boolean(),
    always_expose_tools: z.boolean(),
    toolsets: z.array(z.string()),
    timeout: z.number().positive(),
    inject_runtime_environment: z.boolean(),
    runtime_risk_acknowledged: z.boolean(),
  })
  .strict();
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
  app: publicProcedure.input(attempt).query(async ({ ctx, input }) => {
    if ("owner" in input) {
      const { data } = await request(() =>
        personalGithubToolkitV1PersonalGithubCreationApp({
          client: ctx.apiClient,
          path: { handle: input.handle, attempt_id: input.attemptId },
          throwOnError: true,
        }),
      );
      return data;
    }
    const { data } = await request(() =>
      input.agentId == null
        ? githubUserCreationV1SharedCreationApp({
            client: ctx.apiClient,
            path: { handle: input.handle, attempt_id: input.attemptId },
            throwOnError: true,
          })
        : githubUserCreationV1AgentCreationApp({
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
  connect: publicProcedure
    .input(
      toolkitScopedInput({
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
      if ("owner" in input) {
        const { data } = await request(() =>
          personalGithubToolkitV1PersonalGithubCreationConnect({
            client: ctx.apiClient,
            path: { handle: input.handle },
            body,
            throwOnError: true,
          }),
        );
        return data;
      }
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
      toolkitScopedInput({
        code: z.string().min(1).max(4096),
        state: z.string().min(1).max(4096),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const body = { code: input.code, state: input.state };
      if ("owner" in input) {
        const { data } = await request(() =>
          personalGithubToolkitV1PersonalGithubCreationExchange({
            client: ctx.apiClient,
            path: { handle: input.handle },
            body,
            throwOnError: true,
          }),
        );
        return data;
      }
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
    if ("owner" in input) {
      const { data } = await request(() =>
        personalGithubToolkitV1PersonalGithubCreationReview({
          client: ctx.apiClient,
          path: { handle: input.handle, attempt_id: input.attemptId },
          throwOnError: true,
        }),
      );
      return data;
    }
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
  confirm: publicProcedure
    .input(toolkitScopedInput({ ...attemptFields, settings: finalSettings }))
    .mutation(async ({ ctx, input }) => {
      const body = { attempt_id: input.attemptId, settings: input.settings };
      if ("owner" in input) {
        const { data } = await request(() =>
          personalGithubToolkitV1PersonalGithubCreationConfirm({
            client: ctx.apiClient,
            path: { handle: input.handle },
            body,
            throwOnError: true,
          }),
        );
        return data;
      }
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
    if ("owner" in input) {
      await request(() =>
        personalGithubToolkitV1PersonalGithubCreationCancel({
          client: ctx.apiClient,
          path: { handle: input.handle, attempt_id: input.attemptId },
          throwOnError: true,
        }),
      );
      return null;
    }
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
