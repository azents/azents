"use client";

/**
 * LLM Settings container hook.
 *
 * Handles LLM Provider Integration list fetch, CRUD callbacks, and workspace default model settings.
 */

import { useCallback, useMemo, useState } from "react";
import {
  buildProviderIntegrationOptions,
  fallbackSelectableModelLabel,
  selectableModelOptionInputsFromFormValues,
} from "@/features/agents/model-selection";
import { trpc } from "@/trpc/client";
import type {
  FormModalState,
  IntegrationListState,
  MutationState,
} from "../types";
import type {
  ModelCatalogState,
  ModelSelectionOption,
  ProviderIntegrationOption,
  SelectableModelOptionFormValue,
} from "@/features/agents/model-selection";
import type { LlmProviderIntegrationResponse } from "@azents/public-client";

type ApiKeySecrets = { type: "api_key"; api_key: string };
type AwsSecrets = {
  type: "aws_credentials";
  secret_access_key: string;
};
type GcpSecrets = {
  type: "gcp_service_account";
  service_account_json: string;
};
type ProviderSecrets = ApiKeySecrets | AwsSecrets | GcpSecrets;

type AwsConfig = {
  type: "aws_credentials";
  access_key_id: string;
  region: string;
};
type GcpConfig = {
  type: "gcp_service_account";
  project_id: string;
  region: string;
};
type ProviderConfig = AwsConfig | GcpConfig;

export interface LlmSettingsContainerProps {
  handle: string;
}

export interface LlmSettingsContainerOutput {
  handle: string;
  listState: IntegrationListState;
  formModal: FormModalState;
  mutationState: MutationState;
  canManage: boolean;
  providerOptions: ProviderIntegrationOption[];
  availableProviderValues: string[];
  modelOptions: ModelSelectionOption[];
  catalogStates: ReadonlyMap<string, ModelCatalogState>;
  modelsLoading: boolean;
  onOpenCreate: () => void;
  onOpenEdit: (integration: LlmProviderIntegrationResponse) => void;
  onCloseModal: () => void;
  onCreate: (data: {
    provider: string;
    name?: string;
    secrets: ProviderSecrets;
    config?: ProviderConfig | null;
  }) => void;
  onUpdate: (data: {
    name?: string;
    secrets?: ProviderSecrets;
    config?: ProviderConfig | null;
    enabled?: boolean;
  }) => void;
  onDelete: (integrationId: string) => void;
  onToggleEnabled: (
    integration: LlmProviderIntegrationResponse,
    enabled: boolean,
  ) => void;
  onSyncCatalog: (integrationId: string) => Promise<void>;
  onUpdateWorkspaceModelSettings: (data: {
    defaultSelectableModelOptions: SelectableModelOptionFormValue[];
    defaultMainModelLabel: string | null;
    defaultLightweightModelLabel: string | null;
  }) => void;
}

