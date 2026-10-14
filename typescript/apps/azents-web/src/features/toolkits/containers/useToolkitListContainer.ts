"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { usesToolkitCreationWizard } from "@/shared/toolkits/toolkit-form-lifecycle";
import { trpc } from "@/trpc/client";
import {
  canToggleWorkspaceToolkit,
  completeWorkspaceToolkitSetup,
  workspaceToolkitEditorPending,
} from "../workspace-toolkit-management-state";
import type {
  WorkspaceToolkitEditor,
  WorkspaceToolkitWriteState,
} from "../workspace-toolkit-management-state";
import type {
  ToolkitConfigListState,
  ToolkitListState,
} from "@/shared/toolkits/types";
import type { ToolkitConfigResponse } from "@azents/public-client";

export interface ToolkitListContainerProps {
  handle: string;
}
export interface ToolkitListContainerOutput {
  handle: string;
  listState: ToolkitConfigListState;
  catalogState: ToolkitListState;
  editor: WorkspaceToolkitEditor;
  writeState: WorkspaceToolkitWriteState;
  pending: boolean;
  setupPending: boolean;
  createPublicationPending: boolean;
  refreshFailed: boolean;
  onStartAdd: () => void;
  onConfigureType: (toolkitType: string) => void;
  onDetails: (toolkitId: string) => void;
  onEdit: (toolkitId: string) => void;
  onCloseEditor: () => void;
  onBack: () => void;
  onRetryRead: () => void;
  onSetupPendingChange: (pending: boolean) => void;
  onCreatePublicationPendingChange: (pending: boolean) => void;
  onCreateAbandonReady: (abandon: (() => void) | null) => void;
  onCompleteSetup: () => void;
  onDelete: (toolkitId: string) => void;
  deleteTarget: string | null;
  deleteState:
    { type: "IDLE" } | { type: "PENDING" } | { type: "ERROR"; message: string };
  onConfirmDelete: () => void;
  onCancelDelete: () => void;
  onToggleEnabled: (toolkit: ToolkitConfigResponse, enabled: boolean) => void;
}

