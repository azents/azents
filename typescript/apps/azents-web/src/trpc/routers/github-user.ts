import {
  githubUserToolkitV1AgentAccess,
  githubUserToolkitV1AgentCancel,
  githubUserToolkitV1AgentConfirm,
  githubUserToolkitV1AgentConnect,
  githubUserToolkitV1AgentDisconnect,
  githubUserToolkitV1AgentExchange,
  githubUserToolkitV1AgentReview,
  githubUserToolkitV1AgentSetupAvailability,
  githubUserToolkitV1AgentStatus,
  githubUserToolkitV1SharedAccess,
  githubUserToolkitV1SharedCancel,
  githubUserToolkitV1SharedConfirm,
  githubUserToolkitV1SharedConnect,
  githubUserToolkitV1SharedDisconnect,
  githubUserToolkitV1SharedExchange,
  githubUserToolkitV1SharedReview,
  githubUserToolkitV1SharedSetupAvailability,
  githubUserToolkitV1SharedStatus,
  personalGithubToolkitV1PersonalGithubAccess,
  personalGithubToolkitV1PersonalGithubAvailability,
  personalGithubToolkitV1PersonalGithubCancel,
  personalGithubToolkitV1PersonalGithubConfirm,
  personalGithubToolkitV1PersonalGithubConnect,
  personalGithubToolkitV1PersonalGithubDisconnect,
  personalGithubToolkitV1PersonalGithubExchange,
  personalGithubToolkitV1PersonalGithubReview,
  personalGithubToolkitV1PersonalGithubStatus,
} from "@azents/public-client";
import { z } from "zod/v4";
import { toolkitScopedInput } from "@/shared/toolkits/toolkit-owner-scope";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const contextFields = { toolkitId: z.string().min(1) };
const attemptFields = {
  ...contextFields,
  attemptId: z.string().min(1).max(64),
};
const scope = toolkitScopedInput({});
const context = toolkitScopedInput(contextFields);
const attempt = toolkitScopedInput(attemptFields);

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

