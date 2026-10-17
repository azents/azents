import {
  googleToolkitV1AgentGoogleCancel,
  googleToolkitV1AgentGoogleConfirm,
  googleToolkitV1AgentGoogleConnect,
  googleToolkitV1AgentGoogleDisconnect,
  googleToolkitV1AgentGoogleExchange,
  googleToolkitV1AgentGoogleOutcome,
  googleToolkitV1AgentGooglePreparation,
  googleToolkitV1AgentGoogleReconnect,
  googleToolkitV1AgentGoogleReconnectConfirm,
  googleToolkitV1AgentGoogleReview,
  googleToolkitV1AgentGoogleStatus,
  googleToolkitV1SharedGoogleCancel,
  googleToolkitV1SharedGoogleConfirm,
  googleToolkitV1SharedGoogleConnect,
  googleToolkitV1SharedGoogleDisconnect,
  googleToolkitV1SharedGoogleExchange,
  googleToolkitV1SharedGoogleOutcome,
  googleToolkitV1SharedGooglePreparation,
  googleToolkitV1SharedGoogleReconnect,
  googleToolkitV1SharedGoogleReconnectConfirm,
  googleToolkitV1SharedGoogleReview,
  googleToolkitV1SharedGoogleStatus,
  personalGoogleToolkitV1PersonalGoogleCancel,
  personalGoogleToolkitV1PersonalGoogleConfirm,
  personalGoogleToolkitV1PersonalGoogleConnect,
  personalGoogleToolkitV1PersonalGoogleDisconnect,
  personalGoogleToolkitV1PersonalGoogleExchange,
  personalGoogleToolkitV1PersonalGoogleOutcome,
  personalGoogleToolkitV1PersonalGooglePreparation,
  personalGoogleToolkitV1PersonalGoogleReconnect,
  personalGoogleToolkitV1PersonalGoogleReconnectConfirm,
  personalGoogleToolkitV1PersonalGoogleReview,
  personalGoogleToolkitV1PersonalGoogleStatus,
} from "@azents/public-client";
import { z } from "zod/v4";
import {
  googleDesiredSchema,
  googleFinalSettingsSchema,
  googleReconnectSettingsSchema,
} from "@/shared/toolkits/google-schemas";
import { toolkitScopedInput } from "@/shared/toolkits/toolkit-owner-scope";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const attemptFields = {
  attemptId: z.string().min(1).max(64),
};
const savedFields = {
  toolkitId: z.string().min(1).max(64),
};
const attempt = toolkitScopedInput(attemptFields);
const saved = toolkitScopedInput(savedFields);
async function request<T>(operation: () => Promise<T>): Promise<T> {
  try {
    return await operation();
  } catch (error) {
    throw mapExpectedError(error, {
      401: "UNAUTHORIZED",
      403: "FORBIDDEN",
      404: "NOT_FOUND",
      409: "CONFLICT",
      422: "BAD_REQUEST",
    });
  }
}

