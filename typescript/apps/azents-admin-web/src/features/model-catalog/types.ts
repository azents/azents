import type {
  SystemCatalogProvider,
  SystemModelCatalogResponse,
} from "@azents/admin-client";

export type {
  SystemCatalogProvider,
  SystemModelCatalogRefreshResponse,
  SystemModelCatalogResponse,
  SystemModelCatalogSyncStatusResponse,
} from "@azents/admin-client";

export type SystemCatalogListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; catalogs: SystemModelCatalogResponse[] };

export interface SystemCatalogStatus {
  provider: SystemCatalogProvider;
  catalog: SystemModelCatalogResponse | null;
  refreshing: boolean;
}
