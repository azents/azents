"use client";

/**
 * Toolkit create/update form container hook.
 *
 * Edit mode when toolkitId exists; create mode otherwise.
 * Includes Scope management.
 */

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type { ToolkitFormValues } from "../schemas";
import type {
  MutationState,
  ScopeListState,
  ToolkitConfigFormState,
  ToolkitListState,
} from "../types";

export interface ToolkitFormContainerProps {
  handle: string;
  toolkitId?: string;
}

export interface ToolkitFormContainerOutput {
  handle: string;
  formState: ToolkitConfigFormState;
  mutationState: MutationState;
  scopeListState: ScopeListState;
  toolkitListState: ToolkitListState;
  onSubmit: (values: ToolkitFormValues) => void;
  onAddScope: () => void;
  onDeleteScope: (scopeId: string) => void;
}

/**
 * Return null when all secret values in credentials dict are empty.
 * Used to keep existing credentials in edit mode.
 */
function normalizeCredentials(
  credentials: Record<string, unknown> | null,
): Record<string, unknown> | null {
  if (credentials == null) {
    return null;
  }

  // null when all secret fields except type field are empty
  const secretEntries = Object.entries(credentials).filter(
    ([key]) => key !== "type",
  );
  if (secretEntries.length === 0) {
    return null;
  }
  const allEmpty = secretEntries.every(([, v]) => v === "" || v == null);
  if (allEmpty) {
    return null;
  }

  return credentials;
}

export function useToolkitFormContainer(
  props: ToolkitFormContainerProps,
): ToolkitFormContainerOutput {
  const { handle, toolkitId } = props;
  const router = useRouter();
  const utils = trpc.useUtils();

  const [mutationState, setMutationState] = useState<MutationState>({
    type: "IDLE",
    error: null,
  });

  const isEditMode = toolkitId != null;

  // Fetch Toolkit (tool definition) list
  const definitionsQuery = trpc.toolkit.listToolkits.useQuery();

  // Fetch Toolkit Config detail (edit mode only)
  const toolkitQuery = trpc.toolkit.getConfig.useQuery(
    { handle, toolkitId: toolkitId ?? "" },
    { enabled: isEditMode },
  );

  // Fetch Scope list (edit mode only)
  const scopesQuery = trpc.toolkit.listScopes.useQuery(
    { handle, toolkitId: toolkitId ?? "" },
    { enabled: isEditMode },
  );

  // Derive Toolkit (tool definition) state
  const toolkitListState: ToolkitListState = useMemo(() => {
    if (definitionsQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (definitionsQuery.isError) {
      return { type: "ERROR" };
    }
    return {
      type: "READY",
      toolkits: definitionsQuery.data?.items ?? [],
    };
  }, [
    definitionsQuery.isLoading,
    definitionsQuery.isError,
    definitionsQuery.data,
  ]);

  // Derive form state
  const formState: ToolkitConfigFormState = useMemo(() => {
    if (!isEditMode) {
      return { type: "CREATE" };
    }
    if (toolkitQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (toolkitQuery.isError) {
      return { type: "NOT_FOUND" };
    }
    if (!toolkitQuery.data) {
      return { type: "NOT_FOUND" };
    }
    return { type: "EDIT", config: toolkitQuery.data };
  }, [
    isEditMode,
    toolkitQuery.isLoading,
    toolkitQuery.isError,
    toolkitQuery.data,
  ]);

  // Derive Scope state
  const scopeListState: ScopeListState = useMemo(() => {
    if (!isEditMode) {
      return { type: "READY", scopes: [] };
    }
    if (scopesQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (scopesQuery.isError) {
      return { type: "ERROR" };
    }
    return { type: "READY", scopes: scopesQuery.data?.items ?? [] };
  }, [
    isEditMode,
    scopesQuery.isLoading,
    scopesQuery.isError,
    scopesQuery.data,
  ]);

  // Create mutation
  const createMutation = trpc.toolkit.createConfig.useMutation({
    onSuccess: () => {
      setMutationState({ type: "IDLE", error: null });
      void utils.toolkit.listConfigs.invalidate({ handle });
      router.push(`/w/${handle}/toolkits`);
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });

  // Update mutation
  const updateMutation = trpc.toolkit.updateConfig.useMutation({
    onSuccess: () => {
      setMutationState({ type: "IDLE", error: null });
      void utils.toolkit.listConfigs.invalidate({ handle });
      if (toolkitId) {
        void utils.toolkit.getConfig.invalidate({ handle, toolkitId });
      }
      router.push(`/w/${handle}/toolkits`);
    },
    onError: (error) => {
      setMutationState({ type: "IDLE", error: error.message });
    },
  });

  // Scope add mutation
  const createScopeMutation = trpc.toolkit.createScope.useMutation({
    onSuccess: () => {
      if (toolkitId) {
        void utils.toolkit.listScopes.invalidate({ handle, toolkitId });
      }
    },
  });

  // Scope delete mutation
  const deleteScopeMutation = trpc.toolkit.deleteScope.useMutation({
    onSuccess: () => {
      if (toolkitId) {
        void utils.toolkit.listScopes.invalidate({ handle, toolkitId });
      }
    },
  });

  // Form submit — config is already structured object, so JSON.parse is unnecessary
  const onSubmit = useCallback(
    (values: ToolkitFormValues): void => {
      setMutationState({ type: "SUBMITTING" });
      const credentials = normalizeCredentials(values.credentials ?? null);

      if (isEditMode && toolkitId) {
        updateMutation.mutate({
          handle,
          toolkitId,
          slug: values.slug,
          name: values.name,
          description: values.description ?? null,
          prompt: values.prompt ?? null,
          config: values.config,
          ...(credentials != null && { credentials }),
          enabled: values.enabled,
        });
      } else {
        createMutation.mutate({
          handle,
          toolkitType: values.toolkitType,
          slug: values.slug,
          name: values.name,
          description: values.description,
          prompt: values.prompt,
          config: values.config,
          ...(credentials != null && { credentials }),
          enabled: values.enabled,
        });
      }
    },
    [handle, toolkitId, isEditMode, createMutation, updateMutation],
  );

  // Add workspace Scope
  const onAddScope = useCallback((): void => {
    if (!toolkitId) {
      return;
    }
    createScopeMutation.mutate({
      handle,
      toolkitId,
    });
  }, [handle, toolkitId, createScopeMutation]);

  // Delete Scope
  const onDeleteScope = useCallback(
    (scopeId: string): void => {
      if (!toolkitId) {
        return;
      }
      deleteScopeMutation.mutate({ handle, toolkitId, scopeId });
    },
    [handle, toolkitId, deleteScopeMutation],
  );

  return {
    handle,
    formState,
    mutationState,
    scopeListState,
    toolkitListState,
    onSubmit,
    onAddScope,
    onDeleteScope,
  };
}
