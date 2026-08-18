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
 * Workspace member detail container hook
 *
 * Fetches data server-side through tRPC and
 * manages the delete mutation.
 */
export function useWorkspaceMemberDetailContainer(
  props: WorkspaceMemberDetailContainerProps,
): WorkspaceMemberDetailComponentProps {
  const { memberId, onDeleted } = props;
  const utils = trpc.useUtils();

  // --- Data loading ---
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

  // --- Mutations ---
  const deleteMutation = trpc.workspaceMember.delete.useMutation();
  const isDeleting = deleteMutation.isPending;

  // --- State calculation ---
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

  // --- Handlers ---
  const handleDelete = useCallback(() => {
    if (!memberId) {
      return;
    }
    modals.openConfirmModal({
      title: "Remove Workspace Member",
      children:
        "Are you sure you want to remove this workspace member? This action cannot be undone.",
      labels: { confirm: "Remove", cancel: "Cancel" },
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
