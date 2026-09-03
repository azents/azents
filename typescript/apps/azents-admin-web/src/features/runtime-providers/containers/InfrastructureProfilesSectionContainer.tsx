"use client";

import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useConfig } from "@/config/client";
import { trpc } from "@/trpc/client";
import {
  blankValues,
  InfrastructureProfilesSection,
  resourceUnitsForValues,
  valuesFromProfile,
} from "../components/InfrastructureProfilesSection";
import {
  infrastructureProfileDeletionConfirmationEnabled,
  infrastructureProfileDeletionFailureMessage,
  nextDeletionReferenceOffset,
  previousDeletionReferenceOffset,
} from "../infrastructureProfileDeletion";
import { infrastructureProfileKindForProvider } from "../runtimeProviderPresentation";
import type {
  InfrastructureProfileFormUnits,
  InfrastructureProfileFormValues,
} from "../components/InfrastructureProfilesSection";
import type { InfrastructureProfileKind } from "../runtimeProviderPresentation";
import type {
  RuntimeInfrastructureProfileDeletionImpactResponse,
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

export type InfrastructureProfileDeletionState =
  | { type: "CLOSED" }
  | { type: "LOADING"; profile: RuntimeInfrastructureProfileResponse }
  | {
      type: "READY";
      profile: RuntimeInfrastructureProfileResponse;
      impact: RuntimeInfrastructureProfileDeletionImpactResponse;
    }
  | {
      type: "BLOCKED";
      profile: RuntimeInfrastructureProfileResponse;
      impact: RuntimeInfrastructureProfileDeletionImpactResponse;
    }
  | {
      type: "IMPACT_ERROR";
      profile: RuntimeInfrastructureProfileResponse;
      message: string;
    }
  | {
      type: "DELETING";
      profile: RuntimeInfrastructureProfileResponse;
      impact: RuntimeInfrastructureProfileDeletionImpactResponse;
    }
  | {
      type: "DELETE_ERROR";
      profile: RuntimeInfrastructureProfileResponse;
      impact: RuntimeInfrastructureProfileDeletionImpactResponse;
      message: string;
    };

export interface InfrastructureProfileSubmission {
  displayName: string;
  description: string;
  lifecycle: RuntimeProfileLifecycle;
  terminalEnabled: boolean;
  spec: RuntimeInfrastructureProfileSpec;
}

export interface InfrastructureProfilesSectionProps {
  profileKind: InfrastructureProfileKind | null;
  state: InfrastructureProfilesState;
  editorState: InfrastructureProfileEditorState;
  operationState: InfrastructureProfileOperationState;
  deletionState: InfrastructureProfileDeletionState;
  submitting: boolean;
  errorMessage: string | null;
  onOpenCreate: () => void;
  onOpenEdit: (profile: RuntimeInfrastructureProfileResponse) => void;
  onCloseEditor: () => void;
  onSubmit: (submission: InfrastructureProfileSubmission) => void;
  onRecreate: (profile: RuntimeInfrastructureProfileResponse) => void;
  onRecreateProvider: () => void;
  onOpenDelete: (profile: RuntimeInfrastructureProfileResponse) => void;
  onCloseDeletion: () => void;
  onRetryDeletionImpact: () => void;
  onPreviousDeletionReferences: () => void;
  onNextDeletionReferences: () => void;
  onConfirmDeletion: () => void;
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
  const { publicBaseUrl } = useConfig();
  const utils = trpc.useUtils();
  const [editorState, setEditorState] =
    useState<InfrastructureProfileEditorState>({ type: "CLOSED" });
  const [operationId, setOperationId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [selectedDeletionProfile, setSelectedDeletionProfile] =
    useState<RuntimeInfrastructureProfileResponse | null>(null);
  const [deletionError, setDeletionError] = useState<string | null>(null);
  const [deletionOffset, setDeletionOffset] = useState(0);
  const [deletionImpactRefreshToken, setDeletionImpactRefreshToken] =
    useState(0);
  const [deletionImpactRefreshPending, setDeletionImpactRefreshPending] =
    useState(false);
  const editorForm = useForm<InfrastructureProfileFormValues>({
    mode: "controlled",
    initialValues: blankValues(profileKind ?? "kubernetes_pod"),
    validate: {
      displayName: (value) => (value.trim() ? null : "Name is required."),
      storageClassName: (value) =>
        profileKind === "kubernetes_pod" && !value.trim()
          ? "Storage class is required."
          : null,
      nodeSelector: (value) =>
        value
          .split(/\r?\n/)
          .map((line) => line.trim())
          .filter(Boolean)
          .some((line) => !line.includes("="))
          ? "Use one key=value selector per line."
          : null,
      tolerations: (value) =>
        value
          .split(/\r?\n/)
          .map((line) => line.trim())
          .filter(Boolean)
          .some((line) => line.split("|").length < 2)
          ? "Use key|operator|value|effect|seconds."
          : null,
    },
  });
  const [editorUnits, setEditorUnits] =
    useState<InfrastructureProfileFormUnits>(() =>
      resourceUnitsForValues(blankValues(profileKind ?? "kubernetes_pod")),
    );

  useEffect(() => {
    if (profileKind === null) {
      return;
    }
    const nextValues =
      editorState.type === "EDIT"
        ? valuesFromProfile(editorState.profile)
        : blankValues(profileKind);
    editorForm.setValues(nextValues);
    setEditorUnits(resourceUnitsForValues(nextValues));
    editorForm.resetDirty();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when the selected editor target or Provider kind changes.
  }, [editorState, profileKind]);

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
  const deletionImpactQuery =
    trpc.runtimeProvider.getInfrastructureProfileDeletionImpact.useQuery(
      {
        providerId,
        profileId: selectedDeletionProfile?.id ?? "",
        profileKind: profileKind ?? "kubernetes_pod",
        offset: deletionOffset,
        limit: 50,
      },
      {
        enabled: false,
        retry: false,
      },
    );
  const refetchDeletionImpact = deletionImpactQuery.refetch;

  useEffect(() => {
    if (selectedDeletionProfile === null || profileKind === null) {
      return;
    }
    let active = true;
    setDeletionImpactRefreshPending(true);
    void refetchDeletionImpact().finally(() => {
      if (active) {
        setDeletionImpactRefreshPending(false);
      }
    });
    return () => {
      active = false;
    };
  }, [
    deletionImpactRefreshToken,
    deletionOffset,
    profileKind,
    refetchDeletionImpact,
    selectedDeletionProfile,
  ]);

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
  const deleteMutation =
    trpc.runtimeProvider.deleteInfrastructureProfile.useMutation({
      onSuccess: async () => {
        const deletedProfile = selectedDeletionProfile;
        setSelectedDeletionProfile(null);
        setDeletionError(null);
        setDeletionImpactRefreshPending(false);
        notifications.show({
          color: "green",
          title: "Profile deleted",
          message:
            deletedProfile === null
              ? "The infrastructure Profile was permanently deleted."
              : `${deletedProfile.display_name} was permanently deleted.`,
        });
        await invalidateProfiles();
      },
      onError: async (error) => {
        setDeletionError(
          infrastructureProfileDeletionFailureMessage(error.message),
        );
        setDeletionOffset(0);
        setDeletionImpactRefreshPending(true);
        setDeletionImpactRefreshToken((value) => value + 1);
        await invalidateProfiles();
      },
    });

  const deletionState: InfrastructureProfileDeletionState = useMemo(() => {
    if (selectedDeletionProfile === null) {
      return { type: "CLOSED" };
    }
    if (deleteMutation.isPending && deletionImpactQuery.data != null) {
      return {
        type: "DELETING",
        profile: selectedDeletionProfile,
        impact: deletionImpactQuery.data,
      };
    }
    if (deletionImpactRefreshPending || deletionImpactQuery.isFetching) {
      return { type: "LOADING", profile: selectedDeletionProfile };
    }
    if (deletionImpactQuery.isError) {
      return {
        type: "IMPACT_ERROR",
        profile: selectedDeletionProfile,
        message: deletionImpactQuery.error.message,
      };
    }
    if (deletionError !== null && deletionImpactQuery.data != null) {
      return {
        type: "DELETE_ERROR",
        profile: selectedDeletionProfile,
        impact: deletionImpactQuery.data,
        message: deletionError,
      };
    }
    if (deletionImpactQuery.data == null) {
      return { type: "LOADING", profile: selectedDeletionProfile };
    }
    if (deletionImpactQuery.data.blocking_reference_count > 0) {
      return {
        type: "BLOCKED",
        profile: selectedDeletionProfile,
        impact: deletionImpactQuery.data,
      };
    }
    return {
      type: "READY",
      profile: selectedDeletionProfile,
      impact: deletionImpactQuery.data,
    };
  }, [
    deleteMutation.isPending,
    deletionError,
    deletionImpactQuery.data,
    deletionImpactQuery.error?.message,
    deletionImpactQuery.isError,
    deletionImpactQuery.isFetching,
    deletionImpactRefreshPending,
    selectedDeletionProfile,
  ]);

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
          terminalEnabled: submission.terminalEnabled,
          spec: submission.spec,
        });
        return;
      }
      createMutation.mutate({
        providerId,
        displayName: submission.displayName,
        description: submission.description,
        lifecycle: submission.lifecycle,
        terminalEnabled: submission.terminalEnabled,
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
  const onOpenDelete = useCallback(
    (profile: RuntimeInfrastructureProfileResponse): void => {
      setSelectedDeletionProfile(profile);
      setDeletionError(null);
      setDeletionOffset(0);
      setDeletionImpactRefreshPending(true);
      setDeletionImpactRefreshToken((value) => value + 1);
    },
    [],
  );
  const onCloseDeletion = useCallback((): void => {
    if (!deleteMutation.isPending) {
      setSelectedDeletionProfile(null);
      setDeletionError(null);
      setDeletionOffset(0);
      setDeletionImpactRefreshPending(false);
    }
  }, [deleteMutation.isPending]);
  const onRetryDeletionImpact = useCallback((): void => {
    setDeletionError(null);
    setDeletionImpactRefreshPending(true);
    setDeletionImpactRefreshToken((value) => value + 1);
  }, []);
  const onPreviousDeletionReferences = useCallback((): void => {
    const impact = deletionImpactQuery.data;
    if (impact == null) {
      return;
    }
    setDeletionImpactRefreshPending(true);
    setDeletionOffset(
      previousDeletionReferenceOffset(impact.offset, impact.limit),
    );
  }, [deletionImpactQuery.data]);
  const onNextDeletionReferences = useCallback((): void => {
    const impact = deletionImpactQuery.data;
    if (impact == null) {
      return;
    }
    setDeletionImpactRefreshPending(true);
    setDeletionOffset(
      nextDeletionReferenceOffset(
        impact.offset,
        impact.limit,
        impact.references.length,
        impact.blocking_reference_count,
      ),
    );
  }, [deletionImpactQuery.data]);
  const onConfirmDeletion = useCallback((): void => {
    if (
      selectedDeletionProfile === null ||
      profileKind === null ||
      deletionImpactQuery.data == null ||
      !infrastructureProfileDeletionConfirmationEnabled({
        refreshPending:
          deletionImpactRefreshPending || deletionImpactQuery.isFetching,
        impactError: deletionImpactQuery.isError,
        blockingReferenceCount:
          deletionImpactQuery.data.blocking_reference_count,
      })
    ) {
      return;
    }
    setDeletionError(null);
    deleteMutation.mutate({
      providerId,
      profileId: selectedDeletionProfile.id,
      profileKind,
      expectedVersion: deletionImpactQuery.data.version,
    });
  }, [
    deleteMutation,
    deletionImpactQuery.data,
    deletionImpactQuery.isError,
    deletionImpactQuery.isFetching,
    deletionImpactRefreshPending,
    profileKind,
    providerId,
    selectedDeletionProfile,
  ]);
  const onSetEditorNumber = (
    field: keyof InfrastructureProfileFormValues,
    value: number | null,
  ): void => {
    editorForm.setFieldValue(field, value);
  };
  const onSetEditorUnit = (
    field: keyof InfrastructureProfileFormUnits,
    unit: string,
  ): void => {
    setEditorUnits((currentUnits) => ({ ...currentUnits, [field]: unit }));
  };

  return (
    <InfrastructureProfilesSection
      profileKind={profileKind}
      state={state}
      editorState={editorState}
      editorForm={editorForm}
      editorUnits={editorUnits}
      publicBaseUrl={publicBaseUrl}
      operationState={operationState}
      deletionState={deletionState}
      submitting={
        createMutation.isPending ||
        replaceMutation.isPending ||
        recreationMutation.isPending ||
        providerRecreationMutation.isPending ||
        deleteMutation.isPending
      }
      errorMessage={errorMessage}
      onOpenCreate={onOpenCreate}
      onOpenEdit={onOpenEdit}
      onCloseEditor={onCloseEditor}
      onSubmit={onSubmit}
      onRecreate={onRecreate}
      onRecreateProvider={onRecreateProvider}
      onOpenDelete={onOpenDelete}
      onCloseDeletion={onCloseDeletion}
      onRetryDeletionImpact={onRetryDeletionImpact}
      onPreviousDeletionReferences={onPreviousDeletionReferences}
      onNextDeletionReferences={onNextDeletionReferences}
      onConfirmDeletion={onConfirmDeletion}
      onSetEditorNumber={onSetEditorNumber}
      onSetEditorUnit={onSetEditorUnit}
    />
  );
}
