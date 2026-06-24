"use client";

import { trpc } from "@/trpc/client";
import type { WorkspaceMemberListState, WorkspaceUserResponse } from "../types";

export interface WorkspaceMemberListContainerProps {
  selectedWorkspaceHandle: string | null;
  selectedMemberId: string | null;
  onRowClick: (member: WorkspaceUserResponse) => void;
}

export interface WorkspaceMemberListComponentProps {
  state: WorkspaceMemberListState;
  selectedMemberId: string | null;
  onRowClick: (member: WorkspaceUserResponse) => void;
}

/**
 * WorkspaceMember 목록 컨테이너 훅
 *
 * tRPC를 사용하여 멤버 목록을 서버사이드에서 가져오고 ADT로 변환합니다.
 */
export function useWorkspaceMemberListContainer(
  props: WorkspaceMemberListContainerProps,
): WorkspaceMemberListComponentProps {
  const { data, isLoading, isError, error } =
    trpc.workspaceMember.listByWorkspace.useQuery(
      { workspace_handle: props.selectedWorkspaceHandle ?? "" },
      { enabled: !!props.selectedWorkspaceHandle },
    );

  const state: WorkspaceMemberListState = !props.selectedWorkspaceHandle
    ? { type: "NO_WORKSPACE" }
    : isLoading
      ? { type: "LOADING" }
      : isError
        ? {
            type: "ERROR",
            message: error.message,
          }
        : {
            type: "LOADED",
            members: data?.items ?? [],
          };

  return {
    state,
    selectedMemberId: props.selectedMemberId,
    onRowClick: props.onRowClick,
  };
}
