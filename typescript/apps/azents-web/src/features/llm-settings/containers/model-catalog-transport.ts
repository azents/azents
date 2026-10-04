import { useCallback } from "react";
import { trpc } from "@/trpc/client";
import type {
  ImageCatalogTransport,
  ModelCatalogQuery,
  ModelCatalogQueryInput,
  ModelCatalogQueryOptions,
} from "@/shared/model-options/catalog-query";

export function useModelCatalogQuery(
  input: ModelCatalogQueryInput,
  options: ModelCatalogQueryOptions,
): ModelCatalogQuery {
  return trpc.llmProviderIntegration.listModels.useQuery(input, options);
}

export function useImageCatalogTransport(
  handle: string,
  integrationIds: string[],
): ImageCatalogTransport {
  const utils = trpc.useUtils();
  const query = trpc.llmProviderIntegration.imageCatalogs.useQuery(
    { handle, integrationIds },
    { enabled: integrationIds.length > 0 },
  );
  const mutation = trpc.llmProviderIntegration.syncImageCatalog.useMutation();
  const sync = useCallback(
    async (integrationId: string): Promise<void> => {
      await mutation.mutateAsync({ handle, integrationId });
      await utils.llmProviderIntegration.imageCatalogs.invalidate({
        handle,
        integrationIds,
      });
    },
    [
      handle,
      integrationIds,
      mutation,
      utils.llmProviderIntegration.imageCatalogs,
    ],
  );
  return { query, sync };
}
