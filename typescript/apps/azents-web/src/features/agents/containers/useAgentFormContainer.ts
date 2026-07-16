"use client";

/**
 * Agent create/update form container hook.
 *
 * Edit mode when agentId exists; create mode otherwise.
 * Handles model catalog fetch, form submit, and Admin management.
 */

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  buildProviderIntegrationOptions,
  fallbackSelectableModelLabel,
  modelSelectionValue,
  selectableModelOptionInputsFromFormValues,
} from "../model-selection";
import type {
  ModelCatalogState,
  ModelSelectionOption,
  ProviderIntegrationOption,
} from "../model-selection";
import type { AgentFormValues } from "../schemas";
import type { AdminListState, AgentFormState, MutationState } from "../types";
import type {
  AgentAdminResponse,
  LlmProviderIntegrationResponse,
  ModelParameters,
  WorkspaceModelSettingsResponse,
} from "@azents/public-client";

export interface AgentFormContainerProps {
  handle: string;
  agentId?: string;
  /** Path to navigate after successful save. Default is agent list (`/w/{handle}/agents`). */
  afterSavePath?: string;
}

/** Member list item type (based on tRPC workspace-member.list response) */
export interface MemberItem {
  id: string;
  name: string;
  role: string;
}

export interface AgentFormContainerOutput {
  handle: string;
  formState: AgentFormState;
  mutationState: MutationState;
  adminListState: AdminListState;
  integrations: LlmProviderIntegrationResponse[];
  providerOptions: ProviderIntegrationOption[];
  modelOptions: ModelSelectionOption[];
  workspaceModelSettings: WorkspaceModelSettingsResponse | null;
  catalogStates: ReadonlyMap<string, ModelCatalogState>;
  modelsLoading: boolean;
  members: MemberItem[];
  onSyncCatalog: (integrationId: string) => Promise<void>;
  onSubmit: (values: AgentFormValues) => void;
  onAddAdmin: (workspaceUserId: string) => void;
  onRemoveAdmin: (admin: AgentAdminResponse) => void;
}

function buildModelParameters(values: AgentFormValues): ModelParameters | null {
  if (values.reasoning_effort == null) {
    return null;
  }
  return { reasoning_effort: values.reasoning_effort };
}

