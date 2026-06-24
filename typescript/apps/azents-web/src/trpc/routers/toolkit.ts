/**
 * Toolkit tRPC router
 *
 * Per-workspace Toolkit CRUD + Scope management + Agent-Toolkit attach:
 * - list / get: Toolkit fetch (auth required, manager or higher)
 * - listAvailable: current user use available Toolkit fetch (member or higher)
 * - create / update / remove: Toolkit CRUD (manager or higher)
 * - listScopes / createScope / deleteScope: Scope management (manager or higher)
 * - listAgentToolkits / attachToAgent / detachFromAgent: Agent-Toolkit attach (member or higher)
 */
import {
  toolkitOauthV1ConnectOauth,
  toolkitOauthV1DisconnectOauthConnection,
  toolkitOauthV1ExchangeOauthConnection,
  toolkitOauthV1GetGithubPlatformInstallations,
  toolkitOauthV1GetGithubPlatformInstallUrl,
  toolkitOauthV1GetGithubPlatformOauthUrl,
  toolkitOauthV1TestConnectionUnsaved,
  toolkitV1AttachToolkitToAgent,
  toolkitV1CreateToolkitConfig,
  toolkitV1CreateToolkitScope,
  toolkitV1DeleteToolkitConfig,
  toolkitV1DeleteToolkitScope,
  toolkitV1DetachToolkitFromAgent,
  toolkitV1GetToolkitConfig,
  toolkitV1ListAgentToolkits,
  toolkitV1ListAvailableToolkitConfigs,
  toolkitV1ListToolkitConfigs,
  toolkitV1ListToolkits,
  toolkitV1ListToolkitScopes,
  toolkitV1UpdateToolkitConfig,
} from "@azents/public-client";
import { z } from "zod/v4";
import { TOOLKIT_SLUG_REGEX } from "@/shared/lib/toolkit-slug";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

