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
 * Workspace detail container hook
 *
 * Fetches data server-side through tRPC and
 * manages form logic, mutations, and complex state.
 */
export function useWorkspaceDetailContainer(
  props: WorkspaceDetailContainerProps,
) {
  const { workspaceHandle, isCreateMode, onSaved, onCancel } = props;
  const utils = trpc.useUtils();

  // --- Data loading ---
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

  // --- Form setup ---
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

  // Track the initial form data to determine dirty state
  const initialFormDataRef = useRef<string>(JSON.stringify(EMPTY_FORM));

  // Initialize the form when workspace data loads
  useEffect(() => {
    if (isCreateMode) {
      form.setValues(EMPTY_FORM);
      initialFormDataRef.current = JSON.stringify(EMPTY_FORM);
    } else if (currentWorkspace) {
      const formData = workspaceToFormData(currentWorkspace);
      form.setValues(formData);
      initialFormDataRef.current = JSON.stringify(formData);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form has a new reference on every render
  }, [currentWorkspace, isCreateMode]);

  // Track dirty state
  const isDirty =
    JSON.stringify(form.getValues()) !== initialFormDataRef.current;

  // --- Mutations ---
  const createMutation = trpc.workspace.create.useMutation();
  const updateMutation = trpc.workspace.update.useMutation();

  const isCreating = createMutation.isPending;
  const isUpdating = updateMutation.isPending;

  // --- State calculation ---
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

  // --- Handlers ---
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