export function useToolkitListContainer({
  handle,
}: ToolkitListContainerProps): ToolkitListContainerOutput {
  const utils = trpc.useUtils();
  const [editor, setEditor] = useState<WorkspaceToolkitEditor>({
    type: "CLOSED",
  });
  const activeEditor = useRef(editor);
  const [writeState, setWriteState] = useState<WorkspaceToolkitWriteState>({
    type: "IDLE",
  });
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleteState, setDeleteState] = useState<
    ToolkitListContainerOutput["deleteState"]
  >({ type: "IDLE" });
  const [setupPending, setSetupPending] = useState(false);
  const [createPublicationPending, setCreatePublicationPending] =
    useState(false);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const abandonCreate = useRef<(() => void) | null>(null);
  const writeInFlight = useRef(false);
  const listQuery = trpc.toolkit.listConfigs.useQuery({ handle });
  const catalogQuery = trpc.toolkit.listToolkits.useQuery();
  const listState: ToolkitConfigListState = useMemo(
    () =>
      listQuery.isLoading
        ? { type: "LOADING" }
        : listQuery.isError
          ? { type: "ERROR" }
          : { type: "READY", configs: listQuery.data?.items ?? [] },
    [listQuery.data, listQuery.isError, listQuery.isLoading],
  );
  const catalogState: ToolkitListState = useMemo(
    () =>
      catalogQuery.isLoading
        ? { type: "LOADING" }
        : catalogQuery.isError
          ? { type: "ERROR" }
          : { type: "READY", toolkits: catalogQuery.data?.items ?? [] },
    [catalogQuery.data, catalogQuery.isError, catalogQuery.isLoading],
  );
  const refresh = useCallback(async (): Promise<void> => {
    const results = await Promise.allSettled([
      utils.toolkit.listConfigs.invalidate({ handle }),
      utils.toolkit.getConfig.invalidate(),
      utils.toolkit.listAgentManagement.invalidate(),
      utils.toolkit.githubUser.status.invalidate(),
      utils.toolkit.githubUser.access.invalidate(),
      utils.toolkit.githubUser.review.invalidate(),
    ]);
    setRefreshFailed(results.some((result) => result.status === "rejected"));
  }, [handle, utils]);
  const removeMutation = trpc.toolkit.removeConfig.useMutation({
    onSuccess: () => {
      changeEditor({ type: "CLOSED" });
      setDeleteTarget(null);
      setDeleteState({ type: "IDLE" });
    },
    onError: (error) =>
      setDeleteState({ type: "ERROR", message: error.message }),
    onSettled: async () => {
      await refresh();
      writeInFlight.current = false;
    },
  });
  const updateMutation = trpc.toolkit.updateConfig.useMutation({
    onSuccess: () => setWriteState({ type: "IDLE" }),
    onError: (error, variables) =>
      setWriteState({
        type: "ERROR",
        toolkitId: variables.toolkitId,
        message: error.message,
      }),
    onSettled: async () => {
      await refresh();
      writeInFlight.current = false;
    },
  });
  const pending = removeMutation.isPending || updateMutation.isPending;
  const formPending = workspaceToolkitEditorPending(
    editor,
    setupPending,
    createPublicationPending,
  );
  const canNavigate = !pending && !formPending && deleteTarget == null;
  const onSetupPendingChange = useCallback(
    (value: boolean): void => {
      if (activeEditor.current === editor) {
        setSetupPending(value);
      }
    },
    [editor],
  );
  const onCreatePublicationPendingChange = useCallback(
    (value: boolean): void => {
      if (activeEditor.current === editor) {
        setCreatePublicationPending(value);
      }
    },
    [editor],
  );
  const onCreateAbandonReady = useCallback(
    (callback: (() => void) | null): void => {
      if (activeEditor.current === editor) {
        abandonCreate.current = callback;
      }
    },
    [editor],
  );
  function changeEditor(next: WorkspaceToolkitEditor): void {
    activeEditor.current = next;
    setEditor(next);
  }
  function abandon(): void {
    if (
      editor.type === "CREATE" &&
      usesToolkitCreationWizard(editor.toolkitType)
    ) {
      abandonCreate.current?.();
    }
    abandonCreate.current = null;
    setSetupPending(false);
    setCreatePublicationPending(false);
  }
  function open(next: WorkspaceToolkitEditor): void {
    if (!canNavigate || writeInFlight.current) {
      return;
    }
    abandon();
    setWriteState({ type: "IDLE" });
    changeEditor(next);
  }
  return {
    handle,
    listState,
    catalogState,
    editor,
    writeState,
    pending,
    setupPending,
    createPublicationPending,
    refreshFailed,
    deleteTarget,
    deleteState,
    onStartAdd: () => open({ type: "CATALOG" }),
    onConfigureType: (toolkitType) => {
      if (
        catalogState.type === "READY" &&
        catalogState.toolkits.some((type) => type.slug === toolkitType)
      ) {
        open({ type: "CREATE", toolkitType });
      }
    },
    onDetails: (toolkitId) => open({ type: "DETAIL", toolkitId }),
    onEdit: (toolkitId) => open({ type: "EDIT", toolkitId }),
    onCloseEditor: () => {
      if (canNavigate && !writeInFlight.current) {
        abandon();
        changeEditor({ type: "CLOSED" });
        void refresh();
      }
    },
    onBack: () =>
      open(
        editor.type === "EDIT"
          ? { type: "DETAIL", toolkitId: editor.toolkitId }
          : { type: "CATALOG" },
      ),
    onRetryRead: () => {
      void refresh();
      void utils.toolkit.listToolkits.invalidate();
    },
    onSetupPendingChange,
    onCreatePublicationPendingChange,
    onCreateAbandonReady,
    onCompleteSetup: () => {
      completeWorkspaceToolkitSetup(activeEditor.current, editor, (next) => {
        // Publication is already committed; refresh failures are read failures, not unsaved forms.
        changeEditor(next);
        setSetupPending(false);
        setCreatePublicationPending(false);
        abandonCreate.current = null;
        void refresh();
      });
    },
    onDelete: (toolkitId) => {
      if (pending || formPending || writeInFlight.current) {
        return;
      }
      setDeleteState({ type: "IDLE" });
      setDeleteTarget(toolkitId);
    },
    onCancelDelete: () => {
      if (!removeMutation.isPending && !writeInFlight.current) {
        setDeleteTarget(null);
        setDeleteState({ type: "IDLE" });
      }
    },
    onConfirmDelete: () => {
      if (deleteTarget == null || pending || writeInFlight.current) {
        return;
      }
      writeInFlight.current = true;
      setDeleteState({ type: "PENDING" });
      removeMutation.mutate({ handle, toolkitId: deleteTarget });
    },
    onToggleEnabled: (toolkit, enabled) => {
      if (
        pending ||
        formPending ||
        deleteTarget != null ||
        writeInFlight.current ||
        !canToggleWorkspaceToolkit(toolkit, enabled)
      ) {
        return;
      }
      writeInFlight.current = true;
      setWriteState({ type: "PENDING", toolkitId: toolkit.id });
      updateMutation.mutate({ handle, toolkitId: toolkit.id, enabled });
    },
  };
}
