"use client";

import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { useLogout } from "@refinedev/core";
import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import { getSystemAdminRoleSummary } from "../system-admin-state";
import type {
  SystemAdminRoleState,
  UserDetailState,
  UserEmailResponse,
} from "../types";

export interface UserDetailContainerProps {
  userId: string | null;
  onDeleted: () => void;
}

export interface UserDetailComponentProps {
  state: UserDetailState;
  roleState: SystemAdminRoleState;
  emails: UserEmailResponse[];
  isLoadingEmails: boolean;
  onDelete: () => void;
  onGrantAdmin: () => void;
  onRevokeAdmin: () => void;
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
  const { mutate: logout } = useLogout();

  // --- 데이터 로딩 ---
  const {
    data: userData,
    isLoading: isLoadingUser,
    isError: isLoadError,
    error: loadError,
  } = trpc.user.get.useQuery({ id: userId ?? "" }, { enabled: !!userId });

  const currentUser = userData ?? null;

  const {
    data: roleData,
    isLoading: isLoadingRoles,
    isError: isRoleError,
    error: roleError,
  } = trpc.systemRole.list.useQuery({}, { enabled: !!userId });
  const {
    data: currentAdmin,
    isLoading: isLoadingCurrentAdmin,
    isError: isCurrentAdminError,
    error: currentAdminError,
  } = trpc.systemRole.me.useQuery(
    {},
    {
      enabled: !!userId,
      retry: false,
    },
  );

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
  const grantAdminMutation = trpc.systemRole.grantAdmin.useMutation();
  const revokeAdminMutation = trpc.systemRole.revokeAdmin.useMutation();

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

  const roleState: SystemAdminRoleState = useMemo(() => {
    if (isLoadingRoles || isLoadingCurrentAdmin) {
      return { type: "LOADING" };
    }
    if (isRoleError || isCurrentAdminError) {
      return {
        type: "ERROR",
        message:
          roleError?.message ??
          currentAdminError?.message ??
          "System administrator status could not be loaded.",
      };
    }

    const assignments = roleData?.items ?? [];
    const summary = getSystemAdminRoleSummary(
      assignments,
      currentAdmin?.user_id ?? null,
      userId,
    );
    let action: "IDLE" | "GRANTING" | "REVOKING" = "IDLE";
    if (grantAdminMutation.isPending) {
      action = "GRANTING";
    } else if (revokeAdminMutation.isPending) {
      action = "REVOKING";
    }
    return {
      type: "READY",
      ...summary,
      action,
    };
  }, [
    currentAdmin,
    currentAdminError,
    grantAdminMutation.isPending,
    isCurrentAdminError,
    isLoadingCurrentAdmin,
    isLoadingRoles,
    isRoleError,
    revokeAdminMutation.isPending,
    roleData,
    roleError,
    userId,
  ]);

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
              void utils.systemRole.list.invalidate();
              onDeleted();
            },
            onError: (error) => {
              notifications.show({
                color: "red",
                title: "User could not be deleted",
                message:
                  error.data?.code === "CONFLICT"
                    ? "The final system administrator cannot be deleted. Grant another administrator first."
                    : error.message,
              });
            },
          },
        );
      },
    });
  }, [userId, deleteMutation, utils, onDeleted]);

  const handleGrantAdmin = useCallback(() => {
    if (!userId) {
      return;
    }
    grantAdminMutation.mutate(
      { userId },
      {
        onSuccess: () => {
          void utils.systemRole.list.invalidate();
          notifications.show({
            color: "green",
            title: "System administrator granted",
            message: "This user can now access instance administration.",
          });
        },
        onError: (error) => {
          notifications.show({
            color: "red",
            title: "Role could not be granted",
            message: error.message,
          });
        },
      },
    );
  }, [grantAdminMutation, userId, utils]);

  const handleRevokeAdmin = useCallback(() => {
    if (!userId || roleState.type !== "READY" || !roleState.assigned) {
      return;
    }
    const revokingCurrentUser = roleState.currentUser;
    modals.openConfirmModal({
      title: revokingCurrentUser
        ? "Revoke your system administrator access?"
        : "Revoke system administrator access?",
      children: revokingCurrentUser
        ? "You will be signed out of Admin Web immediately."
        : "This user will no longer be able to access instance administration.",
      labels: { confirm: "Revoke access", cancel: "Cancel" },
      confirmProps: { color: "red" },
      onConfirm: () => {
        revokeAdminMutation.mutate(
          { userId },
          {
            onSuccess: () => {
              void utils.systemRole.list.invalidate();
              if (revokingCurrentUser) {
                notifications.show({
                  color: "blue",
                  title: "Access revoked",
                  message: "Signing out of Admin Web.",
                });
                logout();
                return;
              }
              notifications.show({
                color: "green",
                title: "System administrator revoked",
                message:
                  "This user no longer has instance administration access.",
              });
            },
            onError: (error) => {
              notifications.show({
                color: "red",
                title: "Role could not be revoked",
                message:
                  error.data?.code === "CONFLICT"
                    ? "The final system administrator cannot be revoked. Grant another administrator first."
                    : error.message,
              });
            },
          },
        );
      },
    });
  }, [logout, revokeAdminMutation, roleState, userId, utils]);

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
    roleState,
    emails,
    isLoadingEmails,
    onDelete: handleDelete,
    onGrantAdmin: handleGrantAdmin,
    onRevokeAdmin: handleRevokeAdmin,
    onAddEmail: handleAddEmail,
    onDeleteEmail: handleDeleteEmail,
  };
}
