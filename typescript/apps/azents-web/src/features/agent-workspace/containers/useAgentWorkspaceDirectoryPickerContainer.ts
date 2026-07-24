"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  ProjectDirectoryPickerEntry,
  ProjectDirectoryPickerState,
} from "../types";

const WORKSPACE_TRANSITION_REFETCH_INTERVAL_MS = 2_000;

interface UseAgentWorkspaceDirectoryPickerContainerInput {
  handle: string;
  agentId: string;
  sessionId?: string;
  enabled?: boolean;
  onSelectDirectory?: (entry: ProjectDirectoryPickerEntry) => void;
  refreshQueries?: () => Promise<void> | void;
}

export interface AgentWorkspaceDirectoryPickerContainerOutput {
  state: ProjectDirectoryPickerState;
  isOpen: boolean;
  open: () => void;
  close: () => void;
  openDirectory: (path: string) => void;
  selectDirectory: (entry: ProjectDirectoryPickerEntry) => void;
  refresh: () => void;
  startRuntime: () => void;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Workspace request failed.";
}

export function useAgentWorkspaceDirectoryPickerContainer({
  handle,
  agentId,
  sessionId,
  enabled = true,
  onSelectDirectory,
  refreshQueries,
}: UseAgentWorkspaceDirectoryPickerContainerInput): AgentWorkspaceDirectoryPickerContainerOutput {
  const utils = trpc.useUtils();
  const [isOpen, setIsOpen] = useState(false);
  const [currentPath, setCurrentPath] = useState<string | null>(null);

  useEffect(() => {
    setIsOpen(false);
    setCurrentPath(null);
  }, [agentId, handle, sessionId]);

  const workspaceQuery = trpc.chat.getAgentWorkspace.useQuery(
    { agentId },
    {
      enabled: enabled && isOpen,
      refetchInterval: (query): number | false =>
        query.state.data?.workspace.type === "CONNECTING" ||
        query.state.data?.workspace.type === "CONTROL_UNAVAILABLE" ||
        query.state.data?.runtime.type === "STARTING" ||
        query.state.data?.runtime.type === "RESETTING" ||
        query.state.data?.runtime.type === "STOPPING"
          ? WORKSPACE_TRANSITION_REFETCH_INTERVAL_MS
          : false,
    },
  );
  const manifest =
    workspaceQuery.data?.workspace.type === "READY"
      ? workspaceQuery.data.workspace.manifest
      : null;
  const activePath = currentPath ?? manifest?.cwd ?? "";

  useEffect(() => {
    if (isOpen && manifest && currentPath === null) {
      setCurrentPath(manifest.cwd);
    }
  }, [currentPath, isOpen, manifest]);

  const directoryQuery = trpc.chat.readAgentWorkspacePath.useQuery(
    { agentId, sessionId, path: activePath },
    {
      enabled:
        enabled &&
        isOpen &&
        workspaceQuery.data?.workspace.type === "READY" &&
        activePath !== "",
    },
  );
  const startRuntimeMutation = trpc.chat.startAgentRuntime.useMutation({
    onSuccess: async () => {
      await utils.chat.getAgentWorkspace.invalidate({ agentId });
    },
  });

  const state = useMemo<ProjectDirectoryPickerState>(() => {
    if (!isOpen) {
      return { type: "CLOSED" };
    }
    if (workspaceQuery.isError) {
      return { type: "ERROR", message: errorMessage(workspaceQuery.error) };
    }
    if (workspaceQuery.isLoading || !workspaceQuery.data) {
      return { type: "LOADING" };
    }
    if (directoryQuery.isError) {
      return { type: "ERROR", message: errorMessage(directoryQuery.error) };
    }
    if (directoryQuery.isLoading && activePath !== manifest?.cwd) {
      return { type: "LOADING" };
    }
    const directoryResult = directoryQuery.data;
    const entries =
      directoryResult?.type === "DIRECTORY"
        ? directoryResult.entries.map((entry) => ({
            path: entry.path,
            kind: entry.kind,
            repositoryType: entry.repository_type ?? null,
          }))
        : (manifest?.entries.map((entry) => ({
            path: entry.path,
            kind: entry.kind,
            repositoryType: entry.repository_type ?? null,
          })) ?? []);
    return {
      type: "SERVER",
      server: workspaceQuery.data,
      currentPath: activePath,
      entries,
      isRefreshing: workspaceQuery.isFetching || directoryQuery.isFetching,
      isStarting: startRuntimeMutation.isPending,
    };
  }, [
    activePath,
    directoryQuery.data,
    directoryQuery.error,
    directoryQuery.isError,
    directoryQuery.isFetching,
    directoryQuery.isLoading,
    isOpen,
    manifest?.cwd,
    manifest?.entries,
    startRuntimeMutation.isPending,
    workspaceQuery.data,
    workspaceQuery.error,
    workspaceQuery.isError,
    workspaceQuery.isFetching,
    workspaceQuery.isLoading,
  ]);

  const open = useCallback((): void => {
    setCurrentPath(null);
    setIsOpen(true);
  }, []);
  const close = useCallback((): void => setIsOpen(false), []);
  const openDirectory = useCallback((path: string): void => {
    setCurrentPath(path);
  }, []);
  const selectDirectory = useCallback(
    (entry: ProjectDirectoryPickerEntry): void => {
      onSelectDirectory?.(entry);
      setIsOpen(false);
    },
    [onSelectDirectory],
  );
  const refresh = useCallback((): void => {
    if (refreshQueries) {
      void refreshQueries();
      return;
    }
    void Promise.all([
      utils.chat.getAgentWorkspace.invalidate({ agentId }),
      utils.chat.readAgentWorkspacePath.invalidate({ agentId }),
    ]);
  }, [
    agentId,
    refreshQueries,
    utils.chat.getAgentWorkspace,
    utils.chat.readAgentWorkspacePath,
  ]);
  const startRuntime = useCallback((): void => {
    startRuntimeMutation.mutate({ handle, agentId });
  }, [agentId, handle, startRuntimeMutation]);

  return {
    state,
    isOpen,
    open,
    close,
    openDirectory,
    selectDirectory,
    refresh,
    startRuntime,
  };
}
