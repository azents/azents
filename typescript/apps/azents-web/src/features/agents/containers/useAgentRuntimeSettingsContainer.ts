"use client";

/** Capability-aware Agent Runtime settings container. */

import { useCallback, useMemo, useState } from "react";
import { useRuntimeSystemMetricsContainer } from "@/features/runtime-metrics/containers/useRuntimeSystemMetricsContainer";
import { trpc } from "@/trpc/client";
import type { RuntimeSystemMetricsOverviewState } from "@/features/runtime-metrics/types";
import type {
  AgentResponse,
  AgentRuntimeResponse,
  WorkspaceRuntimeProfileResponse,
} from "@azents/public-client";

const RUNTIME_TRANSITION_REFETCH_INTERVAL_MS = 2_000;

export type AgentRuntimeSettingsState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      runtime: AgentRuntimeResponse;
      profiles: WorkspaceRuntimeProfileResponse[];
    };

export interface AgentRuntimeSettingsContainerProps {
  handle: string;
  agent: AgentResponse;
}

export interface AgentRuntimeSettingsContainerOutput {
  handle: string;
  agent: AgentResponse;
  state: AgentRuntimeSettingsState;
  metricsState: RuntimeSystemMetricsOverviewState;
  selectedProfileId: string | null;
  actionError: string | null;
  actionNotice: "added" | "profileUpdated" | null;
  addConfirmOpen: boolean;
  removeConfirmOpen: boolean;
  resetConfirmOpen: boolean;
  removalAcknowledged: boolean;
  isAdding: boolean;
  isUpdatingProfile: boolean;
  isRemoving: boolean;
  lifecycleAction: "start" | "stop" | "restart" | "reset" | null;
  onSelectProfile: (profileId: string | null) => void;
  onOpenAddConfirm: () => void;
  onCloseAddConfirm: () => void;
  onConfirmAdd: () => void;
  onUpdateProfile: () => void;
  onOpenRemoveConfirm: () => void;
  onCloseRemoveConfirm: () => void;
  onRemovalAcknowledgedChange: (acknowledged: boolean) => void;
  onConfirmRemove: () => void;
  onOpenResetConfirm: () => void;
  onCloseResetConfirm: () => void;
  onStart: () => void;
  onStop: () => void;
  onRestart: () => void;
  onConfirmReset: () => void;
  onRefresh: () => void;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Runtime request failed.";
}

