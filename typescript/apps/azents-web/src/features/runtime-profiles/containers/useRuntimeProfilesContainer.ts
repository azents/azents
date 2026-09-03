"use client";

import { useForm, type UseFormReturnType } from "@mantine/form";
import { useCallback, useEffect, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  policySchemaVersionForInfrastructure,
  proxyDomainModeForInfrastructure,
  runtimeProfileMutationPolicy,
} from "../runtimeProfilePolicy";
import { runtimeProfileFormSchema } from "../schemas";
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
  form?: UseFormReturnType<RuntimeProfileFormValues>;
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

function cidrsToText(cidrs?: string[]): string {
  return cidrs?.join("\n") ?? "";
}

function networkModeForProfile(
  editorState: RuntimeProfileEditorState,
): RuntimeProfileFormValues["networkMode"] {
  if (editorState.type !== "EDIT") {
    return "inherit";
  }
  const policy = editorState.profile.policy;
  if (policy.schema_version === 1) {
    return policy.network_restriction === null ? "inherit" : "direct";
  }
  return policy.network_restriction.mode;
}

function networkFieldsForProfile(
  editorState: RuntimeProfileEditorState,
): Pick<
  RuntimeProfileFormValues,
  | "allowedCidrs"
  | "deniedCidrs"
  | "proxyDomainMode"
  | "allowedDomains"
  | "deniedDomains"
> {
  if (editorState.type !== "EDIT") {
    return {
      allowedCidrs: "",
      deniedCidrs: "",
      proxyDomainMode: "unrestricted",
      allowedDomains: "",
      deniedDomains: "",
    };
  }
  const restriction = editorState.profile.policy.network_restriction;
  if (
    restriction === null ||
    ("mode" in restriction &&
      (restriction.mode === "inherit" || restriction.mode === "no_network"))
  ) {
    return {
      allowedCidrs: "",
      deniedCidrs: "",
      proxyDomainMode: "unrestricted",
      allowedDomains: "",
      deniedDomains: "",
    };
  }
  return {
    allowedCidrs: cidrsToText(restriction.allowed_cidrs),
    deniedCidrs: cidrsToText(restriction.denied_cidrs),
    proxyDomainMode:
      "domain_policy" in restriction
        ? restriction.domain_policy.mode
        : "unrestricted",
    allowedDomains:
      "domain_policy" in restriction
        ? cidrsToText(restriction.domain_policy.allowed_domains)
        : "",
    deniedDomains:
      "domain_policy" in restriction
        ? cidrsToText(restriction.domain_policy.denied_domains)
        : "",
  };
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
  const form = useForm<RuntimeProfileFormValues>({
    mode: "controlled",
    initialValues: {
      displayName: "",
      description: "",
      infrastructureProfileId: "",
      lifecycle: "active",
      terminalEnabled: true,
      policySchemaVersion: 2,
      networkMode: "inherit",
      allowedCidrs: "",
      deniedCidrs: "",
      proxyDomainMode: "unrestricted",
      allowedDomains: "",
      deniedDomains: "",
    },
    validate: (values) => {
      const result = runtimeProfileFormSchema.safeParse(values);
      if (result.success) {
        return {};
      }
      return Object.fromEntries(
        result.error.issues.map((issue) => [
          issue.path.join("."),
          issue.message,
        ]),
      );
    },
  });

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

  useEffect(() => {
    if (editorState.type === "EDIT") {
      const selectedInfrastructure =
        infrastructureProfilesQuery.data?.items.find(
          (profile) =>
            profile.id === editorState.profile.infrastructure_profile_id,
        );
      const infrastructureNetwork =
        selectedInfrastructure?.infrastructure_network ??
        editorState.profile.infrastructure_network;
      const networkFields = networkFieldsForProfile(editorState);
      form.setValues({
        displayName: editorState.profile.display_name,
        description: editorState.profile.description,
        infrastructureProfileId: editorState.profile.infrastructure_profile_id,
        lifecycle: editorState.profile.lifecycle,
        terminalEnabled: editorState.profile.terminal_enabled,
        policySchemaVersion: editorState.profile.policy.schema_version,
        networkMode: networkModeForProfile(editorState),
        ...networkFields,
        proxyDomainMode:
          infrastructureNetwork?.domain_mode === "allowlist"
            ? "allowlist"
            : networkFields.proxyDomainMode,
      });
      form.resetDirty();
      return;
    }
    if (editorState.type === "CREATE") {
      const initialInfrastructure = infrastructureProfilesQuery.data?.items[0];
      form.setValues({
        displayName: "",
        description: "",
        infrastructureProfileId: initialInfrastructure?.id ?? "",
        lifecycle: "active",
        terminalEnabled: true,
        policySchemaVersion: initialInfrastructure
          ? policySchemaVersionForInfrastructure(initialInfrastructure)
          : 2,
        networkMode: "inherit",
        allowedCidrs: "",
        deniedCidrs: "",
        proxyDomainMode: proxyDomainModeForInfrastructure(
          initialInfrastructure?.infrastructure_network ?? null,
        ),
        allowedDomains: "",
        deniedDomains: "",
      });
      form.resetDirty();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the editor target changes.
  }, [editorState]);

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
          terminalEnabled: values.terminalEnabled,
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
          terminalEnabled: values.terminalEnabled,
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
    form,
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
