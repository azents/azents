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
 * Workspace 목록 컨테이너 훅
 *
 * tRPC를 사용하여 workspace 목록을 서버사이드에서 가져오고 ADT로 변환합니다.
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
