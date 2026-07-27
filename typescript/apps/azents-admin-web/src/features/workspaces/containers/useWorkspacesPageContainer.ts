"use client";

import { useCallback } from "react";
import { serializers, useQueryStates } from "@/hooks/use-query-state";
import type { WorkspaceResponse } from "../types";

const MODES = ["view", "create"] as const;

export interface WorkspacesPageContentProps {
  selectedWorkspaceHandle: string | null;
  isCreateMode: boolean;
  onWorkspaceSelect: (workspace: WorkspaceResponse) => void;
  onCreateNew: () => void;
  onCancel: () => void;
  onSaved: (handle: string) => void;
  onDetailClose: () => void;
}

/** Manage the selected Workspace and creation mode in URL query state. */
export function useWorkspacesPageContainer(): WorkspacesPageContentProps {
  const [state, setState] = useQueryStates({
    workspace: serializers.stringOrNull(),
    mode: serializers.literal(MODES, "view"),
  });
  const selectedWorkspaceHandle = state.workspace;
  const isCreateMode = state.mode === "create";

  const handleWorkspaceSelect = useCallback(
    (workspace: WorkspaceResponse): void => {
      setState({ workspace: workspace.handle, mode: "view" });
    },
    [setState],
  );

  const handleCreateNew = useCallback((): void => {
    setState({ workspace: null, mode: "create" });
  }, [setState]);

  const handleCancel = useCallback((): void => {
    setState({ mode: "view" });
  }, [setState]);

  const handleSaved = useCallback(
    (handle: string): void => {
      setState({ workspace: handle, mode: "view" });
    },
    [setState],
  );

  const handleDetailClose = useCallback((): void => {
    setState({ workspace: null, mode: "view" });
  }, [setState]);

  return {
    selectedWorkspaceHandle,
    isCreateMode,
    onWorkspaceSelect: handleWorkspaceSelect,
    onCreateNew: handleCreateNew,
    onCancel: handleCancel,
    onSaved: handleSaved,
    onDetailClose: handleDetailClose,
  };
}