export const toolkitRouter = router({
  /**
   * Platform-provided Toolkit list
   */
  listToolkits: publicProcedure.query(async ({ ctx }) => {
    try {
      const { data } = await toolkitV1ListToolkits({
        client: ctx.apiClient,
        throwOnError: true,
      });
      return data;
    } catch (e) {
      throw mapExpectedError(e, {});
    }
  }),

  /**
   * workspace of Toolkit Config list fetch
   */
  listConfigs: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitV1ListToolkitConfigs({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),

  /**
   * current user use available Toolkit Config list
   */
  listAvailableConfigs: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitV1ListAvailableToolkitConfigs({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),

  /**
   * Toolkit Config detail fetch
   */
  getConfig: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        toolkitId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitV1GetToolkitConfig({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            toolkit_config_id: input.toolkitId,
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
   * Toolkit Config create
   */
  createConfig: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        toolkitType: z.string().min(1).max(100),
        slug: z.string().min(1).max(100).regex(TOOLKIT_SLUG_REGEX),
        name: z.string().min(1).max(255),
        description: z.string().optional(),
        prompt: z.string().optional(),
        config: z.record(z.string(), z.unknown()),
        credentials: z.record(z.string(), z.unknown()).optional(),
        enabled: z.boolean().optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitV1CreateToolkitConfig({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: {
            toolkit_type: input.toolkitType,
            slug: input.slug,
            name: input.name,
            description: input.description ?? null,
            prompt: input.prompt ?? null,
            config: input.config,
            credentials: input.credentials,
            enabled: input.enabled ?? true,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          400: "BAD_REQUEST",
          422: "BAD_REQUEST",
        });
      }
    }),

  /**
   * Toolkit Config update
   */
  updateConfig: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        toolkitId: z.string().min(1),
        slug: z.string().min(1).max(100).regex(TOOLKIT_SLUG_REGEX).optional(),
        name: z.string().min(1).max(255).optional(),
        description: z.string().nullable().optional(),
        prompt: z.string().nullable().optional(),
        config: z.record(z.string(), z.unknown()).optional(),
        credentials: z.record(z.string(), z.unknown()).optional(),
        enabled: z.boolean().optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitV1UpdateToolkitConfig({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            toolkit_config_id: input.toolkitId,
          },
          body: {
            slug: input.slug,
            name: input.name,
            description: input.description,
            prompt: input.prompt,
            config: input.config,
            credentials: input.credentials,
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
          422: "BAD_REQUEST",
        });
      }
    }),

  /**
   * Toolkit Config delete
   */
  removeConfig: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        toolkitId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await toolkitV1DeleteToolkitConfig({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            toolkit_config_id: input.toolkitId,
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

  /**
   * Toolkit Scope list fetch
   */
  listScopes: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        toolkitId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitV1ListToolkitScopes({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_config_id: input.toolkitId },
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
   * Toolkit Scope add
   */
  createScope: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        toolkitId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitV1CreateToolkitScope({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_config_id: input.toolkitId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  /**
   * Toolkit Scope delete
   */
  deleteScope: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        toolkitId: z.string().min(1),
        scopeId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await toolkitV1DeleteToolkitScope({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            toolkit_config_id: input.toolkitId,
            scope_id: input.scopeId,
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

  /**
   * Agent to attach Toolkit list
   */
  listAgentToolkits: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitV1ListAgentToolkits({
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
   * Agent to Toolkit attach
   */
  attachToAgent: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        toolkitId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitV1AttachToolkitToAgent({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: { toolkit_id: input.toolkitId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  /**
   * Agent in Toolkit detach
   */
  detachFromAgent: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        agentToolkitId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await toolkitV1DetachToolkitFromAgent({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            agent_toolkit_id: input.agentToolkitId,
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

  /**
   * GitHub Platform App installation URL fetch
   *
   * Call GitHub API with Platform App credentials configured on server
   * Fetch App slug and return installation URL.
   */
  getGithubInstallUrl: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitOauthV1GetGithubPlatformInstallUrl({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          502: "INTERNAL_SERVER_ERROR",
        });
      }
    }),

  /**
   * GitHub OAuth URL fetch
   *
   * Let user sign in to GitHub and
   * return OAuth auth URL so own installation list can be fetched.
   */
  getGithubOauthUrl: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitOauthV1GetGithubPlatformOauthUrl({
          client: ctx.apiClient,
          path: { handle: input.handle },
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
   * GitHub Platform App installation list fetch (OAuth auth required)
   *
   * Return only installations accessible with user GitHub OAuth code.
   */
  getGithubInstallations: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        code: z.string().min(1),
        state: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitOauthV1GetGithubPlatformInstallations({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: { code: input.code, state: input.state },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          502: "INTERNAL_SERVER_ERROR",
        });
      }
    }),

  /**
   * Start manager-owned Toolkit OAuth connection.
   */
  connectOauth: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        toolkitConfigId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitOauthV1ConnectOauth({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            toolkit_config_id: input.toolkitConfigId,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          422: "BAD_REQUEST",
        });
      }
    }),

  /**
   * OAuth2 auth code → toolkit-level token exchange.
   */
  oauthExchange: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        toolkitConfigId: z.string().min(1),
        code: z.string().min(1),
        state: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await toolkitOauthV1ExchangeOauthConnection({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            toolkit_config_id: input.toolkitConfigId,
          },
          body: { code: input.code, state: input.state },
          throwOnError: true,
        });
        return null;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          422: "BAD_REQUEST",
        });
      }
    }),

  /**
   * Disconnect manager-owned Toolkit OAuth connection.
   */
  disconnectOauth: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        toolkitConfigId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await toolkitOauthV1DisconnectOauthConnection({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            toolkit_config_id: input.toolkitConfigId,
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

  /**
   * Toolkit connection test
   *
   * always unsaved endpoint use: send form values + toolkit_config_id with DB credentials merge.
   */
  testConnection: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        toolkitType: z.string().default("mcp"),
        toolkitConfigId: z.string().nullable(),
        config: z.record(z.string(), z.unknown()),
        credentials: z.record(z.string(), z.unknown()).nullable(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await toolkitOauthV1TestConnectionUnsaved({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: {
            toolkit_type: input.toolkitType,
            config: input.config,
            credentials: input.credentials,
            toolkit_config_id: input.toolkitConfigId,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),
});
