"use client";

/** State and mutations for the focused Workspace model settings page. */

import { useCallback, useMemo, useState } from "react";
import {
  buildProviderIntegrationOptions,
  fallbackSelectableModelLabel,
  selectableModelOptionInputsFromFormValues,
} from "@/features/agents/model-selection";
import { trpc } from "@/trpc/client";
import type { MutationState, WorkspaceModelSettingsState } from "../types";
import type {
  ProviderIntegrationOption,
  SelectableModelOptionFormValue,
} from "@/features/agents/model-selection";

export interface WorkspaceModelSettingsContainerProps {
  handle: string;
}

export interface WorkspaceModelSettingsContainerOutput {
  handle: string;
  state: WorkspaceModelSettingsState;
  mutationState: MutationState;
  canManage: boolean;
  providerOptions: ProviderIntegrationOption[];
  onSyncCatalog: (integrationId: string) => Promise<void>;
  onSubmit: (data: {
    defaultSelectableModelOptions: SelectableModelOptionFormValue[];
    defaultMainModelLabel: string | null;
    defaultLightweightModelLabel: string | null;
  }) => void;
}

export function useWorkspaceModelSettingsContainer(
  props: WorkspaceModelSettingsContainerProps,
): WorkspaceModelSettingsContainerOutput {
  const { handle } = props;
  const [mutationState, setMutationState] = useState<MutationState>({
    type: "IDLE",
    error: null,
  });
  const utils = trpc.useUtils();

  const meQuery = trpc.workspaceMember.me.useQuery({ handle });
  const listQuery = trpc.llmProviderIntegration.list.useQuery({ handle });
  const settingsQuery = trpc.workspaceModelSettings.get.useQuery({ handle });
  const integrations = useMemo(
    () => listQuery.data?.items ?? [],
    [listQuery.data],
  );
  const providerOptions = useMemo(
    () => buildProviderIntegrationOptions(integrations),
    [integrations],
  );
  const state: WorkspaceModelSettingsState = useMemo(() => {
    if (listQuery.isLoading || settingsQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (listQuery.isError || settingsQuery.isError) {
      return { type: "ERROR" };
    }
    return { type: "READY", settings: settingsQuery.data ?? null };
  }, [
    listQuery.isError,
    listQuery.isLoading,
    settingsQuery.data,
    settingsQuery.isError,
    settingsQuery.isLoading,
  ]);
  const canManage = meQuery.data?.role === "owner";

  const syncCatalogMutation =
    trpc.llmProviderIntegration.syncCatalog.useMutation({
      onSuccess: () => {
        void utils.llmProviderIntegration.list.invalidate({ handle });
        void utils.llmProviderIntegration.listModels.invalidate();
      },
    });
  const updateMutation = trpc.workspaceModelSettings.update.useMutation({
    onSuccess: () => {
      setMutationState({ type: "IDLE", error: null });
      void utils.workspaceModelSettings.get.invalidate({ handle });
      void utils.agent.list.invalidate({ handle });
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });

  const onSyncCatalog = useCallback(
    async (integrationId: string): Promise<void> => {
      await syncCatalogMutation.mutateAsync({ handle, integrationId });
    },
    [handle, syncCatalogMutation],
  );
  const onSubmit = useCallback(
    (data: {
      defaultSelectableModelOptions: SelectableModelOptionFormValue[];
      defaultMainModelLabel: string | null;
      defaultLightweightModelLabel: string | null;
    }): void => {
      setMutationState({ type: "SUBMITTING" });
      updateMutation.mutate({
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
    [handle, updateMutation],
  );

  return {
    handle,
    state,
    mutationState,
    canManage,
    providerOptions,
    onSyncCatalog,
    onSubmit,
  };
}
