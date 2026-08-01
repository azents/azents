"use client";

/** State and mutations for the focused LLM integrations settings page. */

import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  CreateIntegrationInput,
  FormModalState,
  LlmIntegrationListState,
  MutationState,
  UpdateIntegrationInput,
} from "../types";
import type { LlmProviderIntegrationResponse } from "@azents/public-client";

export interface LlmIntegrationsContainerProps {
  handle: string;
}

export interface LlmIntegrationsContainerOutput {
  handle: string;
  listState: LlmIntegrationListState;
  formModal: FormModalState;
  mutationState: MutationState;
  canManage: boolean;
  availableProviderValues: string[];
  onOpenCreate: () => void;
  onOpenEdit: (integration: LlmProviderIntegrationResponse) => void;
  onCloseModal: () => void;
  onCreate: (data: CreateIntegrationInput) => void;
  onUpdate: (data: UpdateIntegrationInput) => void;
  onDelete: (integrationId: string) => void;
  onToggleEnabled: (
    integration: LlmProviderIntegrationResponse,
    enabled: boolean,
  ) => void;
}

export function useLlmIntegrationsContainer(
  props: LlmIntegrationsContainerProps,
): LlmIntegrationsContainerOutput {
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
  const listQuery = trpc.llmProviderIntegration.list.useQuery({ handle });
  const providerCapabilitiesQuery =
    trpc.llmProviderIntegration.listProviders.useQuery({ handle });
  const canManage = meQuery.data?.role === "owner";
  const integrations = useMemo(
    () => listQuery.data?.items ?? [],
    [listQuery.data],
  );
  const listState: LlmIntegrationListState = useMemo(() => {
    if (listQuery.isLoading || providerCapabilitiesQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (listQuery.isError || providerCapabilitiesQuery.isError) {
      return { type: "ERROR" };
    }
    return { type: "READY", integrations };
  }, [
    integrations,
    listQuery.isError,
    listQuery.isLoading,
    providerCapabilitiesQuery.isError,
    providerCapabilitiesQuery.isLoading,
  ]);
  const availableProviderValues = useMemo(
    () =>
      providerCapabilitiesQuery.data?.items.map((item) => item.provider) ?? [],
    [providerCapabilitiesQuery.data],
  );

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
    (data: CreateIntegrationInput): void => {
      setMutationState({ type: "SUBMITTING" });
      createMutation.mutate({
        handle,
        provider: data.provider,
        ...(data.name ? { name: data.name } : {}),
        secrets: data.secrets,
        config: data.config ?? null,
      });
    },
    [createMutation, handle],
  );
  const onUpdate = useCallback(
    (data: UpdateIntegrationInput): void => {
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
    [formModal, handle, updateMutation],
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

  return {
    handle,
    listState,
    formModal,
    mutationState,
    canManage,
    availableProviderValues,
    onOpenCreate,
    onOpenEdit,
    onCloseModal,
    onCreate,
    onUpdate,
    onDelete,
    onToggleEnabled,
  };
}
