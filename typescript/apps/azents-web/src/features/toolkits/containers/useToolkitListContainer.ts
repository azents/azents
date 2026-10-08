"use client";

/**
 * Toolkit list container hook.
 *
 * Handles Toolkit list fetch, delete, and enabled toggle.
 */

import { useCallback, useMemo, useState } from "react";
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
  deleteTarget: string | null;
  deleteState:
    { type: "IDLE" } | { type: "PENDING" } | { type: "ERROR"; message: string };
  onConfirmDelete: () => void;
  onCancelDelete: () => void;
  onToggleEnabled: (toolkit: ToolkitConfigResponse, enabled: boolean) => void;
}

export function useToolkitListContainer(
  props: ToolkitListContainerProps,
): ToolkitListContainerOutput {
  const { handle } = props;

  const utils = trpc.useUtils();
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleteState, setDeleteState] = useState<
    ToolkitListContainerOutput["deleteState"]
  >({ type: "IDLE" });

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
      setDeleteTarget(null);
      setDeleteState({ type: "IDLE" });
    },
    onError: (error) =>
      setDeleteState({ type: "ERROR", message: error.message }),
    onSettled: async () => {
      await Promise.allSettled([
        utils.toolkit.listConfigs.invalidate({ handle }),
        utils.toolkit.getConfig.invalidate(),
        utils.toolkit.listAgentManagement.invalidate(),
        utils.toolkit.githubUser.status.invalidate(),
        utils.toolkit.githubUser.access.invalidate(),
        utils.toolkit.githubUser.review.invalidate(),
      ]);
    },
  });

  const updateMutation = trpc.toolkit.updateConfig.useMutation({
    onSuccess: () => {
      void utils.toolkit.listConfigs.invalidate({ handle });
    },
  });

  const onDelete = useCallback((toolkitId: string): void => {
    setDeleteState({ type: "IDLE" });
    setDeleteTarget(toolkitId);
  }, []);

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
    deleteTarget,
    deleteState,
    onCancelDelete: () => {
      if (!removeMutation.isPending) {
        setDeleteTarget(null);
        setDeleteState({ type: "IDLE" });
      }
    },
    onConfirmDelete: () => {
      if (deleteTarget != null && !removeMutation.isPending) {
        setDeleteState({ type: "PENDING" });
        removeMutation.mutate({ handle, toolkitId: deleteTarget });
      }
    },
    onToggleEnabled,
  };
}
