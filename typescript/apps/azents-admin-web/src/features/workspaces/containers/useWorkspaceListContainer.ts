"use client";

import { trpc } from "@/trpc/client";
import type { WorkspaceListState, WorkspaceResponse } from "../types";

export interface WorkspaceListContainerProps {
  selectedWorkspaceHandle: string | null;
  onRowClick: (workspace: WorkspaceResponse) => void;
  onCreateNew: () => void;
}

export interface WorkspaceListComponentProps {
  state: WorkspaceListState;
  selectedWorkspaceHandle: string | null;
  onRowClick: (workspace: WorkspaceResponse) => void;
  onCreateNew: () => void;
}

/**
 * Workspace list container hook
 *
 * Fetches the workspace list server-side through tRPC and converts it to an ADT.
 */
export function useWorkspaceListContainer(
  props: WorkspaceListContainerProps,
): WorkspaceListComponentProps {
  const { data, isLoading, isError, error } = trpc.workspace.list.useQuery();

  const state: WorkspaceListState = isLoading
    ? { type: "LOADING" }
    : isError
      ? {
          type: "ERROR",
          message: error.message,
        }
      : {
          type: "LOADED",
          workspaces: data?.items ?? [],
        };

  return {
    state,
    selectedWorkspaceHandle: props.selectedWorkspaceHandle,
    onRowClick: props.onRowClick,
    onCreateNew: props.onCreateNew,
  };
}
