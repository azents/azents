"use client";

/**
 * Agent draft chat container.
 *
 * Owns the pre-session first-message write and canonical URL replacement.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { withRequestDeadline } from "@/features/chat/hooks/requestDeadline";
import { trpc } from "@/trpc/client";
import {
  clientRequestIdForDraftSessionWrite,
  draftSessionWriteKey,
  type FailedDraftSessionWriteRequest,
} from "./draftSessionWriteRequest";
import type { UploadedFile } from "@/features/chat/hooks/useFileUpload";
import type {
  ProjectDirectoryPickerEntry,
  ProjectDirectoryPickerState,
} from "@/features/chat/workspace/components/WorkspaceDirectoryPickerModal";
import type {
  AgentProjectPresetResponse,
  AgentResponse,
  GitRefEntryResponse,
  RequestedInferenceProfile,
} from "@azents/public-client";

const WORKSPACE_TRANSITION_REFETCH_INTERVAL_MS = 2_000;
const CHAT_WRITE_REQUEST_TIMEOUT_MS = 15_000;
const SESSION_NAVIGATION_FALLBACK_MS = 5_000;

export interface AgentDraftChatContainerProps {
  handle: string;
  agent: AgentResponse;
}

export type ProjectPresetState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "READY"; presets: AgentProjectPresetResponse[] };

export type NewSessionWorkspaceItemState =
  | { id: string; type: "existing_project"; path: string }
  | {
      id: string;
      type: "git_worktree";
      sourceProjectPath: string;
      startingRef: string | null;
    };

export type NewSessionWorkspaceItemKind = NewSessionWorkspaceItemState["type"];

export type ProjectPickerPurpose = "existing_project" | "git_worktree";

export type GitRefPreviewState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "READY"; refs: GitRefEntryResponse[] };

export interface AgentDraftChatContainerOutput {
  handle: string;
  agent: AgentResponse;
  isWritePending: boolean;
  canSendMessage: boolean;
  selectedProjectPaths: string[];
  workspaceItems: NewSessionWorkspaceItemState[];
  activeWorktreeItemId: string | null;
  gitRefPreviewState: GitRefPreviewState;
  projectPresetState: ProjectPresetState;
  projectPickerState: ProjectDirectoryPickerState;
  isProjectPickerOpen: boolean;
  onAddPresetProject: (path: string) => void;
  onAddWorktreeProject: (path: string) => void;
  onSetWorkspaceItemKind: (
    itemId: string,
    kind: NewSessionWorkspaceItemKind,
  ) => void;
  onActivateWorktreeItem: (itemId: string) => void;
  onSetWorktreeStartingRef: (itemId: string, ref: string | null) => void;
  onRemoveWorkspaceItem: (itemId: string) => void;
  onOpenProjectPicker: (purpose: ProjectPickerPurpose) => void;
  onCloseProjectPicker: () => void;
  onOpenProjectPickerDirectory: (path: string) => void;
  onSelectProjectPickerDirectory: (entry: ProjectDirectoryPickerEntry) => void;
  onRefreshProjectPicker: () => void;
  onStartRuntimeForProjectPicker: () => void;
  onSendMessage: (
    message: string,
    inferenceProfile: RequestedInferenceProfile,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
}

type DefaultWorkspaceItemResponse =
  | { type?: "existing_project"; path: string }
  | {
      type?: "git_worktree";
      source_project_path: string;
      starting_ref?: string | null;
    };

type DefaultWorkspaceResponse = {
  project_paths: string[];
  items?: DefaultWorkspaceItemResponse[];
};

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed.";
}

function normalizeProjectPath(path: string): string {
  return path.replace(/\/+$/, "");
}

function dedupePaths(paths: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const path of paths) {
    const normalized = normalizeProjectPath(path);
    if (normalized === "" || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function makeItemId(prefix: string, path: string): string {
  return `${prefix}:${normalizeProjectPath(path)}:${crypto.randomUUID()}`;
}

function makeExistingProjectItem(path: string): NewSessionWorkspaceItemState {
  const normalizedPath = normalizeProjectPath(path);
  return {
    id: makeItemId("existing_project", normalizedPath),
    type: "existing_project",
    path: normalizedPath,
  };
}

function makeGitWorktreeItem(path: string): NewSessionWorkspaceItemState {
  const normalizedPath = normalizeProjectPath(path);
  return {
    id: makeItemId("git_worktree", normalizedPath),
    type: "git_worktree",
    sourceProjectPath: normalizedPath,
    startingRef: null,
  };
}

function isGitWorktreeWorkspaceItem(
  item: NewSessionWorkspaceItemState,
): item is Extract<NewSessionWorkspaceItemState, { type: "git_worktree" }> {
  return item.type === "git_worktree";
}

function localBranchRefs(refs: GitRefEntryResponse[]): GitRefEntryResponse[] {
  return refs.filter((ref) => ref.type === "branch");
}

function defaultStartingRef(refs: GitRefEntryResponse[]): string | null {
  return refs.find((ref) => ref.default)?.ref ?? refs.at(0)?.ref ?? null;
}

function workspaceItemsFromDefaults(
  defaults: DefaultWorkspaceResponse,
): NewSessionWorkspaceItemState[] {
  const defaultItems = defaults.items;
  if (defaultItems) {
    return defaultItems.map((item, index) => {
      if ("source_project_path" in item) {
        return {
          id: `default-git-worktree:${index}:${item.source_project_path}`,
          type: "git_worktree",
          sourceProjectPath: normalizeProjectPath(item.source_project_path),
          startingRef: item.starting_ref ?? null,
        };
      }
      return {
        id: `default-existing-project:${index}:${item.path}`,
        type: "existing_project",
        path: normalizeProjectPath(item.path),
      };
    });
  }
  return dedupePaths(defaults.project_paths).map((path, index) => ({
    id: `default-existing-project:${index}:${path}`,
    type: "existing_project",
    path,
  }));
}

function dedupeWorkspaceItems(
  items: NewSessionWorkspaceItemState[],
): NewSessionWorkspaceItemState[] {
  const seenExistingProjectPaths = new Set<string>();
  const seenWorktreeSourcePaths = new Set<string>();
  const result: NewSessionWorkspaceItemState[] = [];
  for (const item of items) {
    switch (item.type) {
      case "existing_project": {
        if (seenExistingProjectPaths.has(item.path)) {
          continue;
        }
        seenExistingProjectPaths.add(item.path);
        result.push(item);
        break;
      }
      case "git_worktree": {
        if (seenWorktreeSourcePaths.has(item.sourceProjectPath)) {
          continue;
        }
        seenWorktreeSourcePaths.add(item.sourceProjectPath);
        result.push(item);
        break;
      }
    }
  }
  return result;
}

type NewSessionSetupActionRequest = {
  type: "create_git_worktree";
  source_project_path: string;
  starting_ref: string;
};

function setupActionsFromWorkspaceItems(
  items: NewSessionWorkspaceItemState[],
): NewSessionSetupActionRequest[] {
  const actions: NewSessionSetupActionRequest[] = [];
  for (const item of items) {
    switch (item.type) {
      case "existing_project":
        break;
      case "git_worktree":
        actions.push({
          type: "create_git_worktree",
          source_project_path: item.sourceProjectPath,
          starting_ref: item.startingRef ?? "",
        });
        break;
    }
  }
  return actions;
}

export function useAgentDraftChatContainer(
  props: AgentDraftChatContainerProps,
): AgentDraftChatContainerOutput {
  const { handle, agent } = props;
  const router = useRouter();
  const utils = trpc.useUtils();
  const createMessageMutation =
    trpc.chat.createTeamAgentSessionMessage.useMutation();
  const [writeInFlight, setWriteInFlight] = useState(false);
  const writeInFlightRef = useRef(false);
  const failedCreateRequestRef = useRef<FailedDraftSessionWriteRequest | null>(
    null,
  );
  const currentAgentIdRef = useRef(agent.id);
  currentAgentIdRef.current = agent.id;
  const writeGenerationRef = useRef(0);
  const mountedRef = useRef(true);
  const navigationFallbackTimerRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null);
  const [workspaceItems, setWorkspaceItems] = useState<
    NewSessionWorkspaceItemState[]
  >([]);
  const [activeWorktreeItemId, setActiveWorktreeItemId] = useState<
    string | null
  >(null);
  const [projectPickerOpen, setProjectPickerOpen] = useState(false);
  const [projectPickerPurpose, setProjectPickerPurpose] =
    useState<ProjectPickerPurpose>("existing_project");
  const [projectPickerPath, setProjectPickerPath] = useState<string | null>(
    null,
  );
  const defaultsAppliedRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      writeGenerationRef.current += 1;
      if (navigationFallbackTimerRef.current !== null) {
        clearTimeout(navigationFallbackTimerRef.current);
        navigationFallbackTimerRef.current = null;
      }
    };
  }, []);

  const projectPresetsQuery = trpc.chat.listAgentProjectPresets.useQuery({
    agentId: agent.id,
  });
  const projectDefaultsQuery =
    trpc.chat.getAgentSessionProjectDefaults.useQuery({
      agentId: agent.id,
    });

  useEffect(() => {
    writeGenerationRef.current += 1;
    writeInFlightRef.current = false;
    setWriteInFlight(false);
    if (navigationFallbackTimerRef.current !== null) {
      clearTimeout(navigationFallbackTimerRef.current);
      navigationFallbackTimerRef.current = null;
    }
    defaultsAppliedRef.current = false;
    failedCreateRequestRef.current = null;
    setWorkspaceItems([]);
    setActiveWorktreeItemId(null);
    setProjectPickerPath(null);
    setProjectPickerPurpose("existing_project");
  }, [agent.id]);

  useEffect(() => {
    if (defaultsAppliedRef.current || !projectDefaultsQuery.data) {
      return;
    }
    defaultsAppliedRef.current = true;
    const nextItems = dedupeWorkspaceItems(
      workspaceItemsFromDefaults(projectDefaultsQuery.data),
    );
    setWorkspaceItems(nextItems);
    setActiveWorktreeItemId(
      nextItems.find(isGitWorktreeWorkspaceItem)?.id ?? null,
    );
  }, [projectDefaultsQuery.data]);

  const worktreeItems = useMemo(
    () => workspaceItems.filter(isGitWorktreeWorkspaceItem),
    [workspaceItems],
  );
  const activeWorktreeItem =
    worktreeItems.find((item) => item.id === activeWorktreeItemId) ??
    worktreeItems.at(0) ??
    null;
  const activeSourceProjectPath = activeWorktreeItem?.sourceProjectPath ?? null;

  const gitRefsQuery = trpc.chat.previewAgentGitRefs.useQuery(
    { agentId: agent.id, sourceProjectPath: activeSourceProjectPath ?? "" },
    {
      enabled: activeSourceProjectPath !== null,
    },
  );

  useEffect(() => {
    if (!activeWorktreeItem || !gitRefsQuery.data) {
      return;
    }
    const refs = localBranchRefs(gitRefsQuery.data.refs);
    const currentRef = activeWorktreeItem.startingRef;
    if (currentRef && refs.some((ref) => ref.ref === currentRef)) {
      return;
    }
    const nextRef = defaultStartingRef(refs);
    if (currentRef === nextRef) {
      return;
    }
    setWorkspaceItems((previous) =>
      previous.map((item) =>
        item.id === activeWorktreeItem.id && item.type === "git_worktree"
          ? { ...item, startingRef: nextRef }
          : item,
      ),
    );
  }, [activeWorktreeItem, gitRefsQuery.data]);

  const workspaceQuery = trpc.chat.getAgentWorkspace.useQuery(
    { agentId: agent.id },
    {
      enabled: projectPickerOpen,
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
  const activeProjectPickerPath = projectPickerPath ?? manifest?.cwd ?? "";

  useEffect(() => {
    if (!projectPickerOpen || !manifest || projectPickerPath) {
      return;
    }
    setProjectPickerPath(manifest.cwd);
  }, [manifest, projectPickerOpen, projectPickerPath]);

  const directoryQuery = trpc.chat.readAgentWorkspacePath.useQuery(
    { agentId: agent.id, path: activeProjectPickerPath },
    {
      enabled:
        projectPickerOpen &&
        workspaceQuery.data?.workspace.type === "READY" &&
        activeProjectPickerPath !== "",
    },
  );

  const startRuntimeMutation = trpc.chat.startAgentRuntime.useMutation({
    onSuccess: async () => {
      await utils.chat.getAgentWorkspace.invalidate({ agentId: agent.id });
    },
  });

  const onAddPresetProject = useCallback((path: string): void => {
    defaultsAppliedRef.current = true;
    setWorkspaceItems((previous) =>
      dedupeWorkspaceItems([...previous, makeExistingProjectItem(path)]),
    );
  }, []);

  const onAddWorktreeProject = useCallback((path: string): void => {
    defaultsAppliedRef.current = true;
    const item = makeGitWorktreeItem(path);
    setWorkspaceItems((previous) => dedupeWorkspaceItems([...previous, item]));
    setActiveWorktreeItemId(item.id);
  }, []);

  const onSetWorkspaceItemKind = useCallback(
    (itemId: string, kind: NewSessionWorkspaceItemKind): void => {
      defaultsAppliedRef.current = true;
      setWorkspaceItems((previous) =>
        previous.map((item) => {
          if (item.id !== itemId) {
            return item;
          }
          if (kind === "existing_project") {
            if (item.type === "existing_project") {
              return item;
            }
            return {
              id: item.id,
              type: "existing_project",
              path: item.sourceProjectPath,
            };
          }
          if (item.type === "git_worktree") {
            return item;
          }
          return {
            id: item.id,
            type: "git_worktree",
            sourceProjectPath: item.path,
            startingRef: null,
          };
        }),
      );
      setActiveWorktreeItemId((current) => {
        if (kind === "git_worktree") {
          return itemId;
        }
        return current === itemId ? null : current;
      });
    },
    [],
  );

  const onActivateWorktreeItem = useCallback((itemId: string): void => {
    setActiveWorktreeItemId(itemId);
  }, []);

  const onSetWorktreeStartingRef = useCallback(
    (itemId: string, ref: string | null): void => {
      defaultsAppliedRef.current = true;
      setActiveWorktreeItemId(itemId);
      setWorkspaceItems((previous) =>
        previous.map((item) =>
          item.id === itemId && item.type === "git_worktree"
            ? { ...item, startingRef: ref }
            : item,
        ),
      );
    },
    [],
  );

  const onRemoveWorkspaceItem = useCallback((itemId: string): void => {
    defaultsAppliedRef.current = true;
    setWorkspaceItems((previous) =>
      previous.filter((item) => item.id !== itemId),
    );
    setActiveWorktreeItemId((current) => (current === itemId ? null : current));
  }, []);

  const selectedProjectPaths = useMemo(
    () =>
      workspaceItems
        .filter((item) => item.type === "existing_project")
        .map((item) => item.path),
    [workspaceItems],
  );

  const canSendMessage = workspaceItems.every(
    (item) =>
      item.type === "existing_project" ||
      (item.startingRef !== null && item.startingRef.trim() !== ""),
  );

  const onSendMessage = useCallback(
    async (
      message: string,
      inferenceProfile: RequestedInferenceProfile,
      attachments?: UploadedFile[],
    ): Promise<boolean> => {
      if (writeInFlightRef.current || !canSendMessage) {
        return false;
      }
      const attachmentUris = attachments?.map((attachment) => attachment.uri);
      const setupActions = setupActionsFromWorkspaceItems(workspaceItems);
      const writeKey = draftSessionWriteKey({
        agentId: agent.id,
        message,
        inferenceProfile,
        attachments: attachmentUris ?? [],
        existingProjectPaths: selectedProjectPaths,
        setupActions,
      });
      const clientRequestId = clientRequestIdForDraftSessionWrite(
        failedCreateRequestRef.current,
        writeKey,
        () => crypto.randomUUID(),
      );
      const requestAgentId = agent.id;
      const requestGeneration = writeGenerationRef.current + 1;
      writeGenerationRef.current = requestGeneration;
      const requestIsCurrent = (): boolean =>
        mountedRef.current &&
        currentAgentIdRef.current === requestAgentId &&
        writeGenerationRef.current === requestGeneration;
      let navigationStarted = false;
      writeInFlightRef.current = true;
      setWriteInFlight(true);
      try {
        const response = await withRequestDeadline(
          createMessageMutation.mutateAsync({
            agentId: agent.id,
            clientRequestId,
            message,
            inferenceProfile,
            attachments: attachmentUris,
            existingProjectPaths: selectedProjectPaths,
            setupActions,
          }),
          CHAT_WRITE_REQUEST_TIMEOUT_MS,
        );
        if (!requestIsCurrent()) {
          return false;
        }
        failedCreateRequestRef.current = null;
        const sessionPath = `/w/${handle}/agents/${agent.id}/sessions/${response.session_id}`;
        router.replace(sessionPath);
        navigationStarted = true;
        navigationFallbackTimerRef.current = setTimeout(() => {
          navigationFallbackTimerRef.current = null;
          if (requestIsCurrent()) {
            window.location.replace(sessionPath);
          }
        }, SESSION_NAVIGATION_FALLBACK_MS);
        void utils.chat.listAgentSessions.invalidate({ agentId: agent.id });
        void utils.chat.listAgentProjectPresets.invalidate({
          agentId: agent.id,
        });
        return true;
      } catch {
        if (requestIsCurrent()) {
          failedCreateRequestRef.current = {
            key: writeKey,
            id: clientRequestId,
          };
        }
        return false;
      } finally {
        if (!navigationStarted && requestIsCurrent()) {
          writeInFlightRef.current = false;
          setWriteInFlight(false);
        }
      }
    },
    [
      agent.id,
      canSendMessage,
      createMessageMutation,
      handle,
      router,
      utils.chat.listAgentProjectPresets,
      selectedProjectPaths,
      utils.chat.listAgentSessions,
      workspaceItems,
    ],
  );

  const projectPresetState = useMemo<ProjectPresetState>(() => {
    if (projectPresetsQuery.isLoading || projectDefaultsQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (projectPresetsQuery.isError) {
      return {
        type: "ERROR",
        message: getErrorMessage(projectPresetsQuery.error),
      };
    }
    if (projectDefaultsQuery.isError) {
      return {
        type: "ERROR",
        message: getErrorMessage(projectDefaultsQuery.error),
      };
    }
    return { type: "READY", presets: projectPresetsQuery.data?.items ?? [] };
  }, [
    projectDefaultsQuery.error,
    projectDefaultsQuery.isError,
    projectDefaultsQuery.isLoading,
    projectPresetsQuery.data?.items,
    projectPresetsQuery.error,
    projectPresetsQuery.isError,
    projectPresetsQuery.isLoading,
  ]);

  const gitRefPreviewState = useMemo<GitRefPreviewState>(() => {
    if (activeSourceProjectPath === null) {
      return { type: "IDLE" };
    }
    if (gitRefsQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (gitRefsQuery.isError) {
      return { type: "ERROR", message: getErrorMessage(gitRefsQuery.error) };
    }
    return {
      type: "READY",
      refs: localBranchRefs(gitRefsQuery.data?.refs ?? []),
    };
  }, [
    activeSourceProjectPath,
    gitRefsQuery.data?.refs,
    gitRefsQuery.error,
    gitRefsQuery.isError,
    gitRefsQuery.isLoading,
  ]);

  const projectPickerState = useMemo<ProjectDirectoryPickerState>(() => {
    if (!projectPickerOpen) {
      return { type: "CLOSED" };
    }
    if (workspaceQuery.isLoading) {
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
      currentPath: activeProjectPickerPath,
      entries,
      isRefreshing: workspaceQuery.isFetching || directoryQuery.isFetching,
      isStarting: startRuntimeMutation.isPending,
    };
  }, [
    activeProjectPickerPath,
    directoryQuery.data,
    directoryQuery.isFetching,
    manifest?.entries,
    projectPickerOpen,
    startRuntimeMutation.isPending,
    workspaceQuery.data,
    workspaceQuery.error,
    workspaceQuery.isError,
    workspaceQuery.isFetching,
    workspaceQuery.isLoading,
  ]);

  return {
    handle,
    agent,
    isWritePending: writeInFlight,
    canSendMessage,
    selectedProjectPaths,
    workspaceItems,
    activeWorktreeItemId: activeWorktreeItem?.id ?? null,
    gitRefPreviewState,
    projectPresetState,
    projectPickerState,
    isProjectPickerOpen: projectPickerOpen,
    onAddPresetProject,
    onAddWorktreeProject,
    onSetWorkspaceItemKind,
    onActivateWorktreeItem,
    onSetWorktreeStartingRef,
    onRemoveWorkspaceItem,
    onOpenProjectPicker: (purpose: ProjectPickerPurpose) => {
      setProjectPickerPurpose(purpose);
      setProjectPickerOpen(true);
    },
    onCloseProjectPicker: () => setProjectPickerOpen(false),
    onOpenProjectPickerDirectory: setProjectPickerPath,
    onSelectProjectPickerDirectory: (entry: ProjectDirectoryPickerEntry) => {
      if (projectPickerPurpose === "git_worktree") {
        onAddWorktreeProject(entry.path);
      } else {
        onAddPresetProject(entry.path);
      }
      setProjectPickerOpen(false);
    },
    onRefreshProjectPicker: () => {
      void Promise.all([
        utils.chat.getAgentWorkspace.invalidate({ agentId: agent.id }),
        utils.chat.readAgentWorkspacePath.invalidate({ agentId: agent.id }),
      ]);
    },
    onStartRuntimeForProjectPicker: () =>
      startRuntimeMutation.mutate({ handle, agentId: agent.id }),
    onSendMessage,
  };
}
