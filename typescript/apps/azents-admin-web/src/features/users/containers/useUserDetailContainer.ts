"use client";

import { modals } from "@mantine/modals";
import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import type { UserDetailState, UserEmailResponse } from "../types";

export interface UserDetailContainerProps {
  userId: string | null;
  onDeleted: () => void;
}

export interface UserDetailComponentProps {
  state: UserDetailState;
  emails: UserEmailResponse[];
  isLoadingEmails: boolean;
  onDelete: () => void;
  onAddEmail: (email: string) => void;
  onDeleteEmail: (emailId: string) => void;
}

/**
 * User 상세 컨테이너 훅
 *
 * tRPC를 사용하여 서버사이드에서 데이터를 가져오고,
 * 삭제 뮤테이션을 관리합니다.
 */
export function useUserDetailContainer(
  props: UserDetailContainerProps,
): UserDetailComponentProps {
  const { userId, onDeleted } = props;
  const utils = trpc.useUtils();

  // --- 데이터 로딩 ---
  const {
    data: userData,
    isLoading: isLoadingUser,
    isError: isLoadError,
    error: loadError,
  } = trpc.user.get.useQuery({ id: userId ?? "" }, { enabled: !!userId });

  const currentUser = userData ?? null;

  // --- 이메일 목록 로딩 ---
  const { data: emailData, isLoading: isLoadingEmails } =
    trpc.userEmail.listByUser.useQuery(
      { user_id: userId ?? "" },
      { enabled: !!userId },
    );

  const emails = emailData?.items ?? [];

  // --- 뮤테이션 ---
  const deleteMutation = trpc.user.delete.useMutation();
  const isDeleting = deleteMutation.isPending;

  const createEmailMutation = trpc.userEmail.create.useMutation();
  const deleteEmailMutation = trpc.userEmail.delete.useMutation();

  // --- 상태 계산 ---
  const state: UserDetailState = useMemo(() => {
    if (!userId) {
      return { type: "EMPTY" };
    }
    if (isDeleting && currentUser) {
      return { type: "DELETING", user: currentUser };
    }
    if (isLoadingUser) {
      return { type: "LOADING", userId };
    }
    if (isLoadError) {
      return {
        type: "ERROR",
        userId,
        message: loadError.message,
      };
    }
    if (currentUser) {
      return { type: "VIEWING", user: currentUser };
    }
    return { type: "LOADING", userId };
  }, [userId, currentUser, isLoadingUser, isLoadError, loadError, isDeleting]);

  // --- 핸들러 ---
  const handleDelete = useCallback(() => {
    if (!userId) {
      return;
    }
    modals.openConfirmModal({
      title: "유저 삭제",
      children:
        "정말 이 유저를 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.",
      labels: { confirm: "삭제", cancel: "취소" },
      confirmProps: { color: "red" },
      onConfirm: () => {
        deleteMutation.mutate(
          { id: userId },
          {
            onSuccess: () => {
              void utils.user.list.invalidate();
              void utils.user.get.invalidate({ id: userId });
              onDeleted();
            },
          },
        );
      },
    });
  }, [userId, deleteMutation, utils, onDeleted]);

  const handleAddEmail = useCallback(
    (email: string) => {
      if (!userId) {
        return;
      }
      createEmailMutation.mutate(
        { user_id: userId, email },
        {
          onSuccess: () => {
            void utils.userEmail.listByUser.invalidate({ user_id: userId });
          },
        },
      );
    },
    [userId, createEmailMutation, utils],
  );

  const handleDeleteEmail = useCallback(
    (emailId: string) => {
      if (!userId) {
        return;
      }
      modals.openConfirmModal({
        title: "이메일 삭제",
        children: "정말 이 이메일을 삭제하시겠습니까?",
        labels: { confirm: "삭제", cancel: "취소" },
        confirmProps: { color: "red" },
        onConfirm: () => {
          deleteEmailMutation.mutate(
            { email_id: emailId },
            {
              onSuccess: () => {
                void utils.userEmail.listByUser.invalidate({
                  user_id: userId,
                });
              },
            },
          );
        },
      });
    },
    [userId, deleteEmailMutation, utils],
  );

  return {
    state,
    emails,
    isLoadingEmails,
    onDelete: handleDelete,
    onAddEmail: handleAddEmail,
    onDeleteEmail: handleDeleteEmail,
  };
}
