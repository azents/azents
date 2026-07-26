"use client";

import { useEffect, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  canSaveAgentRuntimeExecution,
  canSelectAgentRuntimeExecutionProfile,
  runtimeExecutionStatusRefetchInterval,
} from "../runtimeExecutionPresentation";
import type {
  AgentRuntimeExecutionProps,
  AgentRuntimeExecutionState,
  AgentRuntimeStatusState,
} from "../types";
import type { AgentResponse } from "@azents/public-client";

interface AgentRuntimeExecutionContainerProps {
  handle: string;
  agent: AgentResponse;
}

export function useAgentRuntimeExecutionContainer({
  handle,
  agent,
}: AgentRuntimeExecutionContainerProps): AgentRuntimeExecutionProps {
  const utils = trpc.useUtils();
  const input = { handle, agentId: agent.id };
  const policyQuery = trpc.runtimeExecution.getAgentPolicy.useQuery(input);
  const profilesQuery = trpc.runtimeExecution.listWorkspaceProfiles.useQuery({
    handle,
  });
  const auditQuery = trpc.runtimeExecution.listAgentAuditEvents.useQuery(input);
  const statusQuery = trpc.runtimeExecution.getAgentStatus.useQuery(input, {
    refetchInterval: (query): number | false =>
      runtimeExecutionStatusRefetchInterval(query.state.data),
    retry: false,
  });
  const [profileId, setProfileId] = useState<string | null>(
    policyQuery.data?.profile_id ?? null,
  );
  const [restriction, setRestriction] = useState(
    policyQuery.data?.restriction ?? null,
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<
    "saved" | "applied" | null
  >(null);

  useEffect(() => {
    if (policyQuery.data) {
      setProfileId(policyQuery.data.profile_id);
      setRestriction(policyQuery.data.restriction);
    }
  }, [policyQuery.data]);

  const profiles = useMemo(
    () => profilesQuery.data?.items ?? [],
    [profilesQuery.data?.items],
  );
  const invalidateAll = async (): Promise<void> => {
    await Promise.all([
      utils.runtimeExecution.getAgentPolicy.invalidate(input),
      utils.runtimeExecution.listAgentAuditEvents.invalidate(input),
      utils.runtimeExecution.getAgentStatus.invalidate(input),
      utils.runtimeExecution.listWorkspaceProfiles.invalidate({ handle }),
    ]);
  };
  const replacePolicy = trpc.runtimeExecution.replaceAgentPolicy.useMutation({
    onSuccess: async () => {
      setActionError(null);
      setActionMessage("saved");
      await invalidateAll();
    },
    onError: (error) => {
      setActionMessage(null);
      setActionError(error.message);
    },
  });
  const applyPolicy = trpc.runtimeExecution.applyAgentPolicy.useMutation({
    onSuccess: async () => {
      setActionError(null);
      setActionMessage("applied");
      await invalidateAll();
    },
    onError: (error) => {
      setActionMessage(null);
      setActionError(error.message);
    },
  });
  const queryError =
    policyQuery.error ?? profilesQuery.error ?? auditQuery.error;
  const loading =
    policyQuery.isLoading || profilesQuery.isLoading || auditQuery.isLoading;
  const state: AgentRuntimeExecutionState = loading
    ? { type: "LOADING" }
    : queryError
      ? { type: "ERROR", message: queryError.message }
      : policyQuery.data && profilesQuery.data && auditQuery.data
        ? {
            type: "LOADED",
            policy: policyQuery.data,
            profiles,
            auditEvents: auditQuery.data.items,
          }
        : { type: "ERROR", message: "Runtime Execution data is unavailable." };
  const statusState: AgentRuntimeStatusState = statusQuery.isLoading
    ? { type: "LOADING" }
    : statusQuery.isError
      ? { type: "ERROR", message: statusQuery.error.message }
      : statusQuery.data
        ? { type: "LOADED", status: statusQuery.data }
        : { type: "ERROR", message: "Runtime policy status is unavailable." };
  const canSave =
    restriction !== null && canSaveAgentRuntimeExecution(profileId, profiles);

  return {
    handle,
    agent,
    state,
    statusState,
    profileId,
    restriction,
    saving: replacePolicy.isPending,
    applying: applyPolicy.isPending,
    canSave,
    actionError,
    actionMessage,
    onProfileChange: (nextProfileId) => {
      const profile = profiles.find((item) => item.id === nextProfileId);
      if (!profile || !canSelectAgentRuntimeExecutionProfile(profile)) {
        return;
      }
      setProfileId(nextProfileId);
      setActionError(null);
      setActionMessage(null);
    },
    onRestrictionChange: (nextRestriction) => {
      setRestriction(nextRestriction);
      setActionError(null);
      setActionMessage(null);
    },
    onSave: () => {
      if (!policyQuery.data || !profileId || !restriction || !canSave) {
        return;
      }
      setActionError(null);
      setActionMessage(null);
      replacePolicy.mutate({
        handle,
        agentId: agent.id,
        expectedVersion: policyQuery.data.version,
        profileId,
        restriction,
      });
    },
    onApply: () => {
      setActionError(null);
      setActionMessage(null);
      applyPolicy.mutate(input);
    },
  };
}
