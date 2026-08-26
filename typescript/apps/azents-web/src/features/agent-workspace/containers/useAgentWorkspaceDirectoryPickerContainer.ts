"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  shouldPollAgentWorkspaceLifecycle,
  shouldPollRuntimeLifecycle,
} from "@/features/runtime-lifecycle/runtimeLifecycle";
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
  restartRuntime: () => void;
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

  const runtimeQuery = trpc.chat.getAgentRuntime.useQuery(
    { handle, agentId },
    {
      enabled: enabled && isOpen,
      refetchInterval: (query): number | false => {
        const runtime = query.state.data;
        return shouldPollRuntimeLifecycle(runtime?.lifecycle, {
          removing: runtime?.capability === "removing",
          configurationStatus: runtime?.configuration?.status,
        })
          ? WORKSPACE_TRANSITION_REFETCH_INTERVAL_MS
          : false;
      },
    },
  );
  const runtimeManaged = runtimeQuery.data?.capability === "managed";
  const runnerAvailable = runtimeQuery.data?.actions.use_runner === true;
  const workspaceQuery = trpc.chat.getAgentWorkspace.useQuery(
    { agentId },
    {
      enabled: enabled && isOpen && runtimeManaged,
      refetchInterval: (query): number | false =>
        shouldPollAgentWorkspaceLifecycle(query.state.data, {
          configurationStatus: runtimeQuery.data?.configuration?.status,
        })
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
        runnerAvailable &&
        workspaceQuery.data?.workspace.type === "READY" &&
        activePath !== "",
    },
  );
  const startRuntimeMutation = trpc.chat.startAgentRuntime.useMutation({
    onSuccess: async () => {
      await Promise.all([
        utils.chat.getAgentRuntime.invalidate({ handle, agentId }),
        utils.chat.getAgentWorkspace.invalidate({ agentId }),
      ]);
    },
  });
  const restartRuntimeMutation = trpc.chat.restartAgentRuntime.useMutation({
    onSuccess: async () => {
      setCurrentPath(null);
      await Promise.all([
        utils.chat.getAgentRuntime.invalidate({ handle, agentId }),
        utils.chat.getAgentWorkspace.invalidate({ agentId }),
        utils.chat.readAgentWorkspacePath.invalidate({ agentId }),
      ]);
    },
  });

  const state = useMemo<ProjectDirectoryPickerState>(() => {
    if (!isOpen) {
      return { type: "CLOSED" };
    }
    if (runtimeQuery.isError) {
      return { type: "ERROR", message: errorMessage(runtimeQuery.error) };
    }
    if (runtimeQuery.isLoading || !runtimeQuery.data) {
      return { type: "LOADING" };
    }
    if (runtimeQuery.data.capability === "none") {
      return { type: "RUNTIME_FREE", runtime: runtimeQuery.data };
    }
    if (runtimeQuery.data.capability === "removing") {
      return { type: "REMOVING", runtime: runtimeQuery.data };
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
      isRestarting: restartRuntimeMutation.isPending,
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
    runtimeQuery.data,
    runtimeQuery.error,
    runtimeQuery.isError,
    runtimeQuery.isLoading,
    restartRuntimeMutation.isPending,
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
      utils.chat.getAgentRuntime.invalidate({ handle, agentId }),
      utils.chat.getAgentWorkspace.invalidate({ agentId }),
      utils.chat.readAgentWorkspacePath.invalidate({ agentId }),
    ]);
  }, [
    agentId,
    handle,
    refreshQueries,
    utils.chat.getAgentRuntime,
    utils.chat.getAgentWorkspace,
    utils.chat.readAgentWorkspacePath,
  ]);
  const startRuntime = useCallback((): void => {
    if (runtimeQuery.data?.actions.start !== true) {
      return;
    }
    startRuntimeMutation.mutate({ handle, agentId });
  }, [agentId, handle, runtimeQuery.data?.actions.start, startRuntimeMutation]);
  const restartRuntime = useCallback((): void => {
    if (workspaceQuery.data?.actions.restart === null) {
      return;
    }
    restartRuntimeMutation.mutate({ handle, agentId });
  }, [
    agentId,
    handle,
    restartRuntimeMutation,
    workspaceQuery.data?.actions.restart,
  ]);

  return {
    state,
    isOpen,
    open,
    close,
    openDirectory,
    selectDirectory,
    refresh,
    startRuntime,
    restartRuntime,
  };
}
