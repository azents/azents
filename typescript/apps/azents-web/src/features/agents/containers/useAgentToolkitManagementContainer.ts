"use client";

import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  type AgentToolkitEditorState,
  type AgentToolkitManagementState,
  type AgentToolkitMutationState,
  projectAgentToolkitManagementState,
} from "../agentToolkitManagementState";
import type { AgentToolkitManagementItemResponse } from "@azents/public-client";

export interface AgentToolkitManagementContainerProps {
  handle: string;
  agentId: string;
}

export interface AgentToolkitManagementContainerOutput extends AgentToolkitManagementContainerProps {
  state: AgentToolkitManagementState;
  editor: AgentToolkitEditorState;
  mutationState: AgentToolkitMutationState;
  selectedToolkitId: string | null;
  deleteTarget: AgentToolkitManagementItemResponse | null;
  pending: boolean;
  attachPending: boolean;
  deletePending: boolean;
  onSelectedToolkitChange: (toolkitId: string | null) => void;
  onStartAdd: () => void;
  onToolkitTypeChange: (toolkitType: string | null) => void;
  onConfigureSelectedType: () => void;
  onEdit: (toolkitConfigId: string) => void;
  onCloseEditor: () => void;
  onAttach: () => void;
  onDetach: (agentToolkitId: string) => void;
  onToggle: (item: AgentToolkitManagementItemResponse) => void;
  onRequestDelete: (item: AgentToolkitManagementItemResponse) => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}

export function useAgentToolkitManagementContainer({
  handle,
  agentId,
}: AgentToolkitManagementContainerProps): AgentToolkitManagementContainerOutput {
  const utils = trpc.useUtils();
  const [selectedToolkitId, setSelectedToolkitId] = useState<string | null>(
    null,
  );
  const [editor, setEditor] = useState<AgentToolkitEditorState>({
    type: "CLOSED",
  });
  const [mutationState, setMutationState] = useState<AgentToolkitMutationState>(
    { type: "IDLE" },
  );
  const [deleteTarget, setDeleteTarget] =
    useState<AgentToolkitManagementItemResponse | null>(null);
  const query = trpc.toolkit.listAgentManagement.useQuery({ handle, agentId });
  const definitionsQuery = trpc.toolkit.listToolkits.useQuery();
  const invalidate = useCallback(async (): Promise<void> => {
    await utils.toolkit.listAgentManagement.invalidate({ handle, agentId });
  }, [agentId, handle, utils.toolkit.listAgentManagement]);
  const attachMutation = trpc.toolkit.attachToAgent.useMutation({
    onSuccess: async () => {
      setMutationState({ type: "IDLE" });
      setSelectedToolkitId(null);
      await invalidate();
      setEditor({ type: "CLOSED" });
    },
    onError: (error) =>
      setMutationState({ type: "ERROR", message: error.message }),
  });
  const detachMutation = trpc.toolkit.detachFromAgent.useMutation({
    onSuccess: async () => {
      setMutationState({ type: "IDLE" });
      await invalidate();
    },
    onError: (error) =>
      setMutationState({ type: "ERROR", message: error.message }),
  });
  const updateMutation = trpc.toolkit.updateAgentConfig.useMutation({
    onSuccess: async () => {
      setMutationState({ type: "IDLE" });
      await invalidate();
    },
    onError: (error) =>
      setMutationState({ type: "ERROR", message: error.message }),
  });
  const deleteMutation = trpc.toolkit.removeAgentConfig.useMutation({
    onSuccess: async () => {
      setMutationState({ type: "IDLE" });
      setDeleteTarget(null);
      await invalidate();
    },
    onError: (error) =>
      setMutationState({ type: "ERROR", message: error.message }),
  });
  const state = useMemo(
    () =>
      projectAgentToolkitManagementState({
        loading: query.isLoading || definitionsQuery.isLoading,
        error: query.isError
          ? query.error.message
          : definitionsQuery.isError
            ? definitionsQuery.error.message
            : null,
        data: query.data,
        toolkitDefinitions: definitionsQuery.data?.items,
      }),
    [
      definitionsQuery.data,
      definitionsQuery.error,
      definitionsQuery.isError,
      definitionsQuery.isLoading,
      query.data,
      query.error,
      query.isError,
      query.isLoading,
    ],
  );
  const closeEditor = useCallback((): void => {
    setEditor({ type: "CLOSED" });
    void invalidate();
  }, [invalidate]);

  return {
    handle,
    agentId,
    state,
    editor,
    mutationState,
    selectedToolkitId,
    deleteTarget,
    pending:
      detachMutation.isPending ||
      updateMutation.isPending ||
      deleteMutation.isPending,
    attachPending: attachMutation.isPending,
    deletePending: deleteMutation.isPending,
    onSelectedToolkitChange: setSelectedToolkitId,
    onStartAdd: () => {
      setMutationState({ type: "IDLE" });
      setEditor({ type: "SELECT_TYPE", toolkitType: null });
    },
    onToolkitTypeChange: (toolkitType) => {
      setMutationState({ type: "IDLE" });
      setSelectedToolkitId(null);
      setEditor({ type: "SELECT_TYPE", toolkitType });
    },
    onConfigureSelectedType: () => {
      if (editor.type === "SELECT_TYPE" && editor.toolkitType != null) {
        setEditor({ type: "CREATE", toolkitType: editor.toolkitType });
      }
    },
    onEdit: (toolkitConfigId) => setEditor({ type: "EDIT", toolkitConfigId }),
    onCloseEditor: closeEditor,
    onAttach: () => {
      if (selectedToolkitId) {
        setMutationState({ type: "IDLE" });
        attachMutation.mutate({
          handle,
          agentId,
          toolkitId: selectedToolkitId,
        });
      }
    },
    onDetach: (agentToolkitId) => {
      setMutationState({ type: "IDLE" });
      detachMutation.mutate({ handle, agentId, agentToolkitId });
    },
    onToggle: (item) => {
      setMutationState({ type: "IDLE" });
      updateMutation.mutate({
        handle,
        agentId,
        toolkitConfigId: item.toolkit.id,
        enabled: !item.toolkit.enabled,
      });
    },
    onRequestDelete: (item) => {
      setMutationState({ type: "IDLE" });
      setDeleteTarget(item);
    },
    onCancelDelete: () => setDeleteTarget(null),
    onConfirmDelete: () => {
      if (deleteTarget) {
        setMutationState({ type: "IDLE" });
        deleteMutation.mutate({
          handle,
          agentId,
          toolkitConfigId: deleteTarget.toolkit.id,
        });
      }
    },
  };
}
