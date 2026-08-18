"use client";

import { useCallback } from "react";
import { serializers, useQueryStates } from "@/hooks/use-query-state";
import type { WorkspaceUserResponse } from "../types";

export interface WorkspaceMembersPageContentProps {
  selectedWorkspaceHandle: string | null;
  selectedMemberId: string | null;
  onWorkspaceChange: (workspaceHandle: string | null) => void;
  onMemberSelect: (member: WorkspaceUserResponse) => void;
  onDeleted: () => void;
  onDetailClose: () => void;
}

/**
 * Workspace members page container hook
 *
 * Manages the selected workspace and member through URL query state.
 */
export function useWorkspaceMembersPageContainer(): WorkspaceMembersPageContentProps {
  const [state, setState] = useQueryStates({
    workspace: serializers.stringOrNull(),
    memberId: serializers.stringOrNull(),
  });

  const { workspace: selectedWorkspaceHandle, memberId: selectedMemberId } =
    state;

  const handleWorkspaceChange = useCallback(
    (workspaceHandle: string | null): void => {
      setState({ workspace: workspaceHandle, memberId: null });
    },
    [setState],
  );

  const handleMemberSelect = useCallback(
    (member: WorkspaceUserResponse): void => {
      setState({ memberId: member.id });
    },
    [setState],
  );

  const handleDeleted = useCallback((): void => {
    setState({ memberId: null });
  }, [setState]);

  const handleDetailClose = useCallback((): void => {
    setState({ memberId: null });
  }, [setState]);

  return {
    selectedWorkspaceHandle,
    selectedMemberId,
    onWorkspaceChange: handleWorkspaceChange,
    onMemberSelect: handleMemberSelect,
    onDeleted: handleDeleted,
    onDetailClose: handleDetailClose,
  };
}