export function useLlmSettingsContainer(
  props: LlmSettingsContainerProps,
): LlmSettingsContainerOutput {
  const { handle } = props;

  const [formModal, setFormModal] = useState<FormModalState>({
    type: "CLOSED",
  });
  const [mutationState, setMutationState] = useState<MutationState>({
    type: "IDLE",
    error: null,
  });

  const utils = trpc.useUtils();

  const meQuery = trpc.workspaceMember.me.useQuery({ handle });
  const canManage = meQuery.data?.role === "owner";

  const listQuery = trpc.llmProviderIntegration.list.useQuery({ handle });
  const providerCapabilitiesQuery =
    trpc.llmProviderIntegration.listProviders.useQuery({ handle });
  const workspaceModelSettingsQuery = trpc.workspaceModelSettings.get.useQuery({
    handle,
  });
  const integrations = useMemo(
    () => listQuery.data?.items ?? [],
    [listQuery.data],
  );
  const listState: IntegrationListState = useMemo(() => {
    if (
      listQuery.isLoading ||
      providerCapabilitiesQuery.isLoading ||
      workspaceModelSettingsQuery.isLoading
    ) {
      return { type: "LOADING" };
    }
    if (
      listQuery.isError ||
      providerCapabilitiesQuery.isError ||
      workspaceModelSettingsQuery.isError
    ) {
      return { type: "ERROR" };
    }
    return {
      type: "READY",
      integrations,
      workspaceModelSettings: workspaceModelSettingsQuery.data ?? null,
    };
  }, [
    listQuery.isLoading,
    listQuery.isError,
    providerCapabilitiesQuery.isLoading,
    providerCapabilitiesQuery.isError,
    integrations,
    workspaceModelSettingsQuery.isLoading,
    workspaceModelSettingsQuery.isError,
    workspaceModelSettingsQuery.data,
  ]);

  const catalogStates = useMemo(() => new Map<string, ModelCatalogState>(), []);

  const providerOptions = useMemo(
    () => buildProviderIntegrationOptions(integrations),
    [integrations],
  );

  const availableProviderValues = useMemo(
    () =>
      providerCapabilitiesQuery.data?.items.map((item) => item.provider) ?? [],
    [providerCapabilitiesQuery.data],
  );

  const modelOptions = useMemo<ModelSelectionOption[]>(() => [], []);

  const modelsLoading = false;

  const createMutation = trpc.llmProviderIntegration.create.useMutation({
    onSuccess: () => {
      setFormModal({ type: "CLOSED" });
      setMutationState({ type: "IDLE", error: null });
      void utils.llmProviderIntegration.list.invalidate({ handle });
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });

  const updateMutation = trpc.llmProviderIntegration.update.useMutation({
    onSuccess: () => {
      setFormModal({ type: "CLOSED" });
      setMutationState({ type: "IDLE", error: null });
      void utils.llmProviderIntegration.list.invalidate({ handle });
      void utils.workspaceModelSettings.get.invalidate({ handle });
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });

  const removeMutation = trpc.llmProviderIntegration.remove.useMutation({
    onSuccess: () => {
      void utils.llmProviderIntegration.list.invalidate({ handle });
      void utils.workspaceModelSettings.get.invalidate({ handle });
    },
  });

  const syncCatalogMutation =
    trpc.llmProviderIntegration.syncCatalog.useMutation({
      onSuccess: () => {
        void utils.llmProviderIntegration.list.invalidate({ handle });
        void utils.llmProviderIntegration.listModels.invalidate();
      },
    });

  const updateWorkspaceModelSettingsMutation =
    trpc.workspaceModelSettings.update.useMutation({
      onSuccess: () => {
        setMutationState({ type: "IDLE", error: null });
        void utils.workspaceModelSettings.get.invalidate({ handle });
        void utils.agent.list.invalidate({ handle });
      },
      onError: (error) =>
        setMutationState({ type: "IDLE", error: error.message }),
    });

  const onOpenCreate = useCallback((): void => {
    setFormModal({ type: "CREATE" });
    setMutationState({ type: "IDLE", error: null });
  }, []);

  const onOpenEdit = useCallback(
    (integration: LlmProviderIntegrationResponse): void => {
      setFormModal({ type: "EDIT", integration });
      setMutationState({ type: "IDLE", error: null });
    },
    [],
  );

  const onCloseModal = useCallback((): void => {
    setFormModal({ type: "CLOSED" });
    setMutationState({ type: "IDLE", error: null });
  }, []);

  const onCreate = useCallback(
    (data: {
      provider: string;
      name?: string;
      secrets: ProviderSecrets;
      config?: ProviderConfig | null;
    }): void => {
      setMutationState({ type: "SUBMITTING" });
      createMutation.mutate({
        handle,
        provider: data.provider,
        ...(data.name ? { name: data.name } : {}),
        secrets: data.secrets,
        config: data.config ?? null,
      });
    },
    [handle, createMutation],
  );

  const onUpdate = useCallback(
    (data: {
      name?: string;
      secrets?: ProviderSecrets;
      config?: ProviderConfig | null;
      enabled?: boolean;
    }): void => {
      if (formModal.type !== "EDIT") {
        return;
      }
      setMutationState({ type: "SUBMITTING" });
      updateMutation.mutate({
        handle,
        integrationId: formModal.integration.id,
        ...data,
      });
    },
    [handle, formModal, updateMutation],
  );

  const onDelete = useCallback(
    (integrationId: string): void => {
      removeMutation.mutate({ handle, integrationId });
    },
    [handle, removeMutation],
  );

  const onToggleEnabled = useCallback(
    (integration: LlmProviderIntegrationResponse, enabled: boolean): void => {
      updateMutation.mutate({
        handle,
        integrationId: integration.id,
        enabled,
      });
    },
    [handle, updateMutation],
  );

  const onSyncCatalog = useCallback(
    async (integrationId: string): Promise<void> => {
      await syncCatalogMutation.mutateAsync({ handle, integrationId });
    },
    [handle, syncCatalogMutation],
  );

  const onUpdateWorkspaceModelSettings = useCallback(
    (data: {
      defaultSelectableModelOptions: SelectableModelOptionFormValue[];
      defaultMainModelLabel: string | null;
      defaultLightweightModelLabel: string | null;
    }): void => {
      setMutationState({ type: "SUBMITTING" });
      updateWorkspaceModelSettingsMutation.mutate({
        handle,
        default_selectable_model_options:
          selectableModelOptionInputsFromFormValues(
            data.defaultSelectableModelOptions,
          ),
        default_main_model_label: fallbackSelectableModelLabel(
          data.defaultMainModelLabel,
          data.defaultSelectableModelOptions,
        ),
        default_lightweight_model_label: fallbackSelectableModelLabel(
          data.defaultLightweightModelLabel,
          data.defaultSelectableModelOptions,
        ),
      });
    },
    [handle, updateWorkspaceModelSettingsMutation],
  );

  return {
    handle,
    listState,
    formModal,
    mutationState,
    canManage,
    providerOptions,
    availableProviderValues,
    modelOptions,
    catalogStates,
    modelsLoading,
    onOpenCreate,
    onOpenEdit,
    onCloseModal,
    onCreate,
    onUpdate,
    onDelete,
    onToggleEnabled,
    onSyncCatalog,
    onUpdateWorkspaceModelSettings,
  };
}
