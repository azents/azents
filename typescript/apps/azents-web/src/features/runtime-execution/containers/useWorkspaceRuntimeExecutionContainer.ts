"use client";

import { useEffect, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  canAllowWorkspaceRuntimeExecutionProfile,
  canEditWorkspaceRuntimeExecution,
  canSaveWorkspaceRuntimeExecution,
} from "../runtimeExecutionPresentation";
import type {
  WorkspaceRuntimeExecutionProps,
  WorkspaceRuntimeExecutionState,
} from "../types";

interface WorkspaceRuntimeExecutionContainerProps {
  handle: string;
}

export function useWorkspaceRuntimeExecutionContainer({
  handle,
}: WorkspaceRuntimeExecutionContainerProps): WorkspaceRuntimeExecutionProps {
  const utils = trpc.useUtils();
  const input = { handle };
  const policyQuery = trpc.runtimeExecution.getWorkspacePolicy.useQuery(input);
  const profilesQuery =
    trpc.runtimeExecution.listWorkspaceProfiles.useQuery(input);
  const auditQuery =
    trpc.runtimeExecution.listWorkspaceAuditEvents.useQuery(input);
  const memberQuery = trpc.workspaceMember.me.useQuery(input);
  const [restriction, setRestriction] = useState(
    policyQuery.data?.restriction ?? null,
  );
  const [allowedProfileIds, setAllowedProfileIds] = useState<string[]>(
    policyQuery.data?.allowed_profile_ids ?? [],
  );
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (policyQuery.data) {
      setRestriction(policyQuery.data.restriction);
      setAllowedProfileIds(policyQuery.data.allowed_profile_ids);
    }
  }, [policyQuery.data]);

  const profiles = useMemo(
    () => profilesQuery.data?.items ?? [],
    [profilesQuery.data?.items],
  );
  const replacePolicy =
    trpc.runtimeExecution.replaceWorkspacePolicy.useMutation({
      onSuccess: async () => {
        setActionError(null);
        await Promise.all([
          utils.runtimeExecution.getWorkspacePolicy.invalidate(input),
          utils.runtimeExecution.listWorkspaceProfiles.invalidate(input),
          utils.runtimeExecution.listWorkspaceAuditEvents.invalidate(input),
        ]);
      },
      onError: (error) => setActionError(error.message),
    });
  const queryError =
    policyQuery.error ??
    profilesQuery.error ??
    auditQuery.error ??
    memberQuery.error;
  const loading =
    policyQuery.isLoading ||
    profilesQuery.isLoading ||
    auditQuery.isLoading ||
    memberQuery.isLoading;
  const state: WorkspaceRuntimeExecutionState = loading
    ? { type: "LOADING" }
    : queryError
      ? { type: "ERROR", message: queryError.message }
      : policyQuery.data &&
          profilesQuery.data &&
          auditQuery.data &&
          memberQuery.data
        ? {
            type: "LOADED",
            policy: policyQuery.data,
            profiles,
            auditEvents: auditQuery.data.items,
            canEdit: canEditWorkspaceRuntimeExecution(memberQuery.data.role),
          }
        : { type: "ERROR", message: "Runtime Execution data is unavailable." };
  const currentPolicy = policyQuery.data;
  const canSave = currentPolicy
    ? restriction !== null &&
      canSaveWorkspaceRuntimeExecution(
        allowedProfileIds,
        profiles,
        currentPolicy.capabilities,
      )
    : false;
  const hasUnsupportedSelection = currentPolicy
    ? allowedProfileIds.some((profileId) => {
        const profile = profiles.find((item) => item.id === profileId);
        return (
          !profile ||
          !canAllowWorkspaceRuntimeExecutionProfile(
            profile,
            currentPolicy.capabilities,
          )
        );
      })
    : false;

  return {
    state,
    restriction,
    allowedProfileIds,
    saving: replacePolicy.isPending,
    canSave,
    hasUnsupportedSelection,
    actionError,
    onRestrictionChange: setRestriction,
    onToggleProfile: (profileId, allowed) => {
      const profile = profiles.find((item) => item.id === profileId);
      if (
        allowed &&
        (!profile ||
          !policyQuery.data ||
          !canAllowWorkspaceRuntimeExecutionProfile(
            profile,
            policyQuery.data.capabilities,
          ))
      ) {
        return;
      }
      setAllowedProfileIds((current) =>
        allowed
          ? Array.from(new Set([...current, profileId]))
          : current.filter((id) => id !== profileId),
      );
    },
    onSave: () => {
      if (!policyQuery.data || restriction === null || !canSave) {
        return;
      }
      setActionError(null);
      replacePolicy.mutate({
        handle,
        expectedVersion: policyQuery.data.version,
        restriction,
        allowedProfileIds,
      });
    },
  };
}
