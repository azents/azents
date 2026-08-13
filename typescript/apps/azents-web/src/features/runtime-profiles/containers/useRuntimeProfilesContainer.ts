"use client";

import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import { runtimeProfileMutationPolicy } from "../runtimeProfilePolicy";
import type { RuntimeProfileFormValues } from "../schemas";
import type {
  RuntimeProfileDeletionErrorKind,
  RuntimeProfileDeletionFeedbackState,
  RuntimeProfileDeletionState,
  RuntimeProfileEditorState,
  RuntimeProfileMutationState,
  RuntimeProfileOperationState,
  RuntimeProfilesState,
} from "../types";
import type { WorkspaceRuntimeProfileResponse } from "@azents/public-client";

export interface RuntimeProfilesContainerProps {
  handle: string;
}

export interface RuntimeProfilesContainerOutput {
  handle: string;
  state: RuntimeProfilesState;
  editorState: RuntimeProfileEditorState;
  mutationState: RuntimeProfileMutationState;
  operationState: RuntimeProfileOperationState;
  deletionState: RuntimeProfileDeletionState;
  deletionFeedbackState: RuntimeProfileDeletionFeedbackState;
  canManage: boolean;
  canDelete: boolean;
  onOpenCreate: () => void;
  onOpenEdit: (profile: WorkspaceRuntimeProfileResponse) => void;
  onCloseEditor: () => void;
  onSubmit: (values: RuntimeProfileFormValues) => void;
  onSetDefault: (profileId: string | null) => void;
  onRecreate: (profile: WorkspaceRuntimeProfileResponse) => void;
  onOpenDelete: (profile: WorkspaceRuntimeProfileResponse) => void;
  onCloseDelete: () => void;
  onConfirmDelete: (profile: WorkspaceRuntimeProfileResponse) => void;
  onDismissDeletionFeedback: () => void;
}

function errorCode(error: unknown): string | null {
  if (
    typeof error !== "object" ||
    error === null ||
    !("data" in error) ||
    typeof error.data !== "object" ||
    error.data === null ||
    !("code" in error.data) ||
    typeof error.data.code !== "string"
  ) {
    return null;
  }
  return error.data.code;
}

function deletionErrorKind(error: unknown): RuntimeProfileDeletionErrorKind {
  const code = errorCode(error);
  if (
    code === "CONFLICT" ||
    code === "NOT_FOUND" ||
    code === "FORBIDDEN" ||
    code === "UNAUTHORIZED" ||
    code === "BAD_REQUEST"
  ) {
    return code;
  }
  return "UNKNOWN";
}

