"use client";

/** Workspace panel container hook. */
import { useCallback, useEffect, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  mapWorkspaceManifest,
  mapWorkspacePathResult,
  mapWorkspacePathStat,
  type WorkspaceEntry,
  type WorkspacePanelState,
  type WorkspaceProjectPanelState,
} from "../types";

const WORKSPACE_TRANSITION_REFETCH_INTERVAL_MS = 2_000;

interface UseWorkspacePanelContainerInput {
  handle: string;
  agentId: string;
  sessionId: string;
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
  onShowInfo: (path: string) => void;
  onBackToBrowser: () => void;
  onToggleSelectedPath: (path: string) => void;
  onClearSelection: () => void;
  onRefresh: () => void;
  onCreateDirectory: (path: string) => void;
  onRenamePath: (sourcePath: string, newName: string) => void;
  onMovePath: (sourcePath: string, destinationPath: string) => void;
  onDeletePath: (path: string, recursive: boolean) => void;
  onBulkMovePaths: (destinationDirectory: string) => void;
  onBulkDeletePaths: (recursive: boolean) => void;
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

function parentPath(path: string): string {
  return path.slice(0, Math.max(0, path.lastIndexOf("/")));
}

function isSameOrDescendant(path: string, targetPath: string): boolean {
  return path === targetPath || path.startsWith(`${targetPath}/`);
}

function removeDeletedWorkspaceEntries(
  entriesByPath: Record<string, WorkspaceEntry[]>,
  deletedPaths: string[],
): Record<string, WorkspaceEntry[]> {
  const isDeleted = (path: string): boolean =>
    deletedPaths.some((deletedPath) => isSameOrDescendant(path, deletedPath));
  return Object.fromEntries(
    Object.entries(entriesByPath)
      .filter(([path]) => !isDeleted(path))
      .map(([path, entries]) => [
        path,
        entries.filter((entry) => !isDeleted(entry.path)),
      ]),
  );
}

export function useWorkspacePanelContainer({
  handle,
  agentId,
  sessionId,
}: UseWorkspacePanelContainerInput): WorkspacePanelContainerOutput {
  const [currentDirectoryPath, setCurrentDirectoryPath] = useState<
    string | null
  >(null);
  const [workspaceView, setWorkspaceView] = useState<
    "browser" | "preview" | "info"
  >("browser");
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
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
    setSelectedPaths([]);
    setWorkspaceView("browser");
    setDirectoryEntriesByPath({});
  }, [agentId, sessionId]);

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

  const projectsQuery = trpc.chat.listAgentProjects.useQuery({
    agentId,
    sessionId,
  });
  const registrationRequestsQuery =
    trpc.chat.listAgentProjectRegistrationRequests.useQuery({
      agentId,
      sessionId,
    });

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
    { agentId, sessionId, path: activeDirectoryPath },
    {
      enabled:
        workspaceQuery.data?.workspace.type === "READY" &&
        activeDirectoryPath !== "",
    },
  );

  const selectedEntry = useMemo(() => {
    if (!selectedFilePath) {
      return null;
    }
    for (const entries of Object.values(directoryEntriesByPath)) {
      const found = entries.find((entry) => entry.path === selectedFilePath);
      if (found) {
        return found;
      }
    }
    return null;
  }, [directoryEntriesByPath, selectedFilePath]);

  const fileQuery = trpc.chat.readAgentWorkspacePath.useQuery(
    { agentId, sessionId, path: selectedFilePath ?? "" },
    {
      enabled:
        workspaceQuery.data?.workspace.type === "READY" &&
        selectedFilePath !== null &&
        selectedEntry?.kind === "file" &&
        workspaceView === "preview",
    },
  );

  const statQuery = trpc.chat.statAgentWorkspacePath.useQuery(
    { agentId, path: selectedFilePath ?? "" },
    {
      enabled:
        workspaceQuery.data?.workspace.type === "READY" &&
        selectedFilePath !== null &&
        workspaceView === "info",
    },
  );

  const invalidateWorkspaceFiles = useCallback(
    async (path?: string) => {
      await Promise.all([
        utils.chat.getAgentWorkspace.invalidate({ agentId }),
        utils.chat.readAgentWorkspacePath.invalidate({ agentId }),
        utils.chat.statAgentWorkspacePath.invalidate({ agentId, path }),
      ]);
    },
    [
      agentId,
      utils.chat.getAgentWorkspace,
      utils.chat.readAgentWorkspacePath,
      utils.chat.statAgentWorkspacePath,
    ],
  );

  const createDirectoryMutation =
    trpc.chat.createAgentWorkspaceDirectory.useMutation({
      onSuccess: async () => {
        await invalidateWorkspaceFiles();
      },
    });

  const deletePathMutation = trpc.chat.deleteAgentWorkspacePath.useMutation({
    onSuccess: async (_data, variables) => {
      const deletedPath = variables.path;
      if (
        selectedFilePath &&
        isSameOrDescendant(selectedFilePath, deletedPath)
      ) {
        setSelectedFilePath(null);
        setWorkspaceView("browser");
      }
      if (
        currentDirectoryPath &&
        isSameOrDescendant(currentDirectoryPath, deletedPath)
      ) {
        setCurrentDirectoryPath(
          parentPath(deletedPath) || manifest?.cwd || null,
        );
        setWorkspaceView("browser");
      }
      setSelectedPaths((previous) =>
        previous.filter((path) => !isSameOrDescendant(path, deletedPath)),
      );
      setDirectoryEntriesByPath((previous) =>
        removeDeletedWorkspaceEntries(previous, [deletedPath]),
      );
      await invalidateWorkspaceFiles(deletedPath);
    },
  });

  const bulkDeletePathsMutation =
    trpc.chat.bulkDeleteAgentWorkspacePaths.useMutation({
      onSuccess: async (_data, variables) => {
        const deletedPaths = variables.paths;
        const includesDeletedPath = (path: string): boolean =>
          deletedPaths.some((deletedPath) =>
            isSameOrDescendant(path, deletedPath),
          );
        if (selectedFilePath && includesDeletedPath(selectedFilePath)) {
          setSelectedFilePath(null);
          setWorkspaceView("browser");
        }
        if (currentDirectoryPath && includesDeletedPath(currentDirectoryPath)) {
          const deletedAncestor = deletedPaths.find((deletedPath) =>
            isSameOrDescendant(currentDirectoryPath, deletedPath),
          );
          setCurrentDirectoryPath(
            deletedAncestor
              ? parentPath(deletedAncestor) || manifest?.cwd || null
              : null,
          );
          setWorkspaceView("browser");
        }
        setSelectedPaths([]);
        setDirectoryEntriesByPath((previous) =>
          removeDeletedWorkspaceEntries(previous, deletedPaths),
        );
        await invalidateWorkspaceFiles();
      },
    });

  const movePathMutation = trpc.chat.moveAgentWorkspacePath.useMutation({
    onSuccess: async (_data, variables) => {
      if (selectedFilePath === variables.sourcePath) {
        setSelectedFilePath(variables.destinationPath);
      }
      setSelectedPaths((previous) =>
        previous.map((path) =>
          path === variables.sourcePath ? variables.destinationPath : path,
        ),
      );
      await invalidateWorkspaceFiles(variables.destinationPath);
    },
  });

  const bulkMovePathsMutation =
    trpc.chat.bulkMoveAgentWorkspacePaths.useMutation({
      onSuccess: async () => {
        setSelectedPaths([]);
        setWorkspaceView("browser");
        await invalidateWorkspaceFiles();
      },
    });

  const startRuntimeMutation = trpc.chat.startAgentRuntime.useMutation({
    onSuccess: async (_data, variables) => {
      await utils.chat.getAgentWorkspace.invalidate({
        agentId: variables.agentId,
      });
      await utils.chat.readAgentWorkspacePath.invalidate();
    },
  });

  const clearWorkspaceSelection = useCallback(() => {
    setSelectedFilePath(null);
    setSelectedPaths([]);
    setWorkspaceView("browser");
  }, []);

  const stopRuntimeMutation = trpc.chat.stopAgentRuntime.useMutation({
    onSuccess: async (_data, variables) => {
      clearWorkspaceSelection();
      setCurrentDirectoryPath(null);
      await utils.chat.getAgentWorkspace.invalidate({
        agentId: variables.agentId,
      });
      await utils.chat.readAgentWorkspacePath.invalidate();
    },
  });

  const restartRuntimeMutation = trpc.chat.restartAgentRuntime.useMutation({
    onSuccess: async (_data, variables) => {
      clearWorkspaceSelection();
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
      clearWorkspaceSelection();
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
      await utils.chat.listAgentProjects.invalidate({ agentId, sessionId });
    },
    onError: (error) => setRegisterProjectError(error.message),
  });

  const approveRegistrationRequestMutation =
    trpc.chat.approveAgentProjectRegistrationRequest.useMutation({
      onSuccess: async () => {
        setPendingApproveRequestId(null);
        await Promise.all([
          utils.chat.listAgentProjects.invalidate({ agentId, sessionId }),
          utils.chat.listAgentProjectRegistrationRequests.invalidate({
            agentId,
            sessionId,
          }),
        ]);
      },
      onError: () => setPendingApproveRequestId(null),
    });

  const rejectRegistrationRequestMutation =
    trpc.chat.rejectAgentProjectRegistrationRequest.useMutation({
      onSuccess: async () => {
        setPendingRejectRequestId(null);
        await utils.chat.listAgentProjectRegistrationRequests.invalidate({
          agentId,
          sessionId,
        });
      },
      onError: () => setPendingRejectRequestId(null),
    });

  const deleteProjectMutation = trpc.chat.deleteAgentProject.useMutation({
    onSuccess: async () => {
      setPendingDeleteProjectId(null);
      await utils.chat.listAgentProjects.invalidate({ agentId, sessionId });
    },
    onError: () => setPendingDeleteProjectId(null),
  });

  const onStartRuntime = useCallback(
    () => startRuntimeMutation.mutate({ handle, agentId }),
    [agentId, handle, startRuntimeMutation],
  );
  const onStopRuntime = useCallback(
    () => stopRuntimeMutation.mutate({ handle, agentId }),
    [agentId, handle, stopRuntimeMutation],
  );
  const onRestartRuntime = useCallback(
    () => restartRuntimeMutation.mutate({ handle, agentId }),
    [agentId, handle, restartRuntimeMutation],
  );
  const onResetRuntime = useCallback(
    () => resetRuntimeMutation.mutate({ handle, agentId }),
    [agentId, handle, resetRuntimeMutation],
  );

  const onOpenDirectory = useCallback((path: string) => {
    setCurrentDirectoryPath(path);
    setSelectedFilePath(path);
    setWorkspaceView("browser");
  }, []);

  const onOpenFile = useCallback((path: string) => {
    setSelectedFilePath(path);
    setWorkspaceView("preview");
  }, []);

  const onShowInfo = useCallback((path: string) => {
    setSelectedFilePath(path);
    setWorkspaceView("info");
  }, []);

  const onToggleSelectedPath = useCallback((path: string) => {
    setSelectedPaths((previous) =>
      previous.includes(path)
        ? previous.filter((value) => value !== path)
        : [...previous, path],
    );
  }, []);

  const onCreateDirectory = useCallback(
    (path: string) =>
      createDirectoryMutation.mutate({ agentId, path, parents: false }),
    [agentId, createDirectoryMutation],
  );

  const onRenamePath = useCallback(
    (sourcePath: string, newName: string) => {
      const destinationPath = `${parentPath(sourcePath)}/${newName}`;
      movePathMutation.mutate({
        agentId,
        sourcePath,
        destinationPath,
        overwrite: false,
      });
    },
    [agentId, movePathMutation],
  );

  const onMovePath = useCallback(
    (sourcePath: string, destinationPath: string) => {
      movePathMutation.mutate({
        agentId,
        sourcePath,
        destinationPath,
        overwrite: false,
      });
    },
    [agentId, movePathMutation],
  );

  const onDeletePath = useCallback(
    (path: string, recursive: boolean) =>
      deletePathMutation.mutate({ agentId, path, recursive }),
    [agentId, deletePathMutation],
  );

  const onBulkMovePaths = useCallback(
    (destinationDirectory: string) => {
      if (selectedPaths.length === 0) {
        return;
      }
      bulkMovePathsMutation.mutate({
        agentId,
        sourcePaths: selectedPaths,
        destinationDirectory,
        overwrite: false,
      });
    },
    [agentId, bulkMovePathsMutation, selectedPaths],
  );

  const onBulkDeletePaths = useCallback(
    (recursive: boolean) => {
      if (selectedPaths.length === 0) {
        return;
      }
      bulkDeletePathsMutation.mutate({
        agentId,
        paths: selectedPaths,
        recursive,
      });
    },
    [agentId, bulkDeletePathsMutation, selectedPaths],
  );

  const onRefresh = useCallback(() => {
    setIsManualRefreshing(true);
    void Promise.all([
      utils.chat.getAgentWorkspace.invalidate({ agentId }),
      utils.chat.readAgentWorkspacePath.invalidate({ agentId }),
      utils.chat.listAgentProjects.invalidate({ agentId, sessionId }),
      utils.chat.listAgentProjectRegistrationRequests.invalidate({
        agentId,
        sessionId,
      }),
    ]).finally(() => setIsManualRefreshing(false));
  }, [
    agentId,
    sessionId,
    utils.chat.getAgentWorkspace,
    utils.chat.listAgentProjectRegistrationRequests,
    utils.chat.listAgentProjects,
    utils.chat.readAgentWorkspacePath,
  ]);

  const getDownloadHref = useCallback(
    (path: string): string =>
      `/api/chat/agents/${encodeURIComponent(agentId)}/workspace/download?path=${encodeURIComponent(path)}`,
    [agentId],
  );

  const onRegisterProject = useCallback(() => {
    setRegisterProjectError(null);
    registerProjectMutation.mutate({
      agentId,
      sessionId,
      path: registerProjectPath,
    });
  }, [agentId, registerProjectMutation, registerProjectPath, sessionId]);

  const onApproveRegistrationRequest = useCallback(
    (requestId: string) => {
      setPendingApproveRequestId(requestId);
      approveRegistrationRequestMutation.mutate({
        agentId,
        sessionId,
        requestId,
      });
    },
    [agentId, approveRegistrationRequestMutation, sessionId],
  );

  const onRejectRegistrationRequest = useCallback(
    (requestId: string) => {
      setPendingRejectRequestId(requestId);
      rejectRegistrationRequestMutation.mutate({
        agentId,
        sessionId,
        requestId,
      });
    },
    [agentId, rejectRegistrationRequestMutation, sessionId],
  );

  const onDeleteProject = useCallback(
    (projectId: string) => {
      setPendingDeleteProjectId(projectId);
      deleteProjectMutation.mutate({ agentId, sessionId, projectId });
    },
    [agentId, deleteProjectMutation, sessionId],
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
        ? { path: mappedDirectory.path, entries: mappedDirectory.entries }
        : {
            path: activeDirectoryPath || manifest?.cwd || "",
            entries: manifest?.entries ?? [],
          };

    const fileState = (() => {
      if (
        !selectedFilePath ||
        selectedEntry?.kind !== "file" ||
        workspaceView !== "preview"
      ) {
        return { type: "IDLE" } as const;
      }
      if (fileQuery.isLoading) {
        return { type: "LOADING", path: selectedFilePath } as const;
      }
      if (fileQuery.isError) {
        return {
          type: "ERROR",
          message: getErrorMessage(fileQuery.error),
        } as const;
      }
      if (!fileQuery.data) {
        return { type: "LOADING", path: selectedFilePath } as const;
      }
      const mappedFile = mapWorkspacePathResult(fileQuery.data);
      return mappedFile.type === "FILE"
        ? ({ type: "LOADED", file: mappedFile.file } as const)
        : ({ type: "IDLE" } as const);
    })();

    return {
      type: "SERVER",
      server: workspaceQuery.data,
      manifest,
      directory,
      directoryEntriesByPath,
      fileState,
      workspaceView,
      selectedFilePath,
      selectedEntry,
      selectedPaths,
      inspectorState: (() => {
        if (!selectedFilePath || workspaceView !== "info") {
          return { type: "IDLE" } as const;
        }
        if (statQuery.isLoading) {
          return { type: "LOADING", path: selectedFilePath } as const;
        }
        if (statQuery.isError) {
          return {
            type: "ERROR",
            message: getErrorMessage(statQuery.error),
          } as const;
        }
        if (!statQuery.data) {
          return { type: "LOADING", path: selectedFilePath } as const;
        }
        return {
          type: "LOADED",
          stat: mapWorkspacePathStat(statQuery.data),
        } as const;
      })(),
      isRefreshing: isManualRefreshing || directoryQuery.isFetching,
      isMutating:
        createDirectoryMutation.isPending ||
        deletePathMutation.isPending ||
        bulkDeletePathsMutation.isPending ||
        movePathMutation.isPending ||
        bulkMovePathsMutation.isPending,
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
    bulkDeletePathsMutation.isPending,
    bulkMovePathsMutation.isPending,
    createDirectoryMutation.isPending,
    deletePathMutation.isPending,
    directoryEntriesByPath,
    directoryQuery.data,
    directoryQuery.isFetching,
    fileQuery.data,
    fileQuery.error,
    fileQuery.isError,
    fileQuery.isLoading,
    isManualRefreshing,
    manifest,
    movePathMutation.isPending,
    resetRuntimeMutation.isPending,
    restartRuntimeMutation.isPending,
    selectedEntry,
    selectedFilePath,
    selectedPaths,
    startRuntimeMutation.isPending,
    statQuery.data,
    statQuery.error,
    statQuery.isError,
    statQuery.isLoading,
    stopRuntimeMutation.isPending,
    workspaceQuery.data,
    workspaceQuery.error,
    workspaceQuery.isError,
    workspaceQuery.isLoading,
    workspaceView,
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
    onShowInfo,
    onBackToBrowser: () => setWorkspaceView("browser"),
    onToggleSelectedPath,
    onClearSelection: () => setSelectedPaths([]),
    onRefresh,
    onCreateDirectory,
    onRenamePath,
    onMovePath,
    onDeletePath,
    onBulkMovePaths,
    onBulkDeletePaths,
    getDownloadHref,
    onRegisterProjectPathChange: setRegisterProjectPath,
    onRegisterProject,
    onApproveRegistrationRequest,
    onRejectRegistrationRequest,
    onDeleteProject,
  };
}
