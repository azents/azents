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
 * WorkspaceMembers 페이지 컨테이너 훅
 *
 * URL 쿼리 상태로 선택된 workspace와 member를 관리합니다.
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
