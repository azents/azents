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
 * Workspace member list container hook
 *
 * Fetches the workspace member list server-side through tRPC and converts it to an ADT.
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