/** Ownership-specific generated SDK adapters; context never comes from the provider. */
export const githubUserRouter = router({
  availability: publicProcedure.input(scope).query(async ({ ctx, input }) => {
    if ("owner" in input) {
      const { data } = await request(() =>
        personalGithubToolkitV1PersonalGithubAvailability({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        }),
      );
      return data;
    }
    const { data } = await request(() =>
      input.agentId == null
        ? githubUserToolkitV1SharedSetupAvailability({
            client: ctx.apiClient,
            path: { handle: input.handle },
            throwOnError: true,
          })
        : githubUserToolkitV1AgentSetupAvailability({
            client: ctx.apiClient,
            path: { handle: input.handle, agent_id: input.agentId },
            throwOnError: true,
          }),
    );
    return data;
  }),
  connect: publicProcedure.input(context).mutation(async ({ ctx, input }) => {
    if ("owner" in input) {
      const { data } = await request(() =>
        personalGithubToolkitV1PersonalGithubConnect({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          throwOnError: true,
        }),
      );
      return data;
    }
    const { data } = await request(() =>
      input.agentId == null
        ? githubUserToolkitV1SharedConnect({
            client: ctx.apiClient,
            path: { handle: input.handle, toolkit_id: input.toolkitId },
            throwOnError: true,
          })
        : githubUserToolkitV1AgentConnect({
            client: ctx.apiClient,
            path: {
              handle: input.handle,
              agent_id: input.agentId,
              toolkit_id: input.toolkitId,
            },
            throwOnError: true,
          }),
    );
    return data;
  }),
  exchange: publicProcedure
    .input(
      toolkitScopedInput({
        ...contextFields,
        code: z.string().min(1).max(4096),
        state: z.string().min(1).max(4096),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const body = { code: input.code, state: input.state };
      if ("owner" in input) {
        const { data } = await request(() =>
          personalGithubToolkitV1PersonalGithubExchange({
            client: ctx.apiClient,
            path: { handle: input.handle, toolkit_id: input.toolkitId },
            body,
            throwOnError: true,
          }),
        );
        return data;
      }
      const { data } = await request(() =>
        input.agentId == null
          ? githubUserToolkitV1SharedExchange({
              client: ctx.apiClient,
              path: { handle: input.handle, toolkit_id: input.toolkitId },
              body,
              throwOnError: true,
            })
          : githubUserToolkitV1AgentExchange({
              client: ctx.apiClient,
              path: {
                handle: input.handle,
                agent_id: input.agentId,
                toolkit_id: input.toolkitId,
              },
              body,
              throwOnError: true,
            }),
      );
      return data;
    }),
  review: publicProcedure.input(attempt).query(async ({ ctx, input }) => {
    if ("owner" in input) {
      const { data } = await request(() =>
        personalGithubToolkitV1PersonalGithubReview({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          query: { attempt_id: input.attemptId },
          throwOnError: true,
        }),
      );
      return data;
    }
    const { data } = await request(() =>
      input.agentId == null
        ? githubUserToolkitV1SharedReview({
            client: ctx.apiClient,
            path: {
              handle: input.handle,
              toolkit_id: input.toolkitId,
              attempt_id: input.attemptId,
            },
            throwOnError: true,
          })
        : githubUserToolkitV1AgentReview({
            client: ctx.apiClient,
            path: {
              handle: input.handle,
              agent_id: input.agentId,
              toolkit_id: input.toolkitId,
              attempt_id: input.attemptId,
            },
            throwOnError: true,
          }),
    );
    return data;
  }),
  confirm: publicProcedure.input(attempt).mutation(async ({ ctx, input }) => {
    const body = { attempt_id: input.attemptId };
    if ("owner" in input) {
      const { data } = await request(() =>
        personalGithubToolkitV1PersonalGithubConfirm({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          body,
          throwOnError: true,
        }),
      );
      return data;
    }
    const { data } = await request(() =>
      input.agentId == null
        ? githubUserToolkitV1SharedConfirm({
            client: ctx.apiClient,
            path: { handle: input.handle, toolkit_id: input.toolkitId },
            body,
            throwOnError: true,
          })
        : githubUserToolkitV1AgentConfirm({
            client: ctx.apiClient,
            path: {
              handle: input.handle,
              agent_id: input.agentId,
              toolkit_id: input.toolkitId,
            },
            body,
            throwOnError: true,
          }),
    );
    return data;
  }),
  cancel: publicProcedure.input(attempt).mutation(async ({ ctx, input }) => {
    const body = { attempt_id: input.attemptId };
    if ("owner" in input) {
      await request(() =>
        personalGithubToolkitV1PersonalGithubCancel({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          body,
          throwOnError: true,
        }),
      );
      return null;
    }
    await request(() =>
      input.agentId == null
        ? githubUserToolkitV1SharedCancel({
            client: ctx.apiClient,
            path: { handle: input.handle, toolkit_id: input.toolkitId },
            body,
            throwOnError: true,
          })
        : githubUserToolkitV1AgentCancel({
            client: ctx.apiClient,
            path: {
              handle: input.handle,
              agent_id: input.agentId,
              toolkit_id: input.toolkitId,
            },
            body,
            throwOnError: true,
          }),
    );
    return null;
  }),
  disconnect: publicProcedure
    .input(context)
    .mutation(async ({ ctx, input }) => {
      if ("owner" in input) {
        await request(() =>
          personalGithubToolkitV1PersonalGithubDisconnect({
            client: ctx.apiClient,
            path: { handle: input.handle, toolkit_id: input.toolkitId },
            throwOnError: true,
          }),
        );
        return null;
      }
      await request(() =>
        input.agentId == null
          ? githubUserToolkitV1SharedDisconnect({
              client: ctx.apiClient,
              path: { handle: input.handle, toolkit_id: input.toolkitId },
              throwOnError: true,
            })
          : githubUserToolkitV1AgentDisconnect({
              client: ctx.apiClient,
              path: {
                handle: input.handle,
                agent_id: input.agentId,
                toolkit_id: input.toolkitId,
              },
              throwOnError: true,
            }),
      );
      return null;
    }),
  status: publicProcedure.input(context).query(async ({ ctx, input }) => {
    if ("owner" in input) {
      const { data } = await request(() =>
        personalGithubToolkitV1PersonalGithubStatus({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          throwOnError: true,
        }),
      );
      return data;
    }
    const { data } = await request(() =>
      input.agentId == null
        ? githubUserToolkitV1SharedStatus({
            client: ctx.apiClient,
            path: { handle: input.handle, toolkit_id: input.toolkitId },
            throwOnError: true,
          })
        : githubUserToolkitV1AgentStatus({
            client: ctx.apiClient,
            path: {
              handle: input.handle,
              agent_id: input.agentId,
              toolkit_id: input.toolkitId,
            },
            throwOnError: true,
          }),
    );
    return data;
  }),
  access: publicProcedure
    .input(
      toolkitScopedInput({
        ...contextFields,
        cursor: z.string().max(4096).nullable(),
      }),
    )
    .query(async ({ ctx, input }) => {
      if ("owner" in input) {
        const { data } = await request(() =>
          personalGithubToolkitV1PersonalGithubAccess({
            client: ctx.apiClient,
            path: { handle: input.handle, toolkit_id: input.toolkitId },
            query: { cursor: input.cursor },
            throwOnError: true,
          }),
        );
        return data;
      }
      const { data } = await request(() =>
        input.agentId == null
          ? githubUserToolkitV1SharedAccess({
              client: ctx.apiClient,
              path: { handle: input.handle, toolkit_id: input.toolkitId },
              query: { cursor: input.cursor },
              throwOnError: true,
            })
          : githubUserToolkitV1AgentAccess({
              client: ctx.apiClient,
              path: {
                handle: input.handle,
                agent_id: input.agentId,
                toolkit_id: input.toolkitId,
              },
              query: { cursor: input.cursor },
              throwOnError: true,
            }),
      );
      return data;
    }),
});
