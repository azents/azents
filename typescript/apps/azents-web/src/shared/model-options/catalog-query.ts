import type {
  ModelCatalogSyncStatus,
  SelectableModelCandidate,
} from "./model-selection";
import type { ImageGenerationModelCatalogResponse } from "@azents/public-client";

export interface ModelCatalogPage {
  models: SelectableModelCandidate[];
  catalog: {
    catalog_id: string;
    catalog_scope: "system" | "integration";
    last_success_at: string | null;
    latest_sync: ModelCatalogSyncStatus | null;
    stale: boolean;
    sync_available_at: string | null;
    automatic_retry_blocked: boolean;
    total: number;
    offset: number;
  };
}

export interface ModelCatalogQueryInput {
  handle: string;
  integrationId: string;
  search?: string;
  limit: number;
  offset: number;
}

export interface ModelCatalogQueryOptions {
  enabled: boolean;
  refetchInterval: (query: {
    state: { data?: ModelCatalogPage };
  }) => number | false;
}

export interface ModelCatalogQuery {
  data?: ModelCatalogPage;
  isLoading: boolean;
  isFetching: boolean;
}

export type UseModelCatalogQuery = (
  input: ModelCatalogQueryInput,
  options: ModelCatalogQueryOptions,
) => ModelCatalogQuery;

export interface ImageCatalogTransport {
  query: {
    data?: {
      items: Array<{
        integrationId: string;
        catalog: ImageGenerationModelCatalogResponse;
      }>;
    };
    isLoading: boolean;
    isError: boolean;
    error: { message: string } | null;
  };
  sync: (integrationId: string) => Promise<void>;
}

export type UseImageCatalogTransport = (
  handle: string,
  integrationIds: string[],
) => ImageCatalogTransport;
