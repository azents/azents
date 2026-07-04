"use client";

/** Workspace panel container hook. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  mapProjectBrowserManifest,
  mapWorkspaceManifest,
  mapWorkspacePathResult,
  mapWorkspacePathStat,
  type WorkspaceBrowserMode,
  type WorkspaceEntry,
  type WorkspacePanelState,
  type WorkspaceProjectPanelState,
} from "../types";
import type { ProjectDirectoryPickerState } from "../components/WorkspaceDirectoryPickerModal";

const WORKSPACE_TRANSITION_REFETCH_INTERVAL_MS = 2_000;

interface UseWorkspacePanelContainerInput {
  handle: string;
  agentId: string;
  sessionId: string;
  autoRefreshVisible: boolean;
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
  projectPickerState: ProjectDirectoryPickerState;
  isProjectPickerOpen: boolean;
  onOpenProjectPicker: () => void;
  onCloseProjectPicker: () => void;
  onOpenProjectPickerDirectory: (path: string) => void;
  onSelectProjectPickerDirectory: (path: string) => void;
  onRefreshProjectPicker: () => void;
  worktreeSourceProjectPath: string | null;
  worktreeStartingRef: string | null;
  worktreeRefOptions: { value: string; label: string }[];
  isLoadingWorktreeRefs: boolean;
  worktreeRefError: string | null;
  isAttachingWorktreeProject: boolean;
  attachWorktreeProjectError: string | null;
  onOpenWorktreeSourcePicker: () => void;
  onSetWorktreeStartingRef: (ref: string | null) => void;
  onAttachWorktreeProject: () => void;
  onCancelWorktreeProjectAttach: () => void;
  onStartRuntimeForProjectPicker: () => void;
  onApproveRegistrationRequest: (requestId: string) => void;
  onRejectRegistrationRequest: (requestId: string) => void;
  onDeleteProject: (projectId: string) => void;
  onRemoveProjectEntry: (entry: WorkspaceEntry) => void;
  onSetBrowserMode: (mode: WorkspaceBrowserMode) => void;
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
  autoRefreshVisible,
}: UseWorkspacePanelContainerInput): WorkspacePanelContainerOutput {
  const [currentDirectoryPath, setCurrentDirectoryPath] = useState<
    string | null
  >(null);
  const [browserMode, setBrowserMode] =
    useState<WorkspaceBrowserMode>("projects");
  const [workspaceView, setWorkspaceView] = useState<
    "browser" | "preview" | "info"
  >("browser");
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [directoryEntriesByPath, setDirectoryEntriesByPath] = useState<
    Record<string, WorkspaceEntry[]>
  >({});
  const utils = trpc.useUtils();
  const [projectPickerOpen, setProjectPickerOpen] = useState(false);
  const [projectPickerPurpose, setProjectPickerPurpose] = useState<
    "register_project" | "worktree_source"
  >("register_project");
  const [worktreeSourceProjectPath, setWorktreeSourceProjectPath] = useState<
    string | null
  >(null);
  const [worktreeStartingRef, setWorktreeStartingRef] = useState<string | null>(
    null,
  );
  const [attachWorktreeProjectError, setAttachWorktreeProjectError] = useState<
    string | null
  >(null);
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
  const autoRefreshKeyRef = useRef<string | null>(null);

  useEffect(() => {
    setCurrentDirectoryPath(null);
    setSelectedFilePath(null);
    setSelectedPaths([]);
    setWorkspaceView("browser");
    setBrowserMode("projects");
    setDirectoryEntriesByPath({});
    setProjectPickerOpen(false);
    setProjectPickerPurpose("register_project");
    setWorktreeSourceProjectPath(null);
    setWorktreeStartingRef(null);
    setAttachWorktreeProjectError(null);
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
  const projectBrowserManifestQuery =
    trpc.chat.getSessionProjectBrowserManifest.useQuery({
      agentId,
      sessionId,
    });
  const registrationRequestsQuery =
    trpc.chat.listAgentProjectRegistrationRequests.useQuery({
      agentId,
      sessionId,
    });
  const gitRefsQuery = trpc.chat.previewAgentGitRefs.useQuery(
    { agentId, sourceProjectPath: worktreeSourceProjectPath ?? "" },
    { enabled: worktreeSourceProjectPath !== null },
  );

  useEffect(() => {
    if (!gitRefsQuery.data) {
      return;
    }
    const refs = gitRefsQuery.data.refs;
    if (
      worktreeStartingRef &&
      refs.some((ref) => ref.ref === worktreeStartingRef)
    ) {
      return;
    }
    setWorktreeStartingRef(
      refs.find((ref) => ref.default)?.ref ?? refs.at(0)?.ref ?? null,
    );
  }, [gitRefsQuery.data, worktreeStartingRef]);

  const manifest = useMemo(() => {
    if (workspaceQuery.data?.workspace.type !== "READY") {
      return null;
    }
    return mapWorkspaceManifest(workspaceQuery.data.workspace.manifest);
  }, [workspaceQuery.data]);

  const projectBrowserManifest = useMemo(() => {
    if (!projectBrowserManifestQuery.data) {
      return null;
    }
    return mapProjectBrowserManifest(projectBrowserManifestQuery.data);
  }, [projectBrowserManifestQuery.data]);

  const projectBrowserRoot =
    projectBrowserManifest?.root ?? manifest?.root ?? "";
  const activeDirectoryPath =
    currentDirectoryPath ??
    (browserMode === "projects" ? projectBrowserRoot : (manifest?.cwd ?? ""));

  useEffect(() => {
    if (!manifest) {
      return;
    }
    setDirectoryEntriesByPath((previous) => ({
      ...previous,
      [manifest.cwd]: manifest.entries,
    }));
  }, [manifest]);

  useEffect(() => {
    if (!projectBrowserManifest) {
      return;
    }
    setDirectoryEntriesByPath((previous) => ({
      ...previous,
      [projectBrowserManifest.root]: projectBrowserManifest.entries,
    }));
  }, [projectBrowserManifest]);

  const directoryQuery = trpc.chat.readAgentWorkspacePath.useQuery(
    { agentId, sessionId, path: activeDirectoryPath },
    {
      enabled:
        workspaceQuery.data?.workspace.type === "READY" &&
        activeDirectoryPath !== "" &&
        !(
          browserMode === "projects" &&
          activeDirectoryPath === projectBrowserRoot
        ),
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
      await Promise.all([
        utils.chat.listAgentProjects.invalidate({ agentId, sessionId }),
        utils.chat.getSessionProjectBrowserManifest.invalidate({
          agentId,
          sessionId,
        }),
      ]);
    },
    onError: (error) => setRegisterProjectError(error.message),
  });

  const attachWorktreeMutation = trpc.chat.attachSessionGitWorktree.useMutation(
    {
      onSuccess: async () => {
        setWorktreeSourceProjectPath(null);
        setWorktreeStartingRef(null);
        setAttachWorktreeProjectError(null);
        await Promise.all([
          utils.chat.listAgentProjects.invalidate({ agentId, sessionId }),
          utils.chat.getSessionProjectBrowserManifest.invalidate({
            agentId,
            sessionId,
          }),
          utils.chat.getSessionInitialization.invalidate({ sessionId }),
        ]);
      },
      onError: (error) => setAttachWorktreeProjectError(error.message),
    },
  );

  const approveRegistrationRequestMutation =
    trpc.chat.approveAgentProjectRegistrationRequest.useMutation({
      onSuccess: async () => {
        setPendingApproveRequestId(null);
        await Promise.all([
          utils.chat.listAgentProjects.invalidate({ agentId, sessionId }),
          utils.chat.getSessionProjectBrowserManifest.invalidate({
            agentId,
            sessionId,
          }),
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
      await Promise.all([
        utils.chat.listAgentProjects.invalidate({ agentId, sessionId }),
        utils.chat.getSessionProjectBrowserManifest.invalidate({
          agentId,
          sessionId,
        }),
      ]);
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
      utils.chat.getSessionProjectBrowserManifest.invalidate({
        agentId,
        sessionId,
      }),
      utils.chat.listAgentProjectRegistrationRequests.invalidate({
        agentId,
        sessionId,
      }),
    ]).finally(() => setIsManualRefreshing(false));
  }, [
    agentId,
    sessionId,
    utils.chat.getAgentWorkspace,
    utils.chat.getSessionProjectBrowserManifest,
    utils.chat.listAgentProjectRegistrationRequests,
    utils.chat.listAgentProjects,
    utils.chat.readAgentWorkspacePath,
  ]);

  useEffect(() => {
    if (!autoRefreshVisible) {
      autoRefreshKeyRef.current = null;
      return;
    }
    if (workspaceQuery.data?.workspace.type !== "READY") {
      return;
    }
    const autoRefreshKey = `${agentId}:${sessionId}`;
    if (autoRefreshKeyRef.current === autoRefreshKey) {
      return;
    }
    autoRefreshKeyRef.current = autoRefreshKey;
    onRefresh();
  }, [
    agentId,
    autoRefreshVisible,
    onRefresh,
    sessionId,
    workspaceQuery.data?.workspace.type,
  ]);

  const getDownloadHref = useCallback(
    (path: string): string =>
      `/api/chat/agents/${encodeURIComponent(agentId)}/workspace/download?path=${encodeURIComponent(path)}`,
    [agentId],
  );

  const onRegisterProject = useCallback(
    (path: string) => {
      setRegisterProjectError(null);
      registerProjectMutation.mutate({
        agentId,
        sessionId,
        path,
      });
    },
    [agentId, registerProjectMutation, sessionId],
  );

  const onOpenProjectPicker = useCallback((): void => {
    setProjectPickerPurpose("register_project");
    setProjectPickerOpen(true);
  }, []);

  const onOpenWorktreeSourcePicker = useCallback((): void => {
    setProjectPickerPurpose("worktree_source");
    setProjectPickerOpen(true);
  }, []);

  const onAttachWorktreeProject = useCallback((): void => {
    if (worktreeSourceProjectPath === null || worktreeStartingRef === null) {
      return;
    }
    setAttachWorktreeProjectError(null);
    attachWorktreeMutation.mutate({
      agentId,
      sessionId,
      sourceProjectPath: worktreeSourceProjectPath,
      startingRef: worktreeStartingRef,
    });
  }, [
    agentId,
    attachWorktreeMutation,
    sessionId,
    worktreeSourceProjectPath,
    worktreeStartingRef,
  ]);

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

  const onRemoveProjectEntry = useCallback(
    (entry: WorkspaceEntry) => {
      const projectId =
        entry.source?.type === "session_project"
          ? entry.source.projectId
          : null;
      if (!projectId || entry.capabilities?.removeProject !== true) {
        return;
      }
      onDeleteProject(projectId);
    },
    [onDeleteProject],
  );

  const onSetBrowserMode = useCallback((mode: WorkspaceBrowserMode) => {
    setBrowserMode(mode);
    setCurrentDirectoryPath(null);
    setSelectedFilePath(null);
    setSelectedPaths([]);
    setWorkspaceView("browser");
  }, []);

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

  const projectPickerState = useMemo<ProjectDirectoryPickerState>(() => {
    if (!projectPickerOpen) {
      return { type: "CLOSED" };
    }
    if (workspaceQuery.isLoading || projectBrowserManifestQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (workspaceQuery.isError) {
      return { type: "ERROR", message: getErrorMessage(workspaceQuery.error) };
    }
    if (!workspaceQuery.data) {
      return { type: "LOADING" };
    }
    const directoryResult = directoryQuery.data;
    const entries =
      directoryResult?.type === "DIRECTORY"
        ? directoryResult.entries
        : (manifest?.entries ?? []);
    return {
      type: "SERVER",
      server: workspaceQuery.data,
      currentPath: activeDirectoryPath,
      entries,
      isRefreshing: workspaceQuery.isFetching || directoryQuery.isFetching,
      isStarting: startRuntimeMutation.isPending,
    };
  }, [
    activeDirectoryPath,
    directoryQuery.data,
    directoryQuery.isFetching,
    manifest?.entries,
    projectBrowserManifestQuery.isLoading,
    projectPickerOpen,
    startRuntimeMutation.isPending,
    workspaceQuery.data,
    workspaceQuery.error,
    workspaceQuery.isError,
    workspaceQuery.isFetching,
    workspaceQuery.isLoading,
  ]);

  const state = useMemo<WorkspacePanelState>(() => {
    if (workspaceQuery.isLoading || projectBrowserManifestQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (workspaceQuery.isError) {
      return { type: "ERROR", message: getErrorMessage(workspaceQuery.error) };
    }
    if (projectBrowserManifestQuery.isError) {
      return {
        type: "ERROR",
        message: getErrorMessage(projectBrowserManifestQuery.error),
      };
    }
    if (!workspaceQuery.data) {
      return { type: "LOADING" };
    }

    const browserManifest =
      browserMode === "projects" && projectBrowserManifest
        ? {
            root: projectBrowserManifest.root,
            cwd: projectBrowserManifest.root,
            entries: projectBrowserManifest.entries,
          }
        : manifest;

    const mappedDirectory = directoryQuery.data
      ? mapWorkspacePathResult(directoryQuery.data)
      : null;
    const directory =
      browserManifest && mappedDirectory?.type === "DIRECTORY"
        ? { path: mappedDirectory.path, entries: mappedDirectory.entries }
        : {
            path: activeDirectoryPath || browserManifest?.cwd || "",
            entries: browserManifest?.entries ?? [],
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
      manifest: browserManifest,
      projectBrowserManifest,
      browserMode,
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
      projectEmptyState:
        browserMode === "projects"
          ? (projectBrowserManifest?.emptyState ?? null)
          : null,
    };
  }, [
    activeDirectoryPath,
    browserMode,
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
    projectBrowserManifest,
    projectBrowserManifestQuery.error,
    projectBrowserManifestQuery.isError,
    projectBrowserManifestQuery.isLoading,
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
    projectPickerState,
    isProjectPickerOpen: projectPickerOpen,
    onOpenProjectPicker,
    onCloseProjectPicker: () => setProjectPickerOpen(false),
    onOpenProjectPickerDirectory: setCurrentDirectoryPath,
    onSelectProjectPickerDirectory: (path: string) => {
      if (projectPickerPurpose === "worktree_source") {
        setWorktreeSourceProjectPath(path);
        setWorktreeStartingRef(null);
        setAttachWorktreeProjectError(null);
      } else {
        onRegisterProject(path);
      }
      setProjectPickerOpen(false);
    },
    onRefreshProjectPicker: onRefresh,
    worktreeSourceProjectPath,
    worktreeStartingRef,
    worktreeRefOptions:
      gitRefsQuery.data?.refs.map((ref) => ({
        value: ref.ref,
        label: ref.default ? `${ref.name} (default)` : ref.name,
      })) ?? [],
    isLoadingWorktreeRefs: gitRefsQuery.isLoading,
    worktreeRefError: gitRefsQuery.isError
      ? getErrorMessage(gitRefsQuery.error)
      : null,
    isAttachingWorktreeProject: attachWorktreeMutation.isPending,
    attachWorktreeProjectError,
    onOpenWorktreeSourcePicker,
    onSetWorktreeStartingRef: setWorktreeStartingRef,
    onAttachWorktreeProject,
    onCancelWorktreeProjectAttach: () => {
      setWorktreeSourceProjectPath(null);
      setWorktreeStartingRef(null);
      setAttachWorktreeProjectError(null);
    },
    onStartRuntimeForProjectPicker: onStartRuntime,
    onApproveRegistrationRequest,
    onRejectRegistrationRequest,
    onDeleteProject,
    onRemoveProjectEntry,
    onSetBrowserMode,
  };
}
