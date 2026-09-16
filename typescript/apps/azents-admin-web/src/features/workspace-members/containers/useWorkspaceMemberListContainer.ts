"use client";

import { trpc } from "@/trpc/client";
import type { WorkspaceMemberListState, WorkspaceUserResponse } from "../types";

export interface WorkspaceMemberListContainerProps {
  selectedWorkspaceHandle: string | null;
  selectedMemberId: string | null;
  onRowClick: (member: WorkspaceUserResponse) => void;
  onCreateNew: () => void;
}

export interface WorkspaceMemberListComponentProps {
  state: WorkspaceMemberListState;
  selectedMemberId: string | null;
  canCreate: boolean;
  onRowClick: (member: WorkspaceUserResponse) => void;
  onCreateNew: () => void;
}

/** Fetch the member list and convert query state to the list ADT. */
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
    canCreate: props.selectedWorkspaceHandle !== null,
    onRowClick: props.onRowClick,
    onCreateNew: props.onCreateNew,
  };
}
