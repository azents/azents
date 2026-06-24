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
  modelSelectionValue,
  parseModelSelectionValue,
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
} from "@azents/public-client";

/** Parse builtin_tool_errors from error message. */
function _parseBuiltinToolErrors(
  message: string,
): Record<string, string[]> | null {
  try {
    const parsed: unknown = JSON.parse(message);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "builtin_tool_errors" in parsed
    ) {
      return (parsed as { builtin_tool_errors: Record<string, string[]> })
        .builtin_tool_errors;
    }
  } catch {
    // JSON parse failure → not builtin tool error
  }
  return null;
}

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
  catalogStates: ReadonlyMap<string, ModelCatalogState>;
  modelsLoading: boolean;
  members: MemberItem[];
  onSyncCatalog: (integrationId: string) => void;
  onSubmit: (values: AgentFormValues) => void;
  onAddAdmin: (workspaceUserId: string) => void;
  onRemoveAdmin: (admin: AgentAdminResponse) => void;
}

function buildModelParameters(values: AgentFormValues): ModelParameters | null {
  const hasBuiltinTools = values.builtin_tools.length > 0;
  const hasModelParams = values.reasoning_effort || hasBuiltinTools;
  if (!hasModelParams) {
    return null;
  }
  return {
    ...(values.reasoning_effort
      ? { reasoning_effort: values.reasoning_effort }
      : {}),
    ...(hasBuiltinTools
      ? {
          builtin_tools: values.builtin_tools.map((name) => ({ name })),
        }
      : {}),
  };
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
    builtinToolErrors: null,
  });

  const isEditMode = agentId != null;

  const agentQuery = trpc.agent.get.useQuery(
    { handle, agentId: agentId ?? "" },
    { enabled: isEditMode },
  );
  const integrationsQuery = trpc.llmProviderIntegration.list.useQuery({
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
      setMutationState({ type: "IDLE", error: null, builtinToolErrors: null });
      void utils.agent.list.invalidate({ handle });
      router.push(successPath);
    },
    onError: (error) => {
      const btErrors = _parseBuiltinToolErrors(error.message);
      setMutationState({
        type: "IDLE",
        error: btErrors ? null : error.message,
        builtinToolErrors: btErrors,
      });
    },
  });

  const updateMutation = trpc.agent.update.useMutation({
    onSuccess: () => {
      setMutationState({ type: "IDLE", error: null, builtinToolErrors: null });
      void utils.agent.list.invalidate({ handle });
      if (agentId) {
        void utils.agent.get.invalidate({ handle, agentId });
      }
      router.push(successPath);
    },
    onError: (error) => {
      const btErrors = _parseBuiltinToolErrors(error.message);
      setMutationState({
        type: "IDLE",
        error: btErrors ? null : error.message,
        builtinToolErrors: btErrors,
      });
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
      const modelSelection = parseModelSelectionValue(
        values.model_selection_value,
      );
      const lightweightModelSelection = parseModelSelectionValue(
        values.lightweight_model_selection_value,
      );
      if (isEditMode && agentId) {
        updateMutation.mutate({
          handle,
          agentId,
          name: values.name,
          description: values.description ?? null,
          model_selection: modelSelection,
          lightweight_model_selection: lightweightModelSelection,
          model_parameters: modelParameters,
          system_prompt: values.system_prompt ?? null,
          type: values.type,
          role: values.role,
          enabled: values.enabled,
          shell_enabled: values.shell_enabled,
          memory_enabled: values.memory_enabled,
          max_turns: values.max_turns ?? null,
          toolkit_inherit_mode: values.toolkit_inherit_mode,
        });
      } else {
        createMutation.mutate({
          handle,
          name: values.name,
          description: values.description,
          model_selection: modelSelection,
          lightweight_model_selection: lightweightModelSelection,
          model_parameters: modelParameters,
          system_prompt: values.system_prompt,
          type: values.type,
          role: values.role,
          enabled: values.enabled,
          shell_enabled: values.shell_enabled,
          memory_enabled: values.memory_enabled,
          max_turns: values.max_turns ?? null,
          toolkit_inherit_mode: values.toolkit_inherit_mode,
        });
      }
    },
    [handle, agentId, isEditMode, createMutation, updateMutation],
  );

  const onSyncCatalog = useCallback(
    (integrationId: string): void => {
      syncCatalogMutation.mutate({ handle, integrationId });
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
