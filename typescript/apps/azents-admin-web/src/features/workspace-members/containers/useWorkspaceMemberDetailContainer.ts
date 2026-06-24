"use client";

import { modals } from "@mantine/modals";
import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import type { WorkspaceMemberDetailState } from "../types";

export interface WorkspaceMemberDetailContainerProps {
  memberId: string | null;
  onDeleted: () => void;
}

export interface WorkspaceMemberDetailComponentProps {
  state: WorkspaceMemberDetailState;
  onDelete: () => void;
}

/**
 * WorkspaceMember 상세 컨테이너 훅
 *
 * tRPC를 사용하여 서버사이드에서 데이터를 가져오고,
 * 삭제 뮤테이션을 관리합니다.
 */
export function useWorkspaceMemberDetailContainer(
  props: WorkspaceMemberDetailContainerProps,
): WorkspaceMemberDetailComponentProps {
  const { memberId, onDeleted } = props;
  const utils = trpc.useUtils();

  // --- 데이터 로딩 ---
  const {
    data: memberData,
    isLoading: isLoadingMember,
    isError: isLoadError,
    error: loadError,
  } = trpc.workspaceMember.get.useQuery(
    { id: memberId ?? "" },
    { enabled: !!memberId },
  );

  const currentMember = memberData ?? null;

  // --- 뮤테이션 ---
  const deleteMutation = trpc.workspaceMember.delete.useMutation();
  const isDeleting = deleteMutation.isPending;

  // --- 상태 계산 ---
  const state: WorkspaceMemberDetailState = useMemo(() => {
    if (!memberId) {
      return { type: "EMPTY" };
    }
    if (isDeleting && currentMember) {
      return { type: "DELETING", member: currentMember };
    }
    if (isLoadingMember) {
      return { type: "LOADING", memberId };
    }
    if (isLoadError) {
      return {
        type: "ERROR",
        memberId,
        message: loadError.message,
      };
    }
    if (currentMember) {
      return { type: "VIEWING", member: currentMember };
    }
    return { type: "LOADING", memberId };
  }, [
    memberId,
    currentMember,
    isLoadingMember,
    isLoadError,
    loadError,
    isDeleting,
  ]);

  // --- 핸들러 ---
  const handleDelete = useCallback(() => {
    if (!memberId) {
      return;
    }
    modals.openConfirmModal({
      title: "멤버 제거",
      children:
        "정말 이 멤버를 제거하시겠습니까? 이 작업은 되돌릴 수 없습니다.",
      labels: { confirm: "제거", cancel: "취소" },
      confirmProps: { color: "red" },
      onConfirm: () => {
        deleteMutation.mutate(
          { id: memberId },
          {
            onSuccess: () => {
              void utils.workspaceMember.listByWorkspace.invalidate();
              void utils.workspaceMember.get.invalidate({ id: memberId });
              onDeleted();
            },
          },
        );
      },
    });
  }, [memberId, deleteMutation, utils, onDeleted]);

  return {
    state,
    onDelete: handleDelete,
  };
}
