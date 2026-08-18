import { z } from "zod/v4";
import { protectedProcedure, router } from "../init";
import type { Client } from "@azents/admin-client";

const systemCatalogProviderSchema = z.enum([
  "openai",
  "xai",
  "xai_oauth",
  "anthropic",
  "google_gemini",
]);

type SystemCatalogProvider = z.infer<typeof systemCatalogProviderSchema>;

const systemModelCatalogSyncAttemptResponseSchema = z.object({
  id: z.string(),
  status: z.string(),
  started_at: z.string(),
  finished_at: z.string().nullable(),
  failure_code: z.string().nullable(),
  failure_message: z.string().nullable(),
  action_hint: z.string().nullable(),
  fetched_count: z.number(),
  matched_count: z.number(),
  skipped_count: z.number(),
  hidden_count: z.number(),
});

const systemModelCatalogResponseSchema = z.object({
  provider: systemCatalogProviderSchema,
  catalog_id: z.string().nullable(),
  snapshot_id: z.string().nullable(),
  visible_count: z.number(),
  hidden_count: z.number(),
  latest_attempt: systemModelCatalogSyncAttemptResponseSchema.nullable(),
});

const systemModelCatalogRefreshResponseSchema = z.object({
  provider: systemCatalogProviderSchema,
  catalog_id: z.string(),
  snapshot_id: z.string().nullable(),
  visible_count: z.number(),
  hidden_count: z.number(),
  status: z.string(),
  failure_code: z.string().nullable(),
  failure_message: z.string().nullable(),
  action_hint: z.string().nullable(),
});

const systemModelCatalogListResponseSchema = z.object({
  items: z.array(systemModelCatalogResponseSchema),
});

const systemModelCatalogRefreshListResponseSchema = z.object({
  items: z.array(systemModelCatalogRefreshResponseSchema),
});

type SystemModelCatalogListResponse = z.infer<
  typeof systemModelCatalogListResponseSchema
>;
type SystemModelCatalogRefreshResponse = z.infer<
  typeof systemModelCatalogRefreshResponseSchema
>;
type SystemModelCatalogRefreshListResponse = z.infer<
  typeof systemModelCatalogRefreshListResponseSchema
>;

function parseResponse<T>(schema: z.ZodType<T>, value: unknown): T {
  return schema.parse(value);
}

async function listSystemModelCatalogs(
  client: Client,
): Promise<SystemModelCatalogListResponse> {
  const response = await client.get({
    url: "/model-catalog/v1/system-catalogs",
    throwOnError: true,
  });
  return parseResponse(systemModelCatalogListResponseSchema, response.data);
}

async function refreshSystemModelCatalog(
  client: Client,
  provider: SystemCatalogProvider,
): Promise<SystemModelCatalogRefreshResponse> {
  const response = await client.post({
    path: { provider },
    url: "/model-catalog/v1/system-catalogs/{provider}/refresh",
    throwOnError: true,
  });
  return parseResponse(systemModelCatalogRefreshResponseSchema, response.data);
}

async function refreshSystemModelCatalogs(
  client: Client,
): Promise<SystemModelCatalogRefreshListResponse> {
  const response = await client.post({
    url: "/model-catalog/v1/system-catalogs/refresh",
    throwOnError: true,
  });
  return parseResponse(
    systemModelCatalogRefreshListResponseSchema,
    response.data,
  );
}

export const modelCatalogRouter = router({
  listSystemCatalogs: protectedProcedure.query(async ({ ctx }) => {
    return await listSystemModelCatalogs(ctx.adminApiClient);
  }),

  refreshSystemCatalog: protectedProcedure
    .input(z.object({ provider: systemCatalogProviderSchema }))
    .mutation(async ({ ctx, input }) => {
      return await refreshSystemModelCatalog(
        ctx.adminApiClient,
        input.provider,
      );
    }),

  refreshSystemCatalogs: protectedProcedure.mutation(async ({ ctx }) => {
    return await refreshSystemModelCatalogs(ctx.adminApiClient);
  }),
});
