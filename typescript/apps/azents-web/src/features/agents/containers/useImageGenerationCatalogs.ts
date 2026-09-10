"use client";

import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import type {
  ImageGenerationCatalogState,
  SelectableModelOptionFormValue,
} from "../model-selection";

export interface ImageGenerationCatalogsOutput {
  states: ReadonlyMap<string, ImageGenerationCatalogState>;
  onSync: (integrationId: string) => Promise<void>;
}

function imageCatalogIntegrationIds(
  options: SelectableModelOptionFormValue[],
): string[] {
  return [
    ...new Set(
      options.flatMap((option) => {
        const supported =
          option.normalized_capabilities?.built_in_tools?.supported ?? [];
        if (
          option.model_provider_integration_id == null ||
          !supported.includes("image_generation")
        ) {
          return [];
        }
        return [option.model_provider_integration_id];
      }),
    ),
  ].sort();
}

export function useImageGenerationCatalogs(
  handle: string,
  options: SelectableModelOptionFormValue[],
): ImageGenerationCatalogsOutput {
  const integrationIds = useMemo(
    () => imageCatalogIntegrationIds(options),
    [options],
  );
  const utils = trpc.useUtils();
  const query = trpc.llmProviderIntegration.imageCatalogs.useQuery(
    { handle, integrationIds },
    { enabled: integrationIds.length > 0 },
  );
  const syncMutation =
    trpc.llmProviderIntegration.syncImageCatalog.useMutation();

  const states = useMemo(() => {
    const next = new Map<string, ImageGenerationCatalogState>();
    if (integrationIds.length === 0) {
      return next;
    }
    if (query.isLoading) {
      for (const integrationId of integrationIds) {
        next.set(integrationId, { type: "LOADING" });
      }
      return next;
    }
    if (query.isError || query.data == null) {
      for (const integrationId of integrationIds) {
        next.set(integrationId, {
          type: "ERROR",
          message: query.error?.message ?? "Image model catalog unavailable.",
        });
      }
      return next;
    }
    for (const item of query.data.items) {
      next.set(
        item.integrationId,
        item.catalog.explicit_selection_supported
          ? { type: "LOADED", data: item.catalog }
          : { type: "UNSUPPORTED", data: item.catalog },
      );
    }
    return next;
  }, [
    integrationIds,
    query.data,
    query.error?.message,
    query.isError,
    query.isLoading,
  ]);

  const onSync = useCallback(
    async (integrationId: string): Promise<void> => {
      await syncMutation.mutateAsync({ handle, integrationId });
      await utils.llmProviderIntegration.imageCatalogs.invalidate({
        handle,
        integrationIds,
      });
    },
    [
      handle,
      integrationIds,
      syncMutation,
      utils.llmProviderIntegration.imageCatalogs,
    ],
  );

  return { states, onSync };
}
