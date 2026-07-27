"use client";

import { useEffect, useMemo, useState } from "react";
import { serializers, useQueryState } from "@/hooks/use-query-state";
import { trpc } from "@/trpc/client";
import {
  getRuntimeExecutionPolicyIssue,
  withRuntimeExecutionDockerDefaults,
} from "../runtimeExecutionPresentation";
import type {
  RuntimeExecutionPageContentProps,
  RuntimeExecutionProfileDraft,
} from "../types";

export function useRuntimeExecutionContainer(): RuntimeExecutionPageContentProps {
  const utils = trpc.useUtils();
  const profilesQuery = trpc.runtimeExecution.listProfiles.useQuery();
  const auditQuery = trpc.runtimeExecution.listAuditEvents.useQuery();
  const [selectedProfileId, setSelectedProfileId] = useQueryState("profileId", {
    serializer: serializers.stringOrNull(),
  });
  const [profileDraft, setProfileDraft] =
    useState<RuntimeExecutionProfileDraft | null>(null);
  const [profileModalOpened, setProfileModalOpened] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const profiles = useMemo(
    () => profilesQuery.data?.items ?? [],
    [profilesQuery.data?.items],
  );
  const effectiveProfileId = selectedProfileId ?? profiles[0]?.id ?? null;
  const selectedProfile =
    profiles.find((profile) => profile.id === effectiveProfileId) ?? null;

  useEffect(() => {
    if (selectedProfile) {
      setProfileDraft({
        id: selectedProfile.id,
        displayName: selectedProfile.display_name,
        description: selectedProfile.description,
        policy: withRuntimeExecutionDockerDefaults(selectedProfile.policy),
        expectedVersion: selectedProfile.version,
        reserved: selectedProfile.reserved,
      });
    }
  }, [selectedProfile]);

  const invalidateAll = async (): Promise<void> => {
    await Promise.all([
      utils.runtimeExecution.listProfiles.invalidate(),
      utils.runtimeExecution.listAuditEvents.invalidate(),
    ]);
  };
  const createProfile = trpc.runtimeExecution.createProfile.useMutation({
    onSuccess: async (profile) => {
      setProfileModalOpened(false);
      setSelectedProfileId(profile.id);
      setActionError(null);
      await invalidateAll();
    },
    onError: (error) => setActionError(error.message),
  });
  const replaceProfile = trpc.runtimeExecution.replaceProfile.useMutation({
    onSuccess: async () => {
      setActionError(null);
      await invalidateAll();
    },
    onError: (error) => setActionError(error.message),
  });
  const retireProfile = trpc.runtimeExecution.retireProfile.useMutation({
    onSuccess: async () => {
      setActionError(null);
      await invalidateAll();
    },
    onError: (error) => setActionError(error.message),
  });

  const loading = profilesQuery.isLoading || auditQuery.isLoading;
  const queryError = profilesQuery.error ?? auditQuery.error;
  const state: RuntimeExecutionPageContentProps["state"] = loading
    ? { type: "LOADING" }
    : queryError
      ? { type: "ERROR", message: queryError.message }
      : profilesQuery.data && auditQuery.data
        ? {
            type: "LOADED",
            capabilities: profilesQuery.data.capabilities,
            profiles,
            auditEvents: auditQuery.data.items,
          }
        : { type: "ERROR", message: "Runtime Execution data is unavailable." };

  return {
    state,
    profileDraft,
    selectedProfileId: effectiveProfileId,
    profileDetailOpen: selectedProfileId !== null,
    profileModalOpened,
    savingProfile: createProfile.isPending || replaceProfile.isPending,
    retiringProfile: retireProfile.isPending,
    actionError,
    onSelectProfile: (profileId) => {
      setSelectedProfileId(profileId);
      setActionError(null);
    },
    onProfileDetailClose: () => setSelectedProfileId(null),
    onProfileDraftChange: setProfileDraft,
    onOpenCreateProfile: () => {
      const templatePolicy = selectedProfile?.policy ?? profiles[0]?.policy;
      if (!templatePolicy) {
        return;
      }
      setProfileDraft({
        id: "",
        displayName: "",
        description: "",
        policy: withRuntimeExecutionDockerDefaults(templatePolicy),
        expectedVersion: null,
        reserved: false,
      });
      setProfileModalOpened(true);
      setActionError(null);
    },
    onCloseProfileModal: () => {
      setProfileModalOpened(false);
      if (selectedProfile) {
        setProfileDraft({
          id: selectedProfile.id,
          displayName: selectedProfile.display_name,
          description: selectedProfile.description,
          policy: withRuntimeExecutionDockerDefaults(selectedProfile.policy),
          expectedVersion: selectedProfile.version,
          reserved: selectedProfile.reserved,
        });
      }
    },
    onSaveProfile: () => {
      if (
        !profileDraft ||
        !profilesQuery.data ||
        getRuntimeExecutionPolicyIssue(
          profileDraft.policy,
          profilesQuery.data.capabilities,
        ) !== null
      ) {
        return;
      }
      setActionError(null);
      if (profileDraft.expectedVersion === null) {
        createProfile.mutate({
          profileId: profileDraft.id,
          displayName: profileDraft.displayName,
          description: profileDraft.description,
          policy: profileDraft.policy,
        });
        return;
      }
      replaceProfile.mutate({
        profileId: profileDraft.id,
        expectedVersion: profileDraft.expectedVersion,
        displayName: profileDraft.displayName,
        description: profileDraft.description,
        policy: profileDraft.policy,
      });
    },
    onRetireProfile: () => {
      if (
        !profileDraft ||
        profileDraft.expectedVersion === null ||
        profileDraft.reserved
      ) {
        return;
      }
      if (!window.confirm(`Retire Profile "${profileDraft.displayName}"?`)) {
        return;
      }
      retireProfile.mutate({
        profileId: profileDraft.id,
        expectedVersion: profileDraft.expectedVersion,
      });
    },
  };
}
