"use client";

/**
 * Workspace panel container hook.
 *
 * tRPC call, selected path, runtime lifecycle mutation  owns and UI ADT  with convert..
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  mapWorkspaceManifest,
  mapWorkspacePathResult,
  type WorkspaceEntry,
  type WorkspacePanelState,
  type WorkspaceProjectPanelState,
} from "../types";

const WORKSPACE_TRANSITION_REFETCH_INTERVAL_MS = 2_000;

interface UseWorkspacePanelContainerInput {
  handle: string;
  agentId: string;
}

export interface WorkspacePanelContainerOutput {
  state: WorkspacePanelState;
  projectState: WorkspaceProjectPanelState;
  onStartRuntime: () => void;
  onStopRuntime: () => void;
  onRestartRuntime: () => void;
  onResetRuntime: () => void;
  onOpenDirectory: (path: string) => void;
  onOpenFile: (path: string) => void;
  onRefresh: () => void;
  getDownloadHref: (path: string) => string;
  onRegisterProjectPathChange: (path: string) => void;
  onRegisterProject: () => void;
  onApproveRegistrationRequest: (requestId: string) => void;
  onRejectRegistrationRequest: (requestId: string) => void;
  onDeleteProject: (projectId: string) => void;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Workspace request failed.";
}

export function useWorkspacePanelContainer({
  handle,
  agentId,
}: UseWorkspacePanelContainerInput): WorkspacePanelContainerOutput {
  const [currentDirectoryPath, setCurrentDirectoryPath] = useState<
    string | null
  >(null);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [directoryEntriesByPath, setDirectoryEntriesByPath] = useState<
    Record<string, WorkspaceEntry[]>
  >({});
  const utils = trpc.useUtils();
  const [registerProjectPath, setRegisterProjectPath] = useState("");
  const [registerProjectError, setRegisterProjectError] = useState<
    string | null
  >(null);
  const [pendingApproveRequestId, setPendingApproveRequestId] = useState<
    string | null
  >(null);
  const [pendingRejectRequestId, setPendingRejectRequestId] = useState<
    string | null
  >(null);
  const [pendingDeleteProjectId, setPendingDeleteProjectId] = useState<
    string | null
  >(null);
  const [isManualRefreshing, setIsManualRefreshing] = useState(false);

  useEffect(() => {
    setCurrentDirectoryPath(null);
    setSelectedFilePath(null);
    setDirectoryEntriesByPath({});
  }, [agentId]);

  const workspaceQuery = trpc.chat.getAgentWorkspace.useQuery(
    { agentId },
    {
      enabled: true,
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

  const projectsQuery = trpc.chat.listAgentProjects.useQuery({ agentId });

  const registrationRequestsQuery =
    trpc.chat.listAgentProjectRegistrationRequests.useQuery({ agentId });

  const manifest = useMemo(() => {
    if (workspaceQuery.data?.workspace.type !== "READY") {
      return null;
    }
    return mapWorkspaceManifest(workspaceQuery.data.workspace.manifest);
  }, [workspaceQuery.data]);

  const activeDirectoryPath = currentDirectoryPath ?? manifest?.cwd ?? "";

  useEffect(() => {
    if (!manifest || registerProjectPath.trim() !== "") {
      return;
    }
    setRegisterProjectPath(`${manifest.root}/`);
  }, [manifest, registerProjectPath]);

  useEffect(() => {
    if (!manifest) {
      return;
    }
    setDirectoryEntriesByPath((previous) => ({
      ...previous,
      [manifest.cwd]: manifest.entries,
    }));
  }, [manifest]);

  const directoryQuery = trpc.chat.readAgentWorkspacePath.useQuery(
    {
      agentId,
      path: activeDirectoryPath,
    },
    {
      enabled:
        workspaceQuery.data?.workspace.type === "READY" &&
        activeDirectoryPath !== "",
    },
  );

  const fileQuery = trpc.chat.readAgentWorkspacePath.useQuery(
    {
      agentId,
      path: selectedFilePath ?? "",
    },
    {
      enabled:
        workspaceQuery.data?.workspace.type === "READY" &&
        selectedFilePath !== null,
    },
  );

  const startRuntimeMutation = trpc.chat.startAgentRuntime.useMutation({
    onSuccess: async (_data, variables) => {
      await utils.chat.getAgentWorkspace.invalidate({
        agentId: variables.agentId,
      });
      await utils.chat.readAgentWorkspacePath.invalidate();
    },
  });

  const stopRuntimeMutation = trpc.chat.stopAgentRuntime.useMutation({
    onSuccess: async (_data, variables) => {
      setSelectedFilePath(null);
      setCurrentDirectoryPath(null);
      await utils.chat.getAgentWorkspace.invalidate({
        agentId: variables.agentId,
      });
      await utils.chat.readAgentWorkspacePath.invalidate();
    },
  });

  const restartRuntimeMutation = trpc.chat.restartAgentRuntime.useMutation({
    onSuccess: async (_data, variables) => {
      setSelectedFilePath(null);
      setCurrentDirectoryPath(null);
      setDirectoryEntriesByPath({});
      await utils.chat.getAgentWorkspace.invalidate({
        agentId: variables.agentId,
      });
      await utils.chat.readAgentWorkspacePath.invalidate();
    },
  });

  const resetRuntimeMutation = trpc.chat.resetAgentRuntime.useMutation({
    onSuccess: async (_data, variables) => {
      setSelectedFilePath(null);
      setCurrentDirectoryPath(null);
      setDirectoryEntriesByPath({});
      await utils.chat.getAgentWorkspace.invalidate({
        agentId: variables.agentId,
      });
      await utils.chat.readAgentWorkspacePath.invalidate();
    },
  });

  const registerProjectMutation = trpc.chat.registerAgentProject.useMutation({
    onSuccess: async () => {
      setRegisterProjectError(null);
      await utils.chat.listAgentProjects.invalidate({ agentId });
    },
    onError: (error) => {
      setRegisterProjectError(error.message);
    },
  });

  const approveRegistrationRequestMutation =
    trpc.chat.approveAgentProjectRegistrationRequest.useMutation({
      onSuccess: async () => {
        setPendingApproveRequestId(null);
        await Promise.all([
          utils.chat.listAgentProjects.invalidate({ agentId }),
          utils.chat.listAgentProjectRegistrationRequests.invalidate({
            agentId,
          }),
        ]);
      },
      onError: () => {
        setPendingApproveRequestId(null);
      },
    });

  const rejectRegistrationRequestMutation =
    trpc.chat.rejectAgentProjectRegistrationRequest.useMutation({
      onSuccess: async () => {
        setPendingRejectRequestId(null);
        await utils.chat.listAgentProjectRegistrationRequests.invalidate({
          agentId,
        });
      },
      onError: () => {
        setPendingRejectRequestId(null);
      },
    });

  const deleteProjectMutation = trpc.chat.deleteAgentProject.useMutation({
    onSuccess: async () => {
      setPendingDeleteProjectId(null);
      await utils.chat.listAgentProjects.invalidate({ agentId });
    },
    onError: () => {
      setPendingDeleteProjectId(null);
    },
  });

  const onStartRuntime = useCallback(() => {
    startRuntimeMutation.mutate({ handle, agentId });
  }, [agentId, handle, startRuntimeMutation]);

  const onStopRuntime = useCallback(() => {
    stopRuntimeMutation.mutate({ handle, agentId });
  }, [agentId, handle, stopRuntimeMutation]);

  const onRestartRuntime = useCallback(() => {
    restartRuntimeMutation.mutate({ handle, agentId });
  }, [agentId, handle, restartRuntimeMutation]);

  const onResetRuntime = useCallback(() => {
    resetRuntimeMutation.mutate({ handle, agentId });
  }, [agentId, handle, resetRuntimeMutation]);

  const onOpenDirectory = useCallback((path: string) => {
    setCurrentDirectoryPath(path);
    setSelectedFilePath(null);
  }, []);

  const onOpenFile = useCallback((path: string) => {
    setSelectedFilePath(path);
  }, []);

  const onRefresh = useCallback(() => {
    setIsManualRefreshing(true);
    void Promise.all([
      utils.chat.getAgentWorkspace.invalidate({ agentId }),
      utils.chat.readAgentWorkspacePath.invalidate({ agentId }),
      utils.chat.listAgentProjects.invalidate({ agentId }),
      utils.chat.listAgentProjectRegistrationRequests.invalidate({
        agentId,
      }),
    ]).finally(() => {
      setIsManualRefreshing(false);
    });
  }, [
    agentId,
    utils.chat.getAgentWorkspace,
    utils.chat.listAgentProjectRegistrationRequests,
    utils.chat.listAgentProjects,
    utils.chat.readAgentWorkspacePath,
  ]);

  const getDownloadHref = useCallback(
    (path: string): string => {
      return `/api/chat/agents/${encodeURIComponent(agentId)}/workspace/download?path=${encodeURIComponent(path)}`;
    },
    [agentId],
  );

  const onRegisterProject = useCallback(() => {
    setRegisterProjectError(null);
    registerProjectMutation.mutate({
      agentId,
      path: registerProjectPath,
    });
  }, [agentId, registerProjectMutation, registerProjectPath]);

  const onApproveRegistrationRequest = useCallback(
    (requestId: string) => {
      setPendingApproveRequestId(requestId);
      approveRegistrationRequestMutation.mutate({ agentId, requestId });
    },
    [agentId, approveRegistrationRequestMutation],
  );

  const onRejectRegistrationRequest = useCallback(
    (requestId: string) => {
      setPendingRejectRequestId(requestId);
      rejectRegistrationRequestMutation.mutate({ agentId, requestId });
    },
    [agentId, rejectRegistrationRequestMutation],
  );

  const onDeleteProject = useCallback(
    (projectId: string) => {
      setPendingDeleteProjectId(projectId);
      deleteProjectMutation.mutate({ agentId, projectId });
    },
    [agentId, deleteProjectMutation],
  );

  useEffect(() => {
    if (!directoryQuery.data) {
      return;
    }
    const mappedDirectory = mapWorkspacePathResult(directoryQuery.data);
    if (mappedDirectory.type !== "DIRECTORY") {
      return;
    }
    setDirectoryEntriesByPath((previous) => ({
      ...previous,
      [mappedDirectory.path]: mappedDirectory.entries,
    }));
  }, [directoryQuery.data]);

  const state = useMemo<WorkspacePanelState>(() => {
    if (workspaceQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (workspaceQuery.isError) {
      return { type: "ERROR", message: getErrorMessage(workspaceQuery.error) };
    }
    if (!workspaceQuery.data) {
      return { type: "LOADING" };
    }

    const mappedDirectory = directoryQuery.data
      ? mapWorkspacePathResult(directoryQuery.data)
      : null;
    const directory =
      manifest && mappedDirectory?.type === "DIRECTORY"
        ? {
            path: mappedDirectory.path,
            entries: mappedDirectory.entries,
          }
        : {
            path: activeDirectoryPath || manifest?.cwd || "",
            entries: manifest?.entries ?? [],
          };

    const fileState = (() => {
      if (!selectedFilePath) {
        return { type: "IDLE" } as const;
      }
      if (fileQuery.isLoading) {
        return { type: "LOADING", path: selectedFilePath } as const;
      }
      if (fileQuery.isError || directoryQuery.isError) {
        return {
          type: "ERROR",
          message: getErrorMessage(fileQuery.error ?? directoryQuery.error),
        } as const;
      }
      if (!fileQuery.data) {
        return { type: "LOADING", path: selectedFilePath } as const;
      }
      const mappedFile = mapWorkspacePathResult(fileQuery.data);
      if (mappedFile.type === "FILE") {
        return { type: "LOADED", file: mappedFile.file } as const;
      }
      return { type: "IDLE" } as const;
    })();

    return {
      type: "SERVER",
      server: workspaceQuery.data,
      manifest,
      directory,
      directoryEntriesByPath,
      fileState,
      selectedFilePath,
      isRefreshing: isManualRefreshing || directoryQuery.isFetching,
      isStarting:
        startRuntimeMutation.isPending ||
        restartRuntimeMutation.isPending ||
        stopRuntimeMutation.isPending ||
        resetRuntimeMutation.isPending,
      isStopping: stopRuntimeMutation.isPending,
      isResetting: resetRuntimeMutation.isPending,
    };
  }, [
    activeDirectoryPath,
    directoryQuery.data,
    directoryQuery.error,
    directoryQuery.isError,
    directoryQuery.isFetching,
    directoryEntriesByPath,
    fileQuery.data,
    fileQuery.error,
    fileQuery.isError,
    fileQuery.isLoading,
    isManualRefreshing,
    manifest,
    selectedFilePath,
    restartRuntimeMutation.isPending,
    startRuntimeMutation.isPending,
    stopRuntimeMutation.isPending,
    resetRuntimeMutation.isPending,
    workspaceQuery.data,
    workspaceQuery.error,
    workspaceQuery.isError,
    workspaceQuery.isLoading,
  ]);

  const projectState = useMemo<WorkspaceProjectPanelState>(() => {
    if (projectsQuery.isLoading || registrationRequestsQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (projectsQuery.isError) {
      return { type: "ERROR", message: getErrorMessage(projectsQuery.error) };
    }
    if (registrationRequestsQuery.isError) {
      return {
        type: "ERROR",
        message: getErrorMessage(registrationRequestsQuery.error),
      };
    }
    return {
      type: "READY",
      projects: projectsQuery.data?.items ?? [],
      registrationRequests: registrationRequestsQuery.data?.items ?? [],
      registerProjectPath,
      isRegisteringProject: registerProjectMutation.isPending,
      registerProjectError,
      pendingApproveRequestId,
      pendingRejectRequestId,
      pendingDeleteProjectId,
    };
  }, [
    pendingApproveRequestId,
    pendingDeleteProjectId,
    pendingRejectRequestId,
    projectsQuery.data?.items,
    projectsQuery.error,
    projectsQuery.isError,
    projectsQuery.isLoading,
    registerProjectError,
    registerProjectMutation.isPending,
    registerProjectPath,
    registrationRequestsQuery.data?.items,
    registrationRequestsQuery.error,
    registrationRequestsQuery.isError,
    registrationRequestsQuery.isLoading,
  ]);

  return {
    state,
    projectState,
    onStartRuntime,
    onStopRuntime,
    onRestartRuntime,
    onResetRuntime,
    onOpenDirectory,
    onOpenFile,
    onRefresh,
    getDownloadHref,
    onRegisterProjectPathChange: setRegisterProjectPath,
    onRegisterProject,
    onApproveRegistrationRequest,
    onRejectRegistrationRequest,
    onDeleteProject,
  };
}
