"use client";

/**
 * Toolkit list container hook.
 *
 * Handles Toolkit list fetch, delete, and enabled toggle.
 */

import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import type { ToolkitConfigListState } from "../types";
import type { ToolkitConfigResponse } from "@azents/public-client";

export interface ToolkitListContainerProps {
  handle: string;
}

export interface ToolkitListContainerOutput {
  handle: string;
  listState: ToolkitConfigListState;
  onDelete: (toolkitId: string) => void;
  onToggleEnabled: (toolkit: ToolkitConfigResponse, enabled: boolean) => void;
}

export function useToolkitListContainer(
  props: ToolkitListContainerProps,
): ToolkitListContainerOutput {
  const { handle } = props;

  const utils = trpc.useUtils();

  const listQuery = trpc.toolkit.listConfigs.useQuery({ handle });

  const listState: ToolkitConfigListState = useMemo(() => {
    if (listQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (listQuery.isError) {
      return { type: "ERROR" };
    }
    return { type: "READY", configs: listQuery.data?.items ?? [] };
  }, [listQuery.isLoading, listQuery.isError, listQuery.data]);

  const removeMutation = trpc.toolkit.removeConfig.useMutation({
    onSuccess: () => {
      void utils.toolkit.listConfigs.invalidate({ handle });
    },
  });

  const updateMutation = trpc.toolkit.updateConfig.useMutation({
    onSuccess: () => {
      void utils.toolkit.listConfigs.invalidate({ handle });
    },
  });

  const onDelete = useCallback(
    (toolkitId: string): void => {
      removeMutation.mutate({ handle, toolkitId });
    },
    [handle, removeMutation],
  );

  const onToggleEnabled = useCallback(
    (toolkit: ToolkitConfigResponse, enabled: boolean): void => {
      updateMutation.mutate({ handle, toolkitId: toolkit.id, enabled });
    },
    [handle, updateMutation],
  );

  return {
    handle,
    listState,
    onDelete,
    onToggleEnabled,
  };
}
