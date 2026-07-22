import {
  externalChannelV1DecideApprovalRequest,
  externalChannelV1DisconnectConnection,
  externalChannelV1DisconnectSessionChannel,
  externalChannelV1GetApprovalRequest,
  externalChannelV1GetManifestGuidance,
  externalChannelV1ListAgentAccess,
  externalChannelV1ListConnections,
  externalChannelV1ListSessionChannels,
  externalChannelV1ReconnectConnection,
  externalChannelV1RemoveAccessBlock,
  externalChannelV1RevokeAccessGrant,
  externalChannelV1SetupSlackConnection,
  externalChannelV1SwitchTransport,
  externalChannelV1ValidateConnection,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const approvalDecisionSchema = z.enum([
  "allow_session",
  "allow_agent",
  "deny",
  "block",
]);
const transportSchema = z.enum(["http", "socket"]);
const slackCredentialsSchema = z.object({
  botToken: z.string().min(1),
  signingSecret: z.string().min(1),
  appToken: z.string().nullable(),
});

function mapManagementError(error: unknown): unknown {
  return mapExpectedError(error, {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
  });
}

export const externalChannelRouter = router({
  getManifestGuidance: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        transport: transportSchema,
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1GetManifestGuidance({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          query: { transport: input.transport },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  listConnections: publicProcedure
    .input(z.object({ handle: z.string().min(1), agentId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1ListConnections({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  setupSlackConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        appId: z.string().min(1),
        transport: transportSchema,
        credentials: slackCredentialsSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1SetupSlackConnection({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: {
            app_id: input.appId,
            transport: input.transport,
            credentials: {
              bot_token: input.credentials.botToken,
              signing_secret: input.credentials.signingSecret,
              app_token: input.credentials.appToken,
            },
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  validateConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        connectionId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1ValidateConnection({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            connection_id: input.connectionId,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  switchTransport: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        connectionId: z.string().min(1),
        transport: transportSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1SwitchTransport({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            connection_id: input.connectionId,
          },
          body: { transport: input.transport },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  reconnectConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        connectionId: z.string().min(1),
        credentials: slackCredentialsSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1ReconnectConnection({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            connection_id: input.connectionId,
          },
          body: {
            credentials: {
              bot_token: input.credentials.botToken,
              signing_secret: input.credentials.signingSecret,
              app_token: input.credentials.appToken,
            },
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  disconnectConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        connectionId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1DisconnectConnection({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            connection_id: input.connectionId,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  listAgentAccess: publicProcedure
    .input(z.object({ handle: z.string().min(1), agentId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1ListAgentAccess({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  revokeAccessGrant: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        grantId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await externalChannelV1RevokeAccessGrant({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            grant_id: input.grantId,
          },
          throwOnError: true,
        });
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  removeAccessBlock: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        blockId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await externalChannelV1RemoveAccessBlock({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            block_id: input.blockId,
          },
          throwOnError: true,
        });
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  listSessionChannels: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1ListSessionChannels({
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
        throw mapManagementError(error);
      }
    }),

  disconnectSessionChannel: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        sessionId: z.string().min(1),
        bindingId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1DisconnectSessionChannel({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            session_id: input.sessionId,
            binding_id: input.bindingId,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  getApprovalRequest: publicProcedure
    .input(z.object({ accessRequestId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1GetApprovalRequest({
          client: ctx.apiClient,
          path: { access_request_id: input.accessRequestId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          404: "NOT_FOUND",
        });
      }
    }),

  decideApprovalRequest: publicProcedure
    .input(
      z.object({
        accessRequestId: z.string().min(1),
        decision: approvalDecisionSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1DecideApprovalRequest({
          client: ctx.apiClient,
          path: { access_request_id: input.accessRequestId },
          body: { decision: input.decision },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),
});
