/**
 * LLM Provider Integration tRPC router
 *
 * Per-workspace LLM provider integration CRUD:
 * - list: integration list fetch (auth required, member or higher)
 * - create: integration create (auth required, owner only)
 * - update: integration update (auth required, owner only)
 * - remove: integration delete (auth required, owner only)
 */
import {
  chatgptOauthV1CancelDevice,
  chatgptOauthV1PollDevice,
  chatgptOauthV1StartDevice,
  kimiOauthV1CancelDevice,
  kimiOauthV1PollDevice,
  kimiOauthV1StartDevice,
  llmProviderIntegrationV1CreateIntegration,
  llmProviderIntegrationV1DeleteIntegration,
  llmProviderIntegrationV1GetSubscriptionUsage,
  llmProviderIntegrationV1ListIntegrationCatalogEntries,
  llmProviderIntegrationV1ListIntegrationProviders,
  llmProviderIntegrationV1ListIntegrations,
  llmProviderIntegrationV1SyncIntegrationCatalog,
  llmProviderIntegrationV1UpdateIntegration,
  xaiOauthV1CancelDevice,
  xaiOauthV1PollDevice,
  xaiOauthV1StartDevice,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

// Secret schema (encrypted storage)
const apiKeySecretsSchema = z.object({
  type: z.literal("api_key"),
  api_key: z.string().min(1),
});

const awsSecretsSchema = z.object({
  type: z.literal("aws_credentials"),
  secret_access_key: z.string().min(1),
});

const gcpSecretsSchema = z.object({
  type: z.literal("gcp_service_account"),
  service_account_json: z.string().min(1),
});

const providerSecretsSchema = z.discriminatedUnion("type", [
  apiKeySecretsSchema,
  awsSecretsSchema,
  gcpSecretsSchema,
]);

// Config schema (plain JSONB storage)
const awsConfigSchema = z.object({
  type: z.literal("aws_credentials"),
  access_key_id: z.string().min(1),
  region: z.string().min(1),
  role_arn: z.string().min(1).optional(),
});

const gcpConfigSchema = z.object({
  type: z.literal("gcp_service_account"),
  project_id: z.string().min(1),
  region: z.string().min(1),
});

const providerConfigSchema = z
  .discriminatedUnion("type", [awsConfigSchema, gcpConfigSchema])
  .nullable();

export const llmProviderIntegrationRouter = router({
  /**
   * workspace of LLM Provider Integration list fetch
   */
  list: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await llmProviderIntegrationV1ListIntegrations({
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

  /** Fetch one integration's live subscription usage. */
  subscriptionUsage: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        integrationId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await llmProviderIntegrationV1GetSubscriptionUsage({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            integration_id: input.integrationId,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  /** Fetch provider options available for new integrations. */
  listProviders: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await llmProviderIntegrationV1ListIntegrationProviders(
          {
            client: ctx.apiClient,
            path: { handle: input.handle },
            throwOnError: true,
          },
        );
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),

  /** Fetch model candidates selectable from Integration */
  listModels: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        integrationId: z.string().min(1),
        search: z.string().optional(),
        limit: z.number().int().min(1).max(100).optional(),
        offset: z.number().int().min(0).optional(),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } =
          await llmProviderIntegrationV1ListIntegrationCatalogEntries({
            client: ctx.apiClient,
            path: {
              handle: input.handle,
              integration_id: input.integrationId,
            },
            query: {
              limit: input.limit ?? 100,
              offset: input.offset ?? 0,
              ...(input.search ? { search: input.search } : {}),
            },
            throwOnError: true,
          });
        return {
          models: data.entries.map((entry) => ({
            provider: entry.provider,
            model_identifier: entry.provider_model_identifier,
            model_display_name: entry.display_name,
            normalized_capabilities: entry.normalized_capabilities,
          })),
          summary: {
            source: "stored_catalog_projection",
            fetched_at:
              data.current_snapshot_created_at ?? new Date().toISOString(),
            returned_count: data.entries.length,
            skipped_count: Math.max(data.total - data.entries.length, 0),
          },
          skips: [],
          catalog: {
            catalog_id: data.catalog_id,
            catalog_scope: data.catalog_scope,
            current_snapshot_id: data.current_snapshot_id,
            current_snapshot_created_at: data.current_snapshot_created_at,
            latest_attempt: data.latest_attempt,
            stale: data.stale,
            sync_available_at: data.sync_available_at,
            automatic_retry_blocked: data.automatic_retry_blocked,
            total: data.total,
            limit: data.limit,
            offset: data.offset,
          },
        };
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

  /** Synchronize an integration-scoped model catalog. */
  syncCatalog: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        integrationId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await llmProviderIntegrationV1SyncIntegrationCatalog({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            integration_id: input.integrationId,
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
          409: "CONFLICT",
          422: "BAD_REQUEST",
          429: "TOO_MANY_REQUESTS",
        });
      }
    }),

  /**
   * LLM Provider Integration create
   */
  create: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        provider: z.string().min(1),
        name: z.string().optional(),
        secrets: providerSecretsSchema,
        config: providerConfigSchema.optional(),
        enabled: z.boolean().optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await llmProviderIntegrationV1CreateIntegration({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: {
            provider: input.provider as "openai",
            name: input.name ?? null,
            secrets: input.secrets,
            config: input.config ?? null,
            enabled: input.enabled ?? true,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          422: "BAD_REQUEST",
        });
      }
    }),

  /**
   * LLM Provider Integration update
   */
  update: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        integrationId: z.string().min(1),
        name: z.string().min(1).optional(),
        secrets: providerSecretsSchema.optional(),
        config: providerConfigSchema.optional(),
        enabled: z.boolean().optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await llmProviderIntegrationV1UpdateIntegration({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            integration_id: input.integrationId,
          },
          body: {
            name: input.name,
            secrets: input.secrets,
            config: input.config,
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
        });
      }
    }),

  /**
   * LLM Provider Integration delete
   */
  remove: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        integrationId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await llmProviderIntegrationV1DeleteIntegration({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            integration_id: input.integrationId,
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

  startChatgptOauthDevice: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatgptOauthV1StartDevice({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          503: "SERVICE_UNAVAILABLE",
        });
      }
    }),

  getChatgptOauthDeviceStatus: publicProcedure
    .input(
      z.object({ handle: z.string().min(1), sessionId: z.string().min(1) }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await chatgptOauthV1PollDevice({
          client: ctx.apiClient,
          path: { handle: input.handle, session_id: input.sessionId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          503: "SERVICE_UNAVAILABLE",
        });
      }
    }),

  cancelChatgptOauthDevice: publicProcedure
    .input(
      z.object({ handle: z.string().min(1), sessionId: z.string().min(1) }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await chatgptOauthV1CancelDevice({
          client: ctx.apiClient,
          path: { handle: input.handle, session_id: input.sessionId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  startXaiOauthDevice: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await xaiOauthV1StartDevice({
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

  getXaiOauthDeviceStatus: publicProcedure
    .input(
      z.object({ handle: z.string().min(1), sessionId: z.string().min(1) }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await xaiOauthV1PollDevice({
          client: ctx.apiClient,
          path: { handle: input.handle, session_id: input.sessionId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  cancelXaiOauthDevice: publicProcedure
    .input(
      z.object({ handle: z.string().min(1), sessionId: z.string().min(1) }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await xaiOauthV1CancelDevice({
          client: ctx.apiClient,
          path: { handle: input.handle, session_id: input.sessionId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  startKimiOauthDevice: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await kimiOauthV1StartDevice({
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

  getKimiOauthDeviceStatus: publicProcedure
    .input(
      z.object({ handle: z.string().min(1), sessionId: z.string().min(1) }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await kimiOauthV1PollDevice({
          client: ctx.apiClient,
          path: { handle: input.handle, session_id: input.sessionId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  cancelKimiOauthDevice: publicProcedure
    .input(
      z.object({ handle: z.string().min(1), sessionId: z.string().min(1) }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await kimiOauthV1CancelDevice({
          client: ctx.apiClient,
          path: { handle: input.handle, session_id: input.sessionId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),
});