export const googleRouter = router({
  preparation: publicProcedure
    .input(toolkitScopedInput({}))
    .query(async ({ ctx, input }) => {
      if ("owner" in input) {
        const { data } = await request(() =>
          personalGoogleToolkitV1PersonalGooglePreparation({
            client: ctx.apiClient,
            path: { handle: input.handle },
            throwOnError: true,
          }),
        );
        return data;
      }
      const { data } = await request(() =>
        input.agentId == null
          ? googleToolkitV1SharedGooglePreparation({
              client: ctx.apiClient,
              path: { handle: input.handle },
              throwOnError: true,
            })
          : googleToolkitV1AgentGooglePreparation({
              client: ctx.apiClient,
              path: { handle: input.handle, agent_id: input.agentId },
              throwOnError: true,
            }),
      );
      return data;
    }),
  connect: publicProcedure
    .input(toolkitScopedInput({ desired: googleDesiredSchema }))
    .mutation(async ({ ctx, input }) => {
      if ("owner" in input) {
        const { data } = await request(() =>
          personalGoogleToolkitV1PersonalGoogleConnect({
            client: ctx.apiClient,
            path: { handle: input.handle },
            body: input.desired,
            throwOnError: true,
          }),
        );
        return data;
      }
      const { data } = await request(() =>
        input.agentId == null
          ? googleToolkitV1SharedGoogleConnect({
              client: ctx.apiClient,
              path: { handle: input.handle },
              body: input.desired,
              throwOnError: true,
            })
          : googleToolkitV1AgentGoogleConnect({
              client: ctx.apiClient,
              path: { handle: input.handle, agent_id: input.agentId },
              body: input.desired,
              throwOnError: true,
            }),
      );
      return data;
    }),
  reconnect: publicProcedure
    .input(toolkitScopedInput({ ...savedFields, desired: googleDesiredSchema }))
    .mutation(async ({ ctx, input }) => {
      if ("owner" in input) {
        const { data } = await request(() =>
          personalGoogleToolkitV1PersonalGoogleReconnect({
            client: ctx.apiClient,
            path: { handle: input.handle, toolkit_id: input.toolkitId },
            body: input.desired,
            throwOnError: true,
          }),
        );
        return data;
      }
      const path = { handle: input.handle, toolkit_id: input.toolkitId };
      const { data } = await request(() =>
        input.agentId == null
          ? googleToolkitV1SharedGoogleReconnect({
              client: ctx.apiClient,
              path,
              body: input.desired,
              throwOnError: true,
            })
          : googleToolkitV1AgentGoogleReconnect({
              client: ctx.apiClient,
              path: { ...path, agent_id: input.agentId },
              body: input.desired,
              throwOnError: true,
            }),
      );
      return data;
    }),
  exchange: publicProcedure
    .input(
      toolkitScopedInput({
        code: z.string().min(1).max(8192),
        state: z.string().min(1).max(16384),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const body = { code: input.code, state: input.state };
      if ("owner" in input) {
        const { data } = await request(() =>
          personalGoogleToolkitV1PersonalGoogleExchange({
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
          ? googleToolkitV1SharedGoogleExchange({
              client: ctx.apiClient,
              path: { handle: input.handle },
              body,
              throwOnError: true,
            })
          : googleToolkitV1AgentGoogleExchange({
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
        personalGoogleToolkitV1PersonalGoogleReview({
          client: ctx.apiClient,
          path: { handle: input.handle, attempt_id: input.attemptId },
          throwOnError: true,
        }),
      );
      return data;
    }
    const path = { handle: input.handle, attempt_id: input.attemptId };
    const { data } = await request(() =>
      input.agentId == null
        ? googleToolkitV1SharedGoogleReview({
            client: ctx.apiClient,
            path,
            throwOnError: true,
          })
        : googleToolkitV1AgentGoogleReview({
            client: ctx.apiClient,
            path: { ...path, agent_id: input.agentId },
            throwOnError: true,
          }),
    );
    return data;
  }),
  confirm: publicProcedure
    .input(
      toolkitScopedInput({
        ...attemptFields,
        settings: googleFinalSettingsSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      if ("owner" in input) {
        const { data } = await request(() =>
          personalGoogleToolkitV1PersonalGoogleConfirm({
            client: ctx.apiClient,
            path: { handle: input.handle, attempt_id: input.attemptId },
            body: { settings: input.settings },
            throwOnError: true,
          }),
        );
        return data;
      }
      const path = { handle: input.handle, attempt_id: input.attemptId };
      const body = { settings: input.settings };
      const { data } = await request(() =>
        input.agentId == null
          ? googleToolkitV1SharedGoogleConfirm({
              client: ctx.apiClient,
              path,
              body,
              throwOnError: true,
            })
          : googleToolkitV1AgentGoogleConfirm({
              client: ctx.apiClient,
              path: { ...path, agent_id: input.agentId },
              body,
              throwOnError: true,
            }),
      );
      return data;
    }),
  reconnectConfirm: publicProcedure
    .input(
      toolkitScopedInput({
        ...attemptFields,
        settings: googleReconnectSettingsSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      if ("owner" in input) {
        const { data } = await request(() =>
          personalGoogleToolkitV1PersonalGoogleReconnectConfirm({
            client: ctx.apiClient,
            path: { handle: input.handle, attempt_id: input.attemptId },
            body: { settings: input.settings },
            throwOnError: true,
          }),
        );
        return data;
      }
      const path = { handle: input.handle, attempt_id: input.attemptId };
      const body = { settings: input.settings };
      const { data } = await request(() =>
        input.agentId == null
          ? googleToolkitV1SharedGoogleReconnectConfirm({
              client: ctx.apiClient,
              path,
              body,
              throwOnError: true,
            })
          : googleToolkitV1AgentGoogleReconnectConfirm({
              client: ctx.apiClient,
              path: { ...path, agent_id: input.agentId },
              body,
              throwOnError: true,
            }),
      );
      return data;
    }),
  cancel: publicProcedure.input(attempt).mutation(async ({ ctx, input }) => {
    if ("owner" in input) {
      const { data } = await request(() =>
        personalGoogleToolkitV1PersonalGoogleCancel({
          client: ctx.apiClient,
          path: { handle: input.handle, attempt_id: input.attemptId },
          throwOnError: true,
        }),
      );
      return data;
    }
    const path = { handle: input.handle, attempt_id: input.attemptId };
    const { data } = await request(() =>
      input.agentId == null
        ? googleToolkitV1SharedGoogleCancel({
            client: ctx.apiClient,
            path,
            throwOnError: true,
          })
        : googleToolkitV1AgentGoogleCancel({
            client: ctx.apiClient,
            path: { ...path, agent_id: input.agentId },
            throwOnError: true,
          }),
    );
    return data;
  }),
  outcome: publicProcedure.input(attempt).query(async ({ ctx, input }) => {
    if ("owner" in input) {
      const { data } = await request(() =>
        personalGoogleToolkitV1PersonalGoogleOutcome({
          client: ctx.apiClient,
          path: { handle: input.handle, attempt_id: input.attemptId },
          throwOnError: true,
        }),
      );
      return data;
    }
    const path = { handle: input.handle, attempt_id: input.attemptId };
    const { data } = await request(() =>
      input.agentId == null
        ? googleToolkitV1SharedGoogleOutcome({
            client: ctx.apiClient,
            path,
            throwOnError: true,
          })
        : googleToolkitV1AgentGoogleOutcome({
            client: ctx.apiClient,
            path: { ...path, agent_id: input.agentId },
            throwOnError: true,
          }),
    );
    return data;
  }),
  status: publicProcedure.input(saved).query(async ({ ctx, input }) => {
    if ("owner" in input) {
      const { data } = await request(() =>
        personalGoogleToolkitV1PersonalGoogleStatus({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          throwOnError: true,
        }),
      );
      return data;
    }
    const path = { handle: input.handle, toolkit_id: input.toolkitId };
    const { data } = await request(() =>
      input.agentId == null
        ? googleToolkitV1SharedGoogleStatus({
            client: ctx.apiClient,
            path,
            throwOnError: true,
          })
        : googleToolkitV1AgentGoogleStatus({
            client: ctx.apiClient,
            path: { ...path, agent_id: input.agentId },
            throwOnError: true,
          }),
    );
    return data;
  }),
  disconnect: publicProcedure.input(saved).mutation(async ({ ctx, input }) => {
    if ("owner" in input) {
      await request(() =>
        personalGoogleToolkitV1PersonalGoogleDisconnect({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          throwOnError: true,
        }),
      );
      return null;
    }
    const path = { handle: input.handle, toolkit_id: input.toolkitId };
    await request(() =>
      input.agentId == null
        ? googleToolkitV1SharedGoogleDisconnect({
            client: ctx.apiClient,
            path,
            throwOnError: true,
          })
        : googleToolkitV1AgentGoogleDisconnect({
            client: ctx.apiClient,
            path: { ...path, agent_id: input.agentId },
            throwOnError: true,
          }),
    );
    return null;
  }),
});
