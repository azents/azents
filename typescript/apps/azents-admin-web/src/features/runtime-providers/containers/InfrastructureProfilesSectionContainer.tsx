"use client";

import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import { InfrastructureProfilesSection } from "../components/InfrastructureProfilesSection";
import { infrastructureProfileKindForProvider } from "../runtimeProviderPresentation";
import type { InfrastructureProfileKind } from "../runtimeProviderPresentation";
import type {
  RuntimeInfrastructureProfileResponse,
  RuntimeInfrastructureProfileSpec,
  RuntimeProfileLifecycle,
  RuntimeRecreationOperationResponse,
} from "@azents/admin-client";

export type InfrastructureProfilesState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; items: RuntimeInfrastructureProfileResponse[] };

export type InfrastructureProfileEditorState =
  | { type: "CLOSED" }
  | { type: "CREATE" }
  | { type: "EDIT"; profile: RuntimeInfrastructureProfileResponse };

export type InfrastructureProfileOperationState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; operation: RuntimeRecreationOperationResponse };

export interface InfrastructureProfileSubmission {
  displayName: string;
  description: string;
  lifecycle: RuntimeProfileLifecycle;
  spec: RuntimeInfrastructureProfileSpec;
}

export interface InfrastructureProfilesSectionProps {
  profileKind: InfrastructureProfileKind | null;
  state: InfrastructureProfilesState;
  editorState: InfrastructureProfileEditorState;
  operationState: InfrastructureProfileOperationState;
  submitting: boolean;
  errorMessage: string | null;
  onOpenCreate: () => void;
  onOpenEdit: (profile: RuntimeInfrastructureProfileResponse) => void;
  onCloseEditor: () => void;
  onSubmit: (submission: InfrastructureProfileSubmission) => void;
  onRecreate: (profile: RuntimeInfrastructureProfileResponse) => void;
  onRecreateProvider: () => void;
}

interface InfrastructureProfilesSectionContainerProps {
  providerId: string;
  providerKind: string;
  providerVersion: number;
}

export function InfrastructureProfilesSectionContainer({
  providerId,
  providerKind,
  providerVersion,
}: InfrastructureProfilesSectionContainerProps): React.ReactElement {
  const profileKind = infrastructureProfileKindForProvider(providerKind);
  const utils = trpc.useUtils();
  const [editorState, setEditorState] =
    useState<InfrastructureProfileEditorState>({ type: "CLOSED" });
  const [operationId, setOperationId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const profilesQuery =
    trpc.runtimeProvider.listInfrastructureProfiles.useQuery(
      {
        providerId,
        profileKind: profileKind ?? "kubernetes_pod",
      },
      { enabled: profileKind !== null },
    );
  const operationQuery = trpc.runtimeProvider.getRecreation.useQuery(
    { operationId: operationId ?? "" },
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

  const state: InfrastructureProfilesState = useMemo(() => {
    if (profileKind === null) {
      return { type: "IDLE" };
    }
    if (profilesQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (profilesQuery.isError) {
      return { type: "ERROR", message: profilesQuery.error.message };
    }
    return { type: "LOADED", items: profilesQuery.data?.items ?? [] };
  }, [
    profileKind,
    profilesQuery.data?.items,
    profilesQuery.error?.message,
    profilesQuery.isError,
    profilesQuery.isLoading,
  ]);

  const operationState: InfrastructureProfileOperationState =
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
    if (profileKind !== null) {
      await utils.runtimeProvider.listInfrastructureProfiles.invalidate({
        providerId,
        profileKind,
      });
    }
  }, [
    profileKind,
    providerId,
    utils.runtimeProvider.listInfrastructureProfiles,
  ]);

  const createMutation =
    trpc.runtimeProvider.createInfrastructureProfile.useMutation({
      onSuccess: async () => {
        setEditorState({ type: "CLOSED" });
        setErrorMessage(null);
        await invalidateProfiles();
      },
      onError: (error) => setErrorMessage(error.message),
    });
  const replaceMutation =
    trpc.runtimeProvider.replaceInfrastructureProfile.useMutation({
      onSuccess: async () => {
        setEditorState({ type: "CLOSED" });
        setErrorMessage(null);
        await invalidateProfiles();
      },
      onError: (error) => setErrorMessage(error.message),
    });
  const recreationMutation =
    trpc.runtimeProvider.createInfrastructureProfileRecreation.useMutation({
      onSuccess: (operation) => {
        setOperationId(operation.id);
        setErrorMessage(null);
      },
      onError: (error) => setErrorMessage(error.message),
    });
  const providerRecreationMutation =
    trpc.runtimeProvider.createProviderRecreation.useMutation({
      onSuccess: (operation) => {
        setOperationId(operation.id);
        setErrorMessage(null);
      },
      onError: (error) => setErrorMessage(error.message),
    });

  const onOpenCreate = useCallback((): void => {
    setEditorState({ type: "CREATE" });
    setErrorMessage(null);
  }, []);
  const onOpenEdit = useCallback(
    (profile: RuntimeInfrastructureProfileResponse): void => {
      setEditorState({ type: "EDIT", profile });
      setErrorMessage(null);
    },
    [],
  );
  const onCloseEditor = useCallback((): void => {
    setEditorState({ type: "CLOSED" });
    setErrorMessage(null);
  }, []);
  const onSubmit = useCallback(
    (submission: InfrastructureProfileSubmission): void => {
      if (editorState.type === "EDIT") {
        replaceMutation.mutate({
          providerId,
          profileId: editorState.profile.id,
          expectedVersion: editorState.profile.version,
          displayName: submission.displayName,
          description: submission.description,
          lifecycle: submission.lifecycle,
          spec: submission.spec,
        });
        return;
      }
      createMutation.mutate({
        providerId,
        displayName: submission.displayName,
        description: submission.description,
        lifecycle: submission.lifecycle,
        spec: submission.spec,
      });
    },
    [createMutation, editorState, providerId, replaceMutation],
  );
  const onRecreate = useCallback(
    (profile: RuntimeInfrastructureProfileResponse): void => {
      if (profileKind === null) {
        return;
      }
      recreationMutation.mutate({
        providerId,
        profileId: profile.id,
        profileKind,
        expectedVersion: profile.version,
      });
    },
    [profileKind, providerId, recreationMutation],
  );
  const onRecreateProvider = useCallback((): void => {
    providerRecreationMutation.mutate({
      providerId,
      expectedVersion: providerVersion,
    });
  }, [providerId, providerRecreationMutation, providerVersion]);

  return (
    <InfrastructureProfilesSection
      profileKind={profileKind}
      state={state}
      editorState={editorState}
      operationState={operationState}
      submitting={
        createMutation.isPending ||
        replaceMutation.isPending ||
        recreationMutation.isPending ||
        providerRecreationMutation.isPending
      }
      errorMessage={errorMessage}
      onOpenCreate={onOpenCreate}
      onOpenEdit={onOpenEdit}
      onCloseEditor={onCloseEditor}
      onSubmit={onSubmit}
      onRecreate={onRecreate}
      onRecreateProvider={onRecreateProvider}
    />
  );
}
