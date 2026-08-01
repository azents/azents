"use client";

import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type { RuntimeProfileFormValues } from "../schemas";
import type {
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
  canManage: boolean;
  onOpenCreate: () => void;
  onOpenEdit: (profile: WorkspaceRuntimeProfileResponse) => void;
  onCloseEditor: () => void;
  onSubmit: (values: RuntimeProfileFormValues) => void;
  onSetDefault: (profileId: string | null) => void;
  onRecreate: (profile: WorkspaceRuntimeProfileResponse) => void;
}

function parseCidrs(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
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
      const allowedCidrs = parseCidrs(values.allowedCidrs);
      const deniedCidrs = parseCidrs(values.deniedCidrs);
      const networkPolicy =
        allowedCidrs.length === 0 && deniedCidrs.length === 0
          ? null
          : { allowedCidrs, deniedCidrs };
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
          networkPolicy,
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
          networkPolicy,
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

  return {
    handle,
    state,
    editorState,
    mutationState,
    operationState,
    canManage,
    onOpenCreate,
    onOpenEdit,
    onCloseEditor,
    onSubmit,
    onSetDefault,
    onRecreate,
  };
}
