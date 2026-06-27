import { z } from "zod/v4";
import { publicProcedure, router } from "../init";
import type { Client } from "@azents/admin-client";

const systemCatalogProviderSchema = z.enum([
  "openai",
  "chatgpt_oauth",
  "anthropic",
  "google_gemini",
]);

type SystemCatalogProvider = z.infer<typeof systemCatalogProviderSchema>;

interface SystemModelCatalogSyncAttemptResponse {
  id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  failure_code: string | null;
  failure_message: string | null;
  action_hint: string | null;
  fetched_count: number;
  matched_count: number;
  skipped_count: number;
  hidden_count: number;
}

interface SystemModelCatalogResponse {
  provider: SystemCatalogProvider;
  catalog_id: string | null;
  snapshot_id: string | null;
  visible_count: number;
  hidden_count: number;
  latest_attempt: SystemModelCatalogSyncAttemptResponse | null;
}

interface SystemModelCatalogRefreshResponse {
  provider: SystemCatalogProvider;
  catalog_id: string;
  snapshot_id: string | null;
  visible_count: number;
  hidden_count: number;
  status: string;
  failure_code: string | null;
  failure_message: string | null;
  action_hint: string | null;
}

interface SystemModelCatalogListResponse {
  items: SystemModelCatalogResponse[];
}

interface SystemModelCatalogRefreshListResponse {
  items: SystemModelCatalogRefreshResponse[];
}

function getJson<T>(value: unknown): T {
  return value as T;
}

async function listSystemModelCatalogs(
  client: Client,
): Promise<SystemModelCatalogListResponse> {
  const response = await client.get({
    url: "/model-catalog/v1/system-catalogs",
    throwOnError: true,
  });
  return getJson<SystemModelCatalogListResponse>(response.data);
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
  return getJson<SystemModelCatalogRefreshResponse>(response.data);
}

async function refreshSystemModelCatalogs(
  client: Client,
): Promise<SystemModelCatalogRefreshListResponse> {
  const response = await client.post({
    url: "/model-catalog/v1/system-catalogs/refresh",
    throwOnError: true,
  });
  return getJson<SystemModelCatalogRefreshListResponse>(response.data);
}

export const modelCatalogRouter = router({
  listSystemCatalogs: publicProcedure.query(async ({ ctx }) => {
    return await listSystemModelCatalogs(ctx.adminApiClient);
  }),

  refreshSystemCatalog: publicProcedure
    .input(z.object({ provider: systemCatalogProviderSchema }))
    .mutation(async ({ ctx, input }) => {
      return await refreshSystemModelCatalog(
        ctx.adminApiClient,
        input.provider,
      );
    }),

  refreshSystemCatalogs: publicProcedure.mutation(async ({ ctx }) => {
    return await refreshSystemModelCatalogs(ctx.adminApiClient);
  }),
});
