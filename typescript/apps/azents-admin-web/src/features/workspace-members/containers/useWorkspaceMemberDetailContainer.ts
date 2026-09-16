"use client";

import { useForm } from "@mantine/form";
import { modals } from "@mantine/modals";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import { workspaceMemberFormSchema } from "../schemas";
import {
  canDirectlyMutateWorkspaceMember,
  getAvailableWorkspaceMemberRoles,
  getDefaultWorkspaceMemberRole,
} from "../workspace-member-role-state";
import type {
  SelectOption,
  WorkspaceMemberDetailState,
  WorkspaceMemberFormData,
  WorkspaceUserResponse,
} from "../types";
import type { UseFormReturnType } from "@mantine/form";

export interface WorkspaceMemberDetailContainerProps {
  workspaceHandle: string | null;
  memberId: string | null;
  isCreateMode: boolean;
  onSaved: (workspaceHandle: string, member: WorkspaceUserResponse) => void;
  onDeleted: (workspaceHandle: string) => void;
  onCancel: () => void;
}

export interface WorkspaceMemberDetailComponentProps {
  state: WorkspaceMemberDetailState;
  form: UseFormReturnType<WorkspaceMemberFormData>;
  userOptions: SelectOption[];
  roleOptions: SelectOption[];
  isDirty: boolean;
  actionError: string | null;
  onSubmit: (data: WorkspaceMemberFormData) => void;
  onCancel: () => void;
  onDelete: () => void;
  onTransferOwnership: () => void;
}

const EMPTY_FORM: WorkspaceMemberFormData = {
  userId: "",
  name: "",
  role: "member",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The operation failed.";
}

function roleLabel(role: WorkspaceMemberFormData["role"]): string {
  switch (role) {
    case "owner":
      return "Owner";
    case "manager":
      return "Manager";
    case "member":
      return "Member";
  }
}