export function useAgentFormContainer(
  props: AgentFormContainerProps,
): AgentFormContainerOutput {
  const { handle, agentId, afterSavePath } = props;
  const successPath = afterSavePath ?? `/w/${handle}/agents`;
  const router = useRouter();
  const utils = trpc.useUtils();

  const [mutationState, setMutationState] = useState<MutationState>({
    type: "IDLE",
    error: null,
  });

  const isEditMode = agentId != null;

  const agentQuery = trpc.agent.get.useQuery(
    { handle, agentId: agentId ?? "" },
    { enabled: isEditMode },
  );
  const integrationsQuery = trpc.llmProviderIntegration.list.useQuery({
    handle,
  });
  const workspaceModelSettingsQuery = trpc.workspaceModelSettings.get.useQuery({
    handle,
  });
  const membersQuery = trpc.workspaceMember.list.useQuery({ handle });
  const adminsQuery = trpc.agent.listAdmins.useQuery(
    { handle, agentId: agentId ?? "" },
    { enabled: isEditMode },
  );

  const formState: AgentFormState = useMemo(() => {
    if (!isEditMode) {
      return { type: "CREATE" };
    }
    if (agentQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (agentQuery.isError) {
      return { type: "NOT_FOUND" };
    }
    if (!agentQuery.data) {
      return { type: "NOT_FOUND" };
    }
    return { type: "EDIT", agent: agentQuery.data };
  }, [isEditMode, agentQuery.isLoading, agentQuery.isError, agentQuery.data]);

  const adminListState: AdminListState = useMemo(() => {
    if (!isEditMode) {
      return { type: "READY", admins: [] };
    }
    if (adminsQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (adminsQuery.isError) {
      return { type: "ERROR" };
    }
    return { type: "READY", admins: adminsQuery.data?.items ?? [] };
  }, [
    isEditMode,
    adminsQuery.isLoading,
    adminsQuery.isError,
    adminsQuery.data,
  ]);

  const integrations = useMemo(
    () => integrationsQuery.data?.items ?? [],
    [integrationsQuery.data],
  );

  const catalogStates = useMemo(() => new Map<string, ModelCatalogState>(), []);

  const providerOptions = useMemo(
    () => buildProviderIntegrationOptions(integrations),
    [integrations],
  );

  const modelOptions = useMemo<ModelSelectionOption[]>(() => [], []);

  const modelsLoading = integrationsQuery.isLoading;

  const members = useMemo(
    () => membersQuery.data?.items ?? [],
    [membersQuery.data],
  );

  const syncCatalogMutation =
    trpc.llmProviderIntegration.syncCatalog.useMutation({
      onSuccess: () => {
        void utils.llmProviderIntegration.list.invalidate({ handle });
        void utils.llmProviderIntegration.listModels.invalidate();
      },
    });

  const createMutation = trpc.agent.create.useMutation({
    onSuccess: () => {
      setMutationState({ type: "IDLE", error: null });
      void utils.agent.list.invalidate({ handle });
      router.push(successPath);
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });

  const updateMutation = trpc.agent.update.useMutation({
    onSuccess: () => {
      setMutationState({ type: "IDLE", error: null });
      void utils.agent.list.invalidate({ handle });
      if (agentId) {
        void utils.agent.get.invalidate({ handle, agentId });
      }
      router.push(successPath);
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });

  const addAdminMutation = trpc.agent.addAdmin.useMutation({
    onSuccess: () => {
      if (agentId) {
        void utils.agent.listAdmins.invalidate({ handle, agentId });
      }
    },
  });

  const removeAdminMutation = trpc.agent.removeAdmin.useMutation({
    onSuccess: () => {
      if (agentId) {
        void utils.agent.listAdmins.invalidate({ handle, agentId });
      }
    },
  });

  const onSubmit = useCallback(
    (values: AgentFormValues): void => {
      setMutationState({ type: "SUBMITTING" });
      const modelParameters = buildModelParameters(values);
      const selectableModelOptions = selectableModelOptionInputsFromFormValues(
        values.selectable_model_options,
      );
      const mainModelLabel = fallbackSelectableModelLabel(
        values.main_model_label,
        values.selectable_model_options,
      );
      const lightweightModelLabel = fallbackSelectableModelLabel(
        values.lightweight_model_label,
        values.selectable_model_options,
      );
      if (isEditMode && agentId) {
        updateMutation.mutate({
          handle,
          agentId,
          name: values.name,
          description: values.description ?? null,
          selectable_model_options: selectableModelOptions,
          main_model_label: mainModelLabel,
          lightweight_model_label: lightweightModelLabel,
          model_parameters: modelParameters,
          system_prompt: values.system_prompt ?? null,
          type: values.type,
          enabled: values.enabled,
          shell_enabled: values.shell_enabled,
          memory_enabled: values.memory_enabled,
          max_turns: values.max_turns ?? null,
          subagent_settings: {
            max_subagents: values.subagent_max_subagents,
            max_depth: values.subagent_max_depth,
          },
        });
      } else {
        createMutation.mutate({
          handle,
          name: values.name,
          description: values.description,
          selectable_model_options: selectableModelOptions,
          main_model_label: mainModelLabel,
          lightweight_model_label: lightweightModelLabel,
          model_parameters: modelParameters,
          system_prompt: values.system_prompt,
          type: values.type,
          enabled: values.enabled,
          shell_enabled: values.shell_enabled,
          memory_enabled: values.memory_enabled,
          max_turns: values.max_turns ?? null,
          subagent_settings: {
            max_subagents: values.subagent_max_subagents,
            max_depth: values.subagent_max_depth,
          },
        });
      }
    },
    [handle, agentId, isEditMode, createMutation, updateMutation],
  );

  const onSyncCatalog = useCallback(
    async (integrationId: string): Promise<void> => {
      await syncCatalogMutation.mutateAsync({ handle, integrationId });
    },
    [handle, syncCatalogMutation],
  );

  const onAddAdmin = useCallback(
    (workspaceUserId: string): void => {
      if (!agentId) {
        return;
      }
      addAdminMutation.mutate({ handle, agentId, workspaceUserId });
    },
    [handle, agentId, addAdminMutation],
  );

  const onRemoveAdmin = useCallback(
    (admin: AgentAdminResponse): void => {
      if (!agentId) {
        return;
      }
      removeAdminMutation.mutate({
        handle,
        agentId,
        adminWorkspaceUserId: admin.workspace_user_id,
      });
    },
    [handle, agentId, removeAdminMutation],
  );

  return {
    handle,
    formState,
    mutationState,
    adminListState,
    integrations,
    providerOptions,
    modelOptions,
    workspaceModelSettings: workspaceModelSettingsQuery.data ?? null,
    catalogStates,
    modelsLoading,
    members,
    onSyncCatalog,
    onSubmit,
    onAddAdmin,
    onRemoveAdmin,
  };
}

export { modelSelectionValue };