export function useRuntimeProfilesContainer(
  props: RuntimeProfilesContainerProps,
): RuntimeProfilesContainerOutput {
  const { handle } = props;
  const utils = trpc.useUtils();
  const [editorState, setEditorState] = useState<RuntimeProfileEditorState>({
    type: "CLOSED",
  });
  const [mutationState, setMutationState] =
    useState<RuntimeProfileMutationState>({
      type: "IDLE",
      error: null,
    });
  const [deletionState, setDeletionState] =
    useState<RuntimeProfileDeletionState>({
      type: "CLOSED",
    });
  const [deletionFeedbackState, setDeletionFeedbackState] =
    useState<RuntimeProfileDeletionFeedbackState>({ type: "NONE" });
  const [operationId, setOperationId] = useState<string | null>(null);

  const memberQuery = trpc.workspaceMember.me.useQuery({ handle });
  const profilesQuery = trpc.runtimeProfile.list.useQuery({
    handle,
    includeDisabled: true,
  });
  const infrastructureProfilesQuery =
    trpc.runtimeProfile.listInfrastructureProfiles.useQuery({ handle });
  const defaultQuery = trpc.runtimeProfile.getDefault.useQuery({ handle });
  const operationQuery = trpc.runtimeProfile.getRecreation.useQuery(
    { handle, operationId: operationId ?? "" },
    {
      enabled: operationId !== null,
      refetchInterval: (query) => {
        const operation = query.state.data;
        return operation?.status === "pending" ||
          operation?.status === "running"
          ? 2000
          : false;
      },
    },
  );

  const canManage =
    memberQuery.data?.role === "owner" || memberQuery.data?.role === "manager";
  const canDelete = memberQuery.data?.role === "owner";

  const state: RuntimeProfilesState = useMemo(() => {
    if (
      profilesQuery.isLoading ||
      infrastructureProfilesQuery.isLoading ||
      defaultQuery.isLoading
    ) {
      return { type: "LOADING" };
    }
    if (
      profilesQuery.isError ||
      infrastructureProfilesQuery.isError ||
      defaultQuery.isError ||
      !profilesQuery.data ||
      !infrastructureProfilesQuery.data ||
      !defaultQuery.data
    ) {
      return {
        type: "ERROR",
        message:
          profilesQuery.error?.message ??
          infrastructureProfilesQuery.error?.message ??
          defaultQuery.error?.message ??
          "Failed to load Runtime Profiles.",
      };
    }
    return {
      type: "READY",
      profiles: profilesQuery.data.items,
      infrastructureProfiles: infrastructureProfilesQuery.data.items,
      defaultProfile: defaultQuery.data,
    };
  }, [
    defaultQuery.data,
    defaultQuery.error?.message,
    defaultQuery.isError,
    defaultQuery.isLoading,
    infrastructureProfilesQuery.data,
    infrastructureProfilesQuery.error?.message,
    infrastructureProfilesQuery.isError,
    infrastructureProfilesQuery.isLoading,
    profilesQuery.data,
    profilesQuery.error?.message,
    profilesQuery.isError,
    profilesQuery.isLoading,
  ]);

  const operationState: RuntimeProfileOperationState =
    operationId === null
      ? { type: "IDLE" }
      : operationQuery.isLoading
        ? { type: "LOADING" }
        : operationQuery.isError
          ? { type: "ERROR", message: operationQuery.error.message }
          : operationQuery.data
            ? { type: "LOADED", operation: operationQuery.data }
            : { type: "LOADING" };

  const invalidateProfiles = useCallback(async (): Promise<void> => {
    await Promise.all([
      utils.runtimeProfile.list.invalidate({
        handle,
        includeDisabled: true,
      }),
      utils.runtimeProfile.getDefault.invalidate({ handle }),
    ]);
  }, [handle, utils.runtimeProfile.getDefault, utils.runtimeProfile.list]);

  const createMutation = trpc.runtimeProfile.create.useMutation({
    onSuccess: async () => {
      setEditorState({ type: "CLOSED" });
      setMutationState({ type: "IDLE", error: null });
      await invalidateProfiles();
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });
  const replaceMutation = trpc.runtimeProfile.replace.useMutation({
    onSuccess: async () => {
      setEditorState({ type: "CLOSED" });
      setMutationState({ type: "IDLE", error: null });
      await invalidateProfiles();
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });
  const replaceDefaultMutation = trpc.runtimeProfile.replaceDefault.useMutation(
    {
      onSuccess: async () => {
        setMutationState({ type: "IDLE", error: null });
        await utils.runtimeProfile.getDefault.invalidate({ handle });
      },
      onError: (error) => {
        setMutationState({ type: "IDLE", error: error.message });
      },
    },
  );
  const recreationMutation = trpc.runtimeProfile.createRecreation.useMutation({
    onSuccess: (operation) => {
      setOperationId(operation.id);
      setMutationState({ type: "IDLE", error: null });
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });
  const deleteMutation = trpc.runtimeProfile.delete.useMutation();

  const onOpenCreate = useCallback((): void => {
    setEditorState({ type: "CREATE" });
    setMutationState({ type: "IDLE", error: null });
  }, []);
  const onOpenEdit = useCallback(
    (profile: WorkspaceRuntimeProfileResponse): void => {
      setEditorState({ type: "EDIT", profile });
      setMutationState({ type: "IDLE", error: null });
    },
    [],
  );
  const onCloseEditor = useCallback((): void => {
    setEditorState({ type: "CLOSED" });
    setMutationState({ type: "IDLE", error: null });
  }, []);
  const onSubmit = useCallback(
    (values: RuntimeProfileFormValues): void => {
      const policy = runtimeProfileMutationPolicy(values);
      setMutationState({ type: "SUBMITTING" });
      if (editorState.type === "EDIT") {
        replaceMutation.mutate({
          handle,
          profileId: editorState.profile.id,
          expectedVersion: editorState.profile.version,
          infrastructureProfileId: values.infrastructureProfileId,
          displayName: values.displayName,
          description: values.description,
          lifecycle: values.lifecycle,
          policy,
        });
        return;
      }
      if (editorState.type === "CREATE") {
        createMutation.mutate({
          handle,
          infrastructureProfileId: values.infrastructureProfileId,
          displayName: values.displayName,
          description: values.description,
          lifecycle: values.lifecycle,
          policy,
        });
      }
    },
    [createMutation, editorState, handle, replaceMutation],
  );
  const onSetDefault = useCallback(
    (profileId: string | null): void => {
      if (state.type !== "READY") {
        return;
      }
      setMutationState({ type: "SUBMITTING" });
      replaceDefaultMutation.mutate({
        handle,
        expectedVersion: state.defaultProfile.version,
        profileId,
      });
    },
    [handle, replaceDefaultMutation, state],
  );
  const onRecreate = useCallback(
    (profile: WorkspaceRuntimeProfileResponse): void => {
      setMutationState({ type: "SUBMITTING" });
      recreationMutation.mutate({
        handle,
        profileId: profile.id,
        expectedVersion: profile.version,
      });
    },
    [handle, recreationMutation],
  );
  const onOpenDelete = useCallback(
    (profile: WorkspaceRuntimeProfileResponse): void => {
      if (!canDelete) {
        return;
      }
      setDeletionFeedbackState({ type: "NONE" });
      setDeletionState({ type: "CONFIRMING", profile, error: null });
    },
    [canDelete],
  );
  const onCloseDelete = useCallback((): void => {
    setDeletionState((current) =>
      current.type === "SUBMITTING" ? current : { type: "CLOSED" },
    );
  }, []);
  const onConfirmDelete = useCallback(
    (profile: WorkspaceRuntimeProfileResponse): void => {
      if (!canDelete) {
        return;
      }
      setDeletionState({ type: "SUBMITTING", profile });
      deleteMutation.mutate(
        {
          handle,
          profileId: profile.id,
          expectedVersion: profile.version,
        },
        {
          onSuccess: (result): void => {
            setDeletionFeedbackState({
              type: "SUCCESS",
              profileName: profile.display_name,
              result,
            });
            setDeletionState({ type: "CLOSED" });
            void invalidateProfiles();
          },
          onError: (error): void => {
            const kind = deletionErrorKind(error);
            setDeletionState({
              type: "CONFIRMING",
              profile,
              error: {
                kind,
                message: error.message,
              },
            });
            if (kind === "CONFLICT" || kind === "NOT_FOUND") {
              void invalidateProfiles();
            }
          },
        },
      );
    },
    [canDelete, deleteMutation, handle, invalidateProfiles],
  );
  const onDismissDeletionFeedback = useCallback((): void => {
    setDeletionFeedbackState({ type: "NONE" });
  }, []);

  return {
    handle,
    state,
    editorState,
    mutationState,
    operationState,
    deletionState,
    deletionFeedbackState,
    canManage,
    canDelete,
    onOpenCreate,
    onOpenEdit,
    onCloseEditor,
    onSubmit,
    onSetDefault,
    onRecreate,
    onOpenDelete,
    onCloseDelete,
    onConfirmDelete,
    onDismissDeletionFeedback,
  };
}