/** Manage Workspace member create, edit, transfer, and delete operations. */
export function useWorkspaceMemberDetailContainer(
  props: WorkspaceMemberDetailContainerProps,
): WorkspaceMemberDetailComponentProps {
  const {
    workspaceHandle,
    memberId,
    isCreateMode,
    onSaved,
    onDeleted,
    onCancel,
  } = props;
  const utils = trpc.useUtils();
  const [actionError, setActionError] = useState<string | null>(null);

  const memberQuery = trpc.workspaceMember.get.useQuery(
    { id: memberId ?? "" },
    { enabled: !!memberId && !isCreateMode },
  );
  const membersQuery = trpc.workspaceMember.listByWorkspace.useQuery(
    { workspace_handle: workspaceHandle ?? "" },
    { enabled: !!workspaceHandle },
  );
  const usersQuery = trpc.user.listAll.useQuery();

  const currentMember = memberQuery.data ?? null;
  const members = useMemo(
    () => membersQuery.data?.items ?? [],
    [membersQuery.data],
  );
  const ownerExists = members.some((member) => member.role === "owner");
  const existingUserIds = useMemo(
    () => new Set(members.map((member) => member.user_id)),
    [members],
  );
  const userOptions: SelectOption[] = (usersQuery.data?.items ?? [])
    .filter((user) => !existingUserIds.has(user.id))
    .map((user) => ({
      value: user.id,
      label: `${user.primary_email} (${user.id})`,
    }));
  const roleOptions: SelectOption[] = getAvailableWorkspaceMemberRoles({
    createMode: isCreateMode,
    ownerExists,
    currentRole: currentMember?.role ?? null,
  }).map((role) => ({
    value: role,
    label: roleLabel(role),
  }));

  const form = useForm<WorkspaceMemberFormData>({
    mode: "uncontrolled",
    initialValues: EMPTY_FORM,
    validate: (values) => {
      const result = workspaceMemberFormSchema.safeParse(values);
      if (result.success) {
        return {};
      }
      const errors: Record<string, string> = {};
      for (const issue of result.error.issues) {
        const path = issue.path.join(".");
        if (path) {
          errors[path] = issue.message;
        }
      }
      return errors;
    },
  });
  const initialFormDataRef = useRef<WorkspaceMemberFormData>(EMPTY_FORM);

  useEffect(() => {
    if (isCreateMode) {
      const values: WorkspaceMemberFormData = {
        ...EMPTY_FORM,
        role: getDefaultWorkspaceMemberRole(ownerExists),
      };
      form.setValues(values);
      initialFormDataRef.current = values;
    } else if (currentMember) {
      const values: WorkspaceMemberFormData = {
        userId: currentMember.user_id,
        name: currentMember.name,
        role: currentMember.role,
      };
      form.setValues(values);
      initialFormDataRef.current = values;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Mantine form changes identity on each render
  }, [currentMember, isCreateMode, ownerExists]);

  useEffect(() => {
    setActionError(null);
  }, [workspaceHandle, memberId, isCreateMode]);

  const isDirty =
    JSON.stringify(form.getValues()) !==
    JSON.stringify(initialFormDataRef.current);

  const createMutation = trpc.workspaceMember.create.useMutation();
  const updateMutation = trpc.workspaceMember.update.useMutation();
  const updateRoleMutation = trpc.workspaceMember.updateRole.useMutation();
  const transferMutation = trpc.workspaceMember.transferOwnership.useMutation();
  const deleteMutation = trpc.workspaceMember.delete.useMutation();
  const isSaving =
    createMutation.isPending ||
    updateMutation.isPending ||
    updateRoleMutation.isPending;

  const state: WorkspaceMemberDetailState = useMemo(() => {
    if (!workspaceHandle) {
      return { type: "EMPTY" };
    }
    if (isCreateMode) {
      if (membersQuery.isLoading || usersQuery.isLoading) {
        return { type: "LOADING" };
      }
      if (membersQuery.isError) {
        return { type: "ERROR", message: membersQuery.error.message };
      }
      if (usersQuery.isError) {
        return { type: "ERROR", message: usersQuery.error.message };
      }
      if (isSaving) {
        return {
          type: "SAVING",
          member: null,
          isNew: true,
          ownerExists,
        };
      }
      return {
        type: "EDITING",
        member: null,
        isNew: true,
        ownerExists,
      };
    }
    if (!memberId) {
      return { type: "EMPTY" };
    }
    if (memberQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (memberQuery.isError) {
      return { type: "ERROR", message: memberQuery.error.message };
    }
    if (!currentMember) {
      return { type: "LOADING" };
    }
    if (transferMutation.isPending) {
      return { type: "TRANSFERRING", member: currentMember };
    }
    if (deleteMutation.isPending) {
      return { type: "DELETING", member: currentMember };
    }
    if (isSaving) {
      return {
        type: "SAVING",
        member: currentMember,
        isNew: false,
        ownerExists,
      };
    }
    return {
      type: "EDITING",
      member: currentMember,
      isNew: false,
      ownerExists,
    };
  }, [
    workspaceHandle,
    isCreateMode,
    memberId,
    currentMember,
    ownerExists,
    isSaving,
    memberQuery.isLoading,
    memberQuery.isError,
    memberQuery.error,
    membersQuery.isLoading,
    membersQuery.isError,
    membersQuery.error,
    usersQuery.isLoading,
    usersQuery.isError,
    usersQuery.error,
    transferMutation.isPending,
    deleteMutation.isPending,
  ]);

  const handleSubmit = useCallback(
    (data: WorkspaceMemberFormData): void => {
      if (!workspaceHandle) {
        return;
      }
      setActionError(null);

      const save = async (): Promise<void> => {
        try {
          if (isCreateMode) {
            const response = await createMutation.mutateAsync({
              workspace_handle: workspaceHandle,
              user_id: data.userId,
              name: data.name,
              role: data.role,
            });
            await utils.workspaceMember.listByWorkspace.invalidate({
              workspace_handle: workspaceHandle,
            });
            onSaved(workspaceHandle, response);
            return;
          }
          if (!currentMember) {
            return;
          }

          let response = currentMember;
          if (data.name !== initialFormDataRef.current.name) {
            response = await updateMutation.mutateAsync({
              workspace_user_id: currentMember.id,
              name: data.name,
            });
          }
          if (
            data.role !== initialFormDataRef.current.role &&
            data.role !== "owner"
          ) {
            response = await updateRoleMutation.mutateAsync({
              workspace_user_id: currentMember.id,
              role: data.role,
            });
          }
          await Promise.all([
            utils.workspaceMember.listByWorkspace.invalidate({
              workspace_handle: workspaceHandle,
            }),
            utils.workspaceMember.get.invalidate({ id: currentMember.id }),
          ]);
          onSaved(workspaceHandle, response);
        } catch (error) {
          const message = errorMessage(error);
          if (currentMember) {
            await Promise.allSettled([
              utils.workspaceMember.listByWorkspace.invalidate({
                workspace_handle: workspaceHandle,
              }),
              utils.workspaceMember.get.invalidate({ id: currentMember.id }),
            ]);
          }
          setActionError(message);
        }
      };

      void save();
    },
    [
      workspaceHandle,
      isCreateMode,
      currentMember,
      createMutation,
      updateMutation,
      updateRoleMutation,
      utils,
      onSaved,
    ],
  );

  const handleCancel = useCallback((): void => {
    setActionError(null);
    if (isCreateMode) {
      onCancel();
      return;
    }
    form.setValues(initialFormDataRef.current);
  }, [form, isCreateMode, onCancel]);

  const handleTransferOwnership = useCallback((): void => {
    if (
      !workspaceHandle ||
      !currentMember ||
      !canDirectlyMutateWorkspaceMember(currentMember.role)
    ) {
      return;
    }
    modals.openConfirmModal({
      title: "Transfer Workspace Ownership",
      children: `${currentMember.name} will become the Owner. The current Owner will become a Manager.`,
      labels: { confirm: "Transfer Ownership", cancel: "Cancel" },
      onConfirm: () => {
        setActionError(null);
        transferMutation.mutate(
          {
            workspace_handle: workspaceHandle,
            new_owner_workspace_user_id: currentMember.id,
          },
          {
            onSuccess: (response) => {
              void utils.workspaceMember.listByWorkspace.invalidate({
                workspace_handle: workspaceHandle,
              });
              void utils.workspaceMember.get.invalidate();
              onSaved(workspaceHandle, response);
            },
            onError: (error) => setActionError(errorMessage(error)),
          },
        );
      },
    });
  }, [workspaceHandle, currentMember, transferMutation, utils, onSaved]);

  const handleDelete = useCallback((): void => {
    if (
      !workspaceHandle ||
      !currentMember ||
      !canDirectlyMutateWorkspaceMember(currentMember.role)
    ) {
      return;
    }
    modals.openConfirmModal({
      title: "Remove Workspace Member",
      children:
        "Remove this member from the Workspace? Their Workspace access will end immediately.",
      labels: { confirm: "Remove", cancel: "Cancel" },
      confirmProps: { color: "red" },
      onConfirm: () => {
        setActionError(null);
        deleteMutation.mutate(
          { id: currentMember.id },
          {
            onSuccess: () => {
              void utils.workspaceMember.listByWorkspace.invalidate({
                workspace_handle: workspaceHandle,
              });
              void utils.workspaceMember.get.invalidate({
                id: currentMember.id,
              });
              onDeleted(workspaceHandle);
            },
            onError: (error) => setActionError(errorMessage(error)),
          },
        );
      },
    });
  }, [workspaceHandle, currentMember, deleteMutation, utils, onDeleted]);

  return {
    state,
    form,
    userOptions,
    roleOptions,
    isDirty,
    actionError,
    onSubmit: handleSubmit,
    onCancel: handleCancel,
    onDelete: handleDelete,
    onTransferOwnership: handleTransferOwnership,
  };
}