export function useAgentRuntimeSettingsContainer({
  handle,
  agent,
}: AgentRuntimeSettingsContainerProps): AgentRuntimeSettingsContainerOutput {
  const utils = trpc.useUtils();
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(
    agent.runtime_profile_id,
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<
    "added" | "profileUpdated" | null
  >(null);
  const [addConfirmOpen, setAddConfirmOpen] = useState(false);
  const [removeConfirmOpen, setRemoveConfirmOpen] = useState(false);
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
  const [removalAcknowledged, setRemovalAcknowledged] = useState(false);
  const [lifecycleAction, setLifecycleAction] = useState<
    "start" | "stop" | "restart" | "reset" | null
  >(null);

  const runtimeQuery = trpc.chat.getAgentRuntime.useQuery(
    { handle, agentId: agent.id },
    {
      refetchInterval: (query): number | false => {
        const runtime = query.state.data;
        return runtime?.capability === "removing" ||
          runtime?.configuration?.status === "waiting_for_recreation"
          ? RUNTIME_TRANSITION_REFETCH_INTERVAL_MS
          : false;
      },
    },
  );
  const profilesQuery = trpc.runtimeProfile.list.useQuery({
    handle,
    includeDisabled: true,
  });
  const metrics = useRuntimeSystemMetricsContainer({
    handle,
    agentId: agent.id,
    enabled:
      runtimeQuery.data?.capability === "managed" ||
      runtimeQuery.data?.capability === "removing",
  });

  const invalidateRuntime = useCallback(async (): Promise<void> => {
    await Promise.all([
      utils.chat.getAgentRuntime.invalidate({ handle, agentId: agent.id }),
      utils.chat.getAgentRuntimeSystemMetrics.invalidate({
        handle,
        agentId: agent.id,
      }),
      utils.agent.get.invalidate({ handle, agentId: agent.id }),
      utils.agent.list.invalidate({ handle }),
      utils.chat.getAgentWorkspace.invalidate({ agentId: agent.id }),
      utils.chat.readAgentWorkspacePath.invalidate({ agentId: agent.id }),
      utils.chat.listAgentProjects.invalidate({ agentId: agent.id }),
    ]);
  }, [
    agent.id,
    handle,
    utils.agent.get,
    utils.agent.list,
    utils.chat.getAgentRuntime,
    utils.chat.getAgentRuntimeSystemMetrics,
    utils.chat.getAgentWorkspace,
    utils.chat.listAgentProjects,
    utils.chat.readAgentWorkspacePath,
  ]);

  const addMutation = trpc.chat.addAgentRuntime.useMutation({
    onSuccess: async (response) => {
      setAddConfirmOpen(false);
      setSelectedProfileId(response.runtime.runtime_profile_id);
      setActionError(null);
      setActionNotice("added");
      await invalidateRuntime();
    },
    onError: (error) => setActionError(errorMessage(error)),
  });
  const updateProfileMutation = trpc.agent.update.useMutation({
    onSuccess: async (updatedAgent) => {
      setSelectedProfileId(updatedAgent.runtime_profile_id);
      setActionError(null);
      setActionNotice("profileUpdated");
      await invalidateRuntime();
    },
    onError: (error) => setActionError(errorMessage(error)),
  });
  const removeMutation = trpc.chat.removeAgentRuntime.useMutation({
    onSuccess: async () => {
      setRemoveConfirmOpen(false);
      setRemovalAcknowledged(false);
      setSelectedProfileId(null);
      setActionError(null);
      setActionNotice(null);
      await invalidateRuntime();
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const lifecycleMutationOptions = {
    onSuccess: async (): Promise<void> => {
      setResetConfirmOpen(false);
      setActionError(null);
      setLifecycleAction(null);
      await invalidateRuntime();
    },
    onError: (error: unknown): void => {
      setActionError(errorMessage(error));
      setLifecycleAction(null);
    },
  };
  const startMutation = trpc.chat.startAgentRuntime.useMutation(
    lifecycleMutationOptions,
  );
  const stopMutation = trpc.chat.stopAgentRuntime.useMutation(
    lifecycleMutationOptions,
  );
  const restartMutation = trpc.chat.restartAgentRuntime.useMutation(
    lifecycleMutationOptions,
  );
  const resetMutation = trpc.chat.resetAgentRuntime.useMutation(
    lifecycleMutationOptions,
  );

  const state = useMemo<AgentRuntimeSettingsState>(() => {
    if (runtimeQuery.isError) {
      return { type: "ERROR", message: errorMessage(runtimeQuery.error) };
    }
    if (profilesQuery.isError) {
      return { type: "ERROR", message: errorMessage(profilesQuery.error) };
    }
    if (
      runtimeQuery.isLoading ||
      profilesQuery.isLoading ||
      !runtimeQuery.data
    ) {
      return { type: "LOADING" };
    }
    return {
      type: "READY",
      runtime: runtimeQuery.data,
      profiles: profilesQuery.data?.items ?? [],
    };
  }, [
    profilesQuery.data,
    profilesQuery.error,
    profilesQuery.isError,
    profilesQuery.isLoading,
    runtimeQuery.data,
    runtimeQuery.error,
    runtimeQuery.isError,
    runtimeQuery.isLoading,
  ]);

  const readyRuntime = state.type === "READY" ? state.runtime : null;
  const clearFeedback = (): void => {
    setActionError(null);
    setActionNotice(null);
  };
  const runLifecycle = (
    action: "start" | "stop" | "restart" | "reset",
  ): void => {
    clearFeedback();
    setLifecycleAction(action);
    const input = { handle, agentId: agent.id };
    switch (action) {
      case "start":
        startMutation.mutate(input);
        return;
      case "stop":
        stopMutation.mutate(input);
        return;
      case "restart":
        restartMutation.mutate(input);
        return;
      case "reset":
        resetMutation.mutate(input);
    }
  };

  return {
    handle,
    agent,
    state,
    metricsState: metrics.state,
    selectedProfileId,
    actionError,
    actionNotice,
    addConfirmOpen,
    removeConfirmOpen,
    resetConfirmOpen,
    removalAcknowledged,
    isAdding: addMutation.isPending,
    isUpdatingProfile: updateProfileMutation.isPending,
    isRemoving: removeMutation.isPending,
    lifecycleAction,
    onSelectProfile: (profileId) => {
      clearFeedback();
      setSelectedProfileId(profileId);
    },
    onOpenAddConfirm: () => {
      clearFeedback();
      setAddConfirmOpen(true);
    },
    onCloseAddConfirm: () => setAddConfirmOpen(false),
    onConfirmAdd: () => {
      if (
        readyRuntime?.capability !== "none" ||
        !readyRuntime.actions.add ||
        selectedProfileId === null
      ) {
        return;
      }
      clearFeedback();
      addMutation.mutate({
        handle,
        agentId: agent.id,
        workspaceRuntimeProfileId: selectedProfileId,
        expectedCapabilityVersion: readyRuntime.capability_version,
        expectedRuntimeProfileSelectionVersion:
          readyRuntime.runtime_profile_selection_version,
        idempotencyKey: crypto.randomUUID(),
      });
    },
    onUpdateProfile: () => {
      if (
        readyRuntime?.capability !== "managed" ||
        selectedProfileId === null ||
        selectedProfileId === readyRuntime.runtime_profile_id
      ) {
        return;
      }
      clearFeedback();
      updateProfileMutation.mutate({
        handle,
        agentId: agent.id,
        runtime_profile_id: selectedProfileId,
        expected_runtime_profile_selection_version:
          readyRuntime.runtime_profile_selection_version,
      });
    },
    onOpenRemoveConfirm: () => {
      clearFeedback();
      setRemovalAcknowledged(false);
      setRemoveConfirmOpen(true);
    },
    onCloseRemoveConfirm: () => {
      setRemoveConfirmOpen(false);
      setRemovalAcknowledged(false);
    },
    onRemovalAcknowledgedChange: setRemovalAcknowledged,
    onConfirmRemove: () => {
      if (
        readyRuntime?.capability !== "managed" ||
        !readyRuntime.actions.remove ||
        readyRuntime.removal_impact === null ||
        !removalAcknowledged
      ) {
        return;
      }
      clearFeedback();
      removeMutation.mutate({
        handle,
        agentId: agent.id,
        expectedCapabilityVersion: readyRuntime.capability_version,
        expectedRuntimeProfileSelectionVersion:
          readyRuntime.runtime_profile_selection_version,
        idempotencyKey: crypto.randomUUID(),
        confirmed: true,
      });
    },
    onOpenResetConfirm: () => {
      clearFeedback();
      setResetConfirmOpen(true);
    },
    onCloseResetConfirm: () => setResetConfirmOpen(false),
    onStart: () => runLifecycle("start"),
    onStop: () => runLifecycle("stop"),
    onRestart: () => runLifecycle("restart"),
    onConfirmReset: () => runLifecycle("reset"),
    onRefresh: () => {
      clearFeedback();
      void invalidateRuntime();
    },
  };
}
