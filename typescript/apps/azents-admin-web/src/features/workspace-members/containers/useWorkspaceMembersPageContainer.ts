"use client";

import { useCallback } from "react";
import { serializers, useQueryStates } from "@/hooks/use-query-state";
import { trpc } from "@/trpc/client";
import { getWorkspaceMemberMutationLocation } from "../workspace-member-role-state";
import type { WorkspaceSelectorState, WorkspaceUserResponse } from "../types";

const MODES = ["view", "create"] as const;

export interface WorkspaceMembersPageContentProps {
  workspaceSelectorState: WorkspaceSelectorState;
  selectedWorkspaceHandle: string | null;
  selectedMemberId: string | null;
  isCreateMode: boolean;
  onWorkspaceChange: (workspaceHandle: string | null) => void;
  onMemberSelect: (member: WorkspaceUserResponse) => void;
  onCreateNew: () => void;
  onSaved: (workspaceHandle: string, member: WorkspaceUserResponse) => void;
  onDeleted: (workspaceHandle: string) => void;
  onCancel: () => void;
  onDetailClose: () => void;
}

/** Manage Workspace selection and member detail mode in URL query state. */
export function useWorkspaceMembersPageContainer(): WorkspaceMembersPageContentProps {
  const [state, setState] = useQueryStates({
    workspace: serializers.stringOrNull(),
    memberId: serializers.stringOrNull(),
    mode: serializers.literal(MODES, "view"),
  });
  const workspaceQuery = trpc.workspace.list.useQuery();

  const workspaceSelectorState: WorkspaceSelectorState =
    workspaceQuery.isLoading
      ? { type: "LOADING" }
      : workspaceQuery.isError
        ? { type: "ERROR", message: workspaceQuery.error.message }
        : {
            type: "READY",
            options: (workspaceQuery.data?.items ?? []).map((workspace) => ({
              value: workspace.handle,
              label: `${workspace.name} (${workspace.handle})`,
            })),
          };

  const selectedWorkspaceHandle = state.workspace;
  const selectedMemberId = state.memberId;
  const isCreateMode = state.mode === "create";

  const handleWorkspaceChange = useCallback(
    (workspaceHandle: string | null): void => {
      setState({ workspace: workspaceHandle, memberId: null, mode: "view" });
    },
    [setState],
  );

  const handleMemberSelect = useCallback(
    (member: WorkspaceUserResponse): void => {
      setState({ memberId: member.id, mode: "view" });
    },
    [setState],
  );

  const handleCreateNew = useCallback((): void => {
    if (!selectedWorkspaceHandle) {
      return;
    }
    setState({ memberId: null, mode: "create" });
  }, [selectedWorkspaceHandle, setState]);

  const handleSaved = useCallback(
    (workspaceHandle: string, member: WorkspaceUserResponse): void => {
      setState(getWorkspaceMemberMutationLocation(workspaceHandle, member.id));
    },
    [setState],
  );

  const handleDeleted = useCallback(
    (workspaceHandle: string): void => {
      setState(getWorkspaceMemberMutationLocation(workspaceHandle, null));
    },
    [setState],
  );

  const handleCancel = useCallback((): void => {
    setState({ memberId: null, mode: "view" });
  }, [setState]);

  const handleDetailClose = useCallback((): void => {
    setState({ memberId: null, mode: "view" });
  }, [setState]);

  return {
    workspaceSelectorState,
    selectedWorkspaceHandle,
    selectedMemberId,
    isCreateMode,
    onWorkspaceChange: handleWorkspaceChange,
    onMemberSelect: handleMemberSelect,
    onCreateNew: handleCreateNew,
    onSaved: handleSaved,
    onDeleted: handleDeleted,
    onCancel: handleCancel,
    onDetailClose: handleDetailClose,
  };
}
