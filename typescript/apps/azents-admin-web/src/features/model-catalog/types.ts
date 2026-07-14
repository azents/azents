import type { SystemCatalogProvider } from "@azents/admin-client";

export type { SystemCatalogProvider };

export interface SystemModelCatalogSyncAttemptResponse {
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

export interface SystemModelCatalogResponse {
  provider: SystemCatalogProvider;
  catalog_id: string | null;
  snapshot_id: string | null;
  visible_count: number;
  hidden_count: number;
  latest_attempt: SystemModelCatalogSyncAttemptResponse | null;
}

export interface SystemModelCatalogRefreshResponse {
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

export type SystemCatalogListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; catalogs: SystemModelCatalogResponse[] };

export interface SystemCatalogStatus {
  provider: SystemCatalogProvider;
  catalog: SystemModelCatalogResponse | null;
  refreshing: boolean;
}
