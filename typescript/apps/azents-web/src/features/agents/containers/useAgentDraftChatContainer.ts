"use client";

/**
 * Agent draft chat container.
 *
 * Owns the pre-session first-message write and canonical URL replacement.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import type { UploadedFile } from "@/features/chat/hooks/useFileUpload";
import type { ProjectDirectoryPickerState } from "@/features/chat/workspace/components/WorkspaceDirectoryPickerModal";
import type {
  AgentProjectPresetResponse,
  AgentResponse,
} from "@azents/public-client";

const WORKSPACE_TRANSITION_REFETCH_INTERVAL_MS = 2_000;

export interface AgentDraftChatContainerProps {
  handle: string;
  agent: AgentResponse;
}

export type ProjectPresetState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "READY"; presets: AgentProjectPresetResponse[] };

export interface AgentDraftChatContainerOutput {
  handle: string;
  agent: AgentResponse;
  isWritePending: boolean;
  selectedProjectPaths: string[];
  projectPresetState: ProjectPresetState;
  projectPickerState: ProjectDirectoryPickerState;
  isProjectPickerOpen: boolean;
  onAddPresetProject: (path: string) => void;
  onRemoveProject: (path: string) => void;
  onOpenProjectPicker: () => void;
  onCloseProjectPicker: () => void;
  onOpenProjectPickerDirectory: (path: string) => void;
  onSelectProjectPickerDirectory: (path: string) => void;
  onRefreshProjectPicker: () => void;
  onStartRuntimeForProjectPicker: () => void;
  onSendMessage: (
    message: string,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
}

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

export function useAgentDraftChatContainer(
  props: AgentDraftChatContainerProps,
): AgentDraftChatContainerOutput {
  const { handle, agent } = props;
  const router = useRouter();
  const utils = trpc.useUtils();
  const createMessageMutation =
    trpc.chat.createTeamAgentSessionMessage.useMutation();
  const [writeInFlight, setWriteInFlight] = useState(false);
  const [selectedProjectPaths, setSelectedProjectPaths] = useState<string[]>(
    [],
  );
  const [projectPickerOpen, setProjectPickerOpen] = useState(false);
  const [projectPickerPath, setProjectPickerPath] = useState<string | null>(
    null,
  );
  const defaultsAppliedRef = useRef(false);

  const projectPresetsQuery = trpc.chat.listAgentProjectPresets.useQuery({
    agentId: agent.id,
  });
  const projectDefaultsQuery =
    trpc.chat.getAgentSessionProjectDefaults.useQuery({
      agentId: agent.id,
    });

  useEffect(() => {
    defaultsAppliedRef.current = false;
    setSelectedProjectPaths([]);
    setProjectPickerPath(null);
  }, [agent.id]);

  useEffect(() => {
    if (defaultsAppliedRef.current || !projectDefaultsQuery.data) {
      return;
    }
    defaultsAppliedRef.current = true;
    setSelectedProjectPaths(
      dedupePaths(projectDefaultsQuery.data.project_paths),
    );
  }, [projectDefaultsQuery.data]);

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
    setSelectedProjectPaths((previous) => dedupePaths([...previous, path]));
  }, []);

  const onRemoveProject = useCallback((path: string): void => {
    defaultsAppliedRef.current = true;
    setSelectedProjectPaths((previous) =>
      previous.filter((selectedPath) => selectedPath !== path),
    );
  }, []);

  const onSendMessage = useCallback(
    async (message: string, attachments?: UploadedFile[]): Promise<boolean> => {
      if (writeInFlight) {
        return false;
      }
      const attachmentUris = attachments?.map((attachment) => attachment.uri);
      setWriteInFlight(true);
      try {
        const response = await createMessageMutation.mutateAsync({
          agentId: agent.id,
          clientRequestId: crypto.randomUUID(),
          message,
          attachments: attachmentUris,
          projectPaths: selectedProjectPaths,
        });
        await Promise.all([
          utils.chat.listAgentSessions.invalidate({ agentId: agent.id }),
          utils.chat.listAgentProjectPresets.invalidate({ agentId: agent.id }),
        ]);
        router.replace(
          `/w/${handle}/agents/${agent.id}/sessions/${response.session_id}`,
        );
        return true;
      } catch {
        return false;
      } finally {
        setWriteInFlight(false);
      }
    },
    [
      agent.id,
      createMessageMutation,
      handle,
      router,
      selectedProjectPaths,
      utils.chat.listAgentProjectPresets,
      utils.chat.listAgentSessions,
      writeInFlight,
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
        ? directoryResult.entries
        : (manifest?.entries ?? []);
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
    isWritePending: createMessageMutation.isPending || writeInFlight,
    selectedProjectPaths,
    projectPresetState,
    projectPickerState,
    isProjectPickerOpen: projectPickerOpen,
    onAddPresetProject,
    onRemoveProject,
    onOpenProjectPicker: () => setProjectPickerOpen(true),
    onCloseProjectPicker: () => setProjectPickerOpen(false),
    onOpenProjectPickerDirectory: setProjectPickerPath,
    onSelectProjectPickerDirectory: (path: string) => {
      onAddPresetProject(path);
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
