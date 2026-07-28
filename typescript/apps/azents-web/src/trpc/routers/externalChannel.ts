import {
  externalChannelV1AddMultiDiscordRoute,
  externalChannelV1AddMultiSlackRoute,
  externalChannelV1ClearMultiDiscordChannelDefault,
  externalChannelV1ClearMultiSlackChannelDefault,
  externalChannelV1DecideApprovalRequest,
  externalChannelV1DisconnectConnection,
  externalChannelV1DisconnectMultiDiscordConnection,
  externalChannelV1DisconnectMultiSlackConnection,
  externalChannelV1DisconnectSessionChannel,
  externalChannelV1GetApprovalRequest,
  externalChannelV1GetManifestGuidance,
  externalChannelV1GetMultiDiscordConnection,
  externalChannelV1GetMultiDiscordConnectionImpact,
  externalChannelV1GetMultiDiscordRouteImpact,
  externalChannelV1GetMultiSlackConnection,
  externalChannelV1GetMultiSlackConnectionImpact,
  externalChannelV1GetMultiSlackRouteImpact,
  externalChannelV1ListAgentAccess,
  externalChannelV1ListConnections,
  externalChannelV1ListMultiDiscordChannelDefaults,
  externalChannelV1ListMultiDiscordConnections,
  externalChannelV1ListMultiDiscordRoutes,
  externalChannelV1ListMultiSlackChannelDefaults,
  externalChannelV1ListMultiSlackConnections,
  externalChannelV1ListMultiSlackRoutes,
  externalChannelV1ListSessionChannels,
  externalChannelV1LoadMultiSlackManagementHandoff,
  externalChannelV1ReenableMultiDiscordRoute,
  externalChannelV1ReenableMultiSlackRoute,
  externalChannelV1RemoveAccessBlock,
  externalChannelV1RemoveMultiDiscordRoute,
  externalChannelV1RemoveMultiSlackRoute,
  externalChannelV1ReplaceMultiDiscordChannelDefault,
  externalChannelV1ReplaceMultiSlackChannelDefault,
  externalChannelV1RevokeAccessGrant,
  externalChannelV1SetupDiscordConnection,
  externalChannelV1SetupMultiDiscordConnection,
  externalChannelV1SetupMultiSlackConnection,
  externalChannelV1SetupSlackConnection,
  externalChannelV1UpdateConnectionAccessPolicy,
  externalChannelV1UpdateDiscordConnection,
  externalChannelV1UpdateMultiDiscordConnection,
  externalChannelV1UpdateMultiSlackConnection,
  externalChannelV1UpdateSlackConnection,
  externalChannelV1ValidateConnection,
  externalChannelV1ValidateMultiDiscordConnection,
  externalChannelV1ValidateMultiSlackConnection,
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
const providerSchema = z.enum(["slack", "discord"]);
const slackCredentialsSchema = z.object({
  botToken: z.string().min(1),
  signingSecret: z.string().min(1),
  appToken: z.string().nullable(),
});
const discordCredentialsSchema = z.object({
  botToken: z.string().min(1),
  targetGuildId: z.string().min(1),
});

function mapManagementError(error: unknown): unknown {
  return mapExpectedError(error, {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    503: "SERVICE_UNAVAILABLE",
  });
}

export const externalChannelRouter = router({
  getManifestGuidance: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        appName: z.string().min(1),
        transport: transportSchema,
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1GetManifestGuidance({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          query: {
            transport: input.transport,
            app_name: input.appName,
          },
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

  listMultiConnections: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: providerSchema,
        offset: z.number().int().min(0).default(0),
        limit: z.number().int().min(1).max(100).default(50),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await (
          input.provider === "discord"
            ? externalChannelV1ListMultiDiscordConnections
            : externalChannelV1ListMultiSlackConnections
        )({
          client: ctx.apiClient,
          path: { handle: input.handle },
          query: { offset: input.offset, limit: input.limit },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  getMultiConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: providerSchema,
        connectionId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await (
          input.provider === "discord"
            ? externalChannelV1GetMultiDiscordConnection
            : externalChannelV1GetMultiSlackConnection
        )({
          client: ctx.apiClient,
          path: { handle: input.handle, connection_id: input.connectionId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  setupMultiConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        appId: z.string().min(1),
        transport: transportSchema,
        credentials: slackCredentialsSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1SetupMultiSlackConnection({
          client: ctx.apiClient,
          path: { handle: input.handle },
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

  setupMultiDiscordConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        appId: z.string().min(1),
        credentials: discordCredentialsSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1SetupMultiDiscordConnection({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: {
            app_id: input.appId,
            configuration: { target_guild_id: input.credentials.targetGuildId },
            credentials: { bot_token: input.credentials.botToken },
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  updateMultiConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        connectionId: z.string().min(1),
        appId: z.string().min(1),
        transport: transportSchema,
        credentials: slackCredentialsSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1UpdateMultiSlackConnection({
          client: ctx.apiClient,
          path: { handle: input.handle, connection_id: input.connectionId },
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

  updateMultiDiscordConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        connectionId: z.string().min(1),
        appId: z.string().min(1),
        credentials: discordCredentialsSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1UpdateMultiDiscordConnection({
          client: ctx.apiClient,
          path: { handle: input.handle, connection_id: input.connectionId },
          body: {
            app_id: input.appId,
            configuration: { target_guild_id: input.credentials.targetGuildId },
            credentials: { bot_token: input.credentials.botToken },
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  validateMultiConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: providerSchema,
        connectionId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await (
          input.provider === "discord"
            ? externalChannelV1ValidateMultiDiscordConnection
            : externalChannelV1ValidateMultiSlackConnection
        )({
          client: ctx.apiClient,
          path: { handle: input.handle, connection_id: input.connectionId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  getMultiConnectionImpact: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: providerSchema,
        connectionId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await (
          input.provider === "discord"
            ? externalChannelV1GetMultiDiscordConnectionImpact
            : externalChannelV1GetMultiSlackConnectionImpact
        )({
          client: ctx.apiClient,
          path: { handle: input.handle, connection_id: input.connectionId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  disconnectMultiConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: providerSchema,
        connectionId: z.string().min(1),
        expectedGeneration: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await (
          input.provider === "discord"
            ? externalChannelV1DisconnectMultiDiscordConnection
            : externalChannelV1DisconnectMultiSlackConnection
        )({
          client: ctx.apiClient,
          path: { handle: input.handle, connection_id: input.connectionId },
          body: { expected_generation: input.expectedGeneration },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  listMultiRoutes: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: providerSchema,
        connectionId: z.string().min(1),
        offset: z.number().int().min(0).default(0),
        limit: z.number().int().min(1).max(100).default(50),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await (
          input.provider === "discord"
            ? externalChannelV1ListMultiDiscordRoutes
            : externalChannelV1ListMultiSlackRoutes
        )({
          client: ctx.apiClient,
          path: { handle: input.handle, connection_id: input.connectionId },
          query: { offset: input.offset, limit: input.limit },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  addMultiRoute: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: providerSchema,
        connectionId: z.string().min(1),
        agentId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await (
          input.provider === "discord"
            ? externalChannelV1AddMultiDiscordRoute
            : externalChannelV1AddMultiSlackRoute
        )({
          client: ctx.apiClient,
          path: { handle: input.handle, connection_id: input.connectionId },
          body: { agent_id: input.agentId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  getMultiRouteImpact: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: providerSchema,
        connectionId: z.string().min(1),
        routeId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await (
          input.provider === "discord"
            ? externalChannelV1GetMultiDiscordRouteImpact
            : externalChannelV1GetMultiSlackRouteImpact
        )({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            connection_id: input.connectionId,
            route_id: input.routeId,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  removeMultiRoute: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: providerSchema,
        connectionId: z.string().min(1),
        routeId: z.string().min(1),
        expectedGeneration: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await (
          input.provider === "discord"
            ? externalChannelV1RemoveMultiDiscordRoute
            : externalChannelV1RemoveMultiSlackRoute
        )({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            connection_id: input.connectionId,
            route_id: input.routeId,
          },
          body: { expected_generation: input.expectedGeneration },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  reenableMultiRoute: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: providerSchema,
        connectionId: z.string().min(1),
        routeId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await (
          input.provider === "discord"
            ? externalChannelV1ReenableMultiDiscordRoute
            : externalChannelV1ReenableMultiSlackRoute
        )({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            connection_id: input.connectionId,
            route_id: input.routeId,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  listMultiChannelDefaults: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: providerSchema,
        connectionId: z.string().min(1),
        offset: z.number().int().min(0).default(0),
        limit: z.number().int().min(1).max(100).default(50),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await (
          input.provider === "discord"
            ? externalChannelV1ListMultiDiscordChannelDefaults
            : externalChannelV1ListMultiSlackChannelDefaults
        )({
          client: ctx.apiClient,
          path: { handle: input.handle, connection_id: input.connectionId },
          query: { offset: input.offset, limit: input.limit },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  replaceMultiChannelDefault: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: providerSchema,
        connectionId: z.string().min(1),
        providerChannelId: z.string().min(1),
        routeId: z.string().min(1),
        expectedGeneration: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await (
          input.provider === "discord"
            ? externalChannelV1ReplaceMultiDiscordChannelDefault
            : externalChannelV1ReplaceMultiSlackChannelDefault
        )({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            connection_id: input.connectionId,
            provider_channel_id: input.providerChannelId,
          },
          body: {
            route_id: input.routeId,
            expected_generation: input.expectedGeneration,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  clearMultiChannelDefault: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: providerSchema,
        connectionId: z.string().min(1),
        providerChannelId: z.string().min(1),
        expectedGeneration: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await (
          input.provider === "discord"
            ? externalChannelV1ClearMultiDiscordChannelDefault
            : externalChannelV1ClearMultiSlackChannelDefault
        )({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            connection_id: input.connectionId,
            provider_channel_id: input.providerChannelId,
          },
          body: { expected_generation: input.expectedGeneration },
          throwOnError: true,
        });
        return null;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  loadMultiManagementHandoff: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        interactionId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1LoadMultiSlackManagementHandoff(
          {
            client: ctx.apiClient,
            path: { handle: input.handle, interaction_id: input.interactionId },
            throwOnError: true,
          },
        );
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

  setupDiscordConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        appId: z.string().min(1),
        credentials: discordCredentialsSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1SetupDiscordConnection({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: {
            app_id: input.appId,
            configuration: { target_guild_id: input.credentials.targetGuildId },
            credentials: { bot_token: input.credentials.botToken },
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

  updateSlackConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        connectionId: z.string().min(1),
        appId: z.string().min(1),
        transport: transportSchema,
        credentials: slackCredentialsSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1UpdateSlackConnection({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            connection_id: input.connectionId,
          },
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

  updateDiscordConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        connectionId: z.string().min(1),
        appId: z.string().min(1),
        credentials: discordCredentialsSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1UpdateDiscordConnection({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            connection_id: input.connectionId,
          },
          body: {
            app_id: input.appId,
            configuration: { target_guild_id: input.credentials.targetGuildId },
            credentials: { bot_token: input.credentials.botToken },
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapManagementError(error);
      }
    }),

  updateConnectionAccessPolicy: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        connectionId: z.string().min(1),
        openAccessEnabled: z.boolean(),
        allowBotMessages: z.boolean(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1UpdateConnectionAccessPolicy({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            connection_id: input.connectionId,
          },
          body: {
            open_access_enabled: input.openAccessEnabled,
            allow_bot_messages: input.allowBotMessages,
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
