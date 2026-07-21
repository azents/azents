"use client";

import { useForm } from "@mantine/form";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { trpc } from "@/trpc/client";
import { workspaceFormSchema } from "../schemas";
import {
  formDataToCreateRequest,
  formDataToUpdateRequest,
  workspaceToFormData,
} from "../types";
import type { WorkspaceDetailState, WorkspaceFormData } from "../types";

export interface WorkspaceDetailContainerProps {
  workspaceHandle: string | null;
  isCreateMode: boolean;
  onSaved: (handle: string) => void;
  onCancel: () => void;
}

export type WorkspaceDetailComponentProps = ReturnType<
  typeof useWorkspaceDetailContainer
>;

const EMPTY_FORM: WorkspaceFormData = {
  name: "",
  handle: "",
};

/**
 * Workspace 상세 컨테이너 훅
 *
 * tRPC를 사용하여 서버사이드에서 데이터를 가져오고,
 * 폼 로직, 뮤테이션, 복잡한 상태를 관리합니다.
 */
export function useWorkspaceDetailContainer(
  props: WorkspaceDetailContainerProps,
) {
  const { workspaceHandle, isCreateMode, onSaved, onCancel } = props;
  const utils = trpc.useUtils();

  // --- 데이터 로딩 ---
  const {
    data: workspaceData,
    isLoading: isLoadingWorkspace,
    isError: isLoadError,
    error: loadError,
  } = trpc.workspace.get.useQuery(
    { handle: workspaceHandle ?? "" },
    { enabled: !!workspaceHandle && !isCreateMode },
  );

  const currentWorkspace = workspaceData ?? null;

  // --- 폼 설정 ---
  const form = useForm<WorkspaceFormData>({
    mode: "uncontrolled",
    initialValues: EMPTY_FORM,
    validate: (values) => {
      const result = workspaceFormSchema.safeParse(values);
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

  // 초기 폼 데이터 추적 (dirty 상태 판단용)
  const initialFormDataRef = useRef<string>(JSON.stringify(EMPTY_FORM));

  // Workspace 데이터가 로드되면 폼 초기화
  useEffect(() => {
    if (isCreateMode) {
      form.setValues(EMPTY_FORM);
      initialFormDataRef.current = JSON.stringify(EMPTY_FORM);
    } else if (currentWorkspace) {
      const formData = workspaceToFormData(currentWorkspace);
      form.setValues(formData);
      initialFormDataRef.current = JSON.stringify(formData);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form은 매 렌더마다 새로운 참조
  }, [currentWorkspace, isCreateMode]);

  // Dirty 상태 추적
  const isDirty =
    JSON.stringify(form.getValues()) !== initialFormDataRef.current;

  // --- 뮤테이션 ---
  const createMutation = trpc.workspace.create.useMutation();
  const updateMutation = trpc.workspace.update.useMutation();

  const isCreating = createMutation.isPending;
  const isUpdating = updateMutation.isPending;

  // --- 상태 계산 ---
  const state: WorkspaceDetailState = useMemo(() => {
    if (!isCreateMode && !workspaceHandle) {
      return { type: "EMPTY" };
    }
    if (isCreating || isUpdating) {
      return {
        type: "SAVING",
        workspace: currentWorkspace,
        isNew: isCreateMode,
      };
    }
    if (!isCreateMode && isLoadingWorkspace) {
      return { type: "LOADING", handle: workspaceHandle ?? "" };
    }
    if (!isCreateMode && isLoadError) {
      return {
        type: "ERROR",
        handle: workspaceHandle ?? "",
        message: loadError.message,
      };
    }
    return {
      type: "EDITING",
      workspace: currentWorkspace,
      isNew: isCreateMode,
    };
  }, [
    isCreateMode,
    workspaceHandle,
    currentWorkspace,
    isLoadingWorkspace,
    isLoadError,
    loadError,
    isCreating,
    isUpdating,
  ]);

  // --- 핸들러 ---
  const handleSubmit = useCallback(
    (data: WorkspaceFormData) => {
      if (isCreateMode) {
        const request = formDataToCreateRequest(data);
        createMutation.mutate(request, {
          onSuccess: (response) => {
            void utils.workspace.list.invalidate();
            onSaved(response.handle);
          },
        });
      } else if (workspaceHandle) {
        const request = formDataToUpdateRequest(data);
        updateMutation.mutate(
          {
            handle: workspaceHandle,
            name: request.name,
            new_handle: request.handle,
          },
          {
            onSuccess: (response) => {
              void utils.workspace.list.invalidate();
              void utils.workspace.get.invalidate({
                handle: response.handle,
              });
              onSaved(response.handle);
            },
          },
        );
      }
    },
    [
      isCreateMode,
      workspaceHandle,
      createMutation,
      updateMutation,
      utils,
      onSaved,
    ],
  );

  return {
    state,
    form,
    isDirty,
    onSubmit: handleSubmit,
    onCancel,
  };
}
