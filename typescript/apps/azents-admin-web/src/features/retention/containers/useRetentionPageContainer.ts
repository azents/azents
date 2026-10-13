"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  RetentionApplicationScope,
  RetentionApplicationState,
  RetentionSettingsState,
  RetentionUpdateConfirmation,
} from "../types";

export interface RetentionPageContentProps {
  compactedEvents: CompactedEventRetentionProps;
  state: RetentionSettingsState;
  retentionDays: number | null;
  applicationScope: RetentionApplicationScope;
  confirmation: RetentionUpdateConfirmation | null;
  applicationState: RetentionApplicationState;
  previewing: boolean;
  saving: boolean;
  saveDisabled: boolean;
  errorMessage: string | null;
  successMessage: string | null;
  onRetentionDaysChange: (retentionDays: number | null) => void;
  onApplicationScopeChange: (scope: RetentionApplicationScope) => void;
  onSave: () => void;
  onCancelConfirmation: () => void;
  onConfirmUpdate: () => void;
}

export interface CompactedEventRetentionProps {
  retentionDays: number | null;
  saving: boolean;
  saveDisabled: boolean;
  errorMessage: string | null;
  onChange: (days: number | null) => void;
  onSave: () => void;
}

export function useRetentionPageContainer(): RetentionPageContentProps {
  const utils = trpc.useUtils();
  const settingsQuery = trpc.retention.getSettings.useQuery();
  const [retentionDays, setRetentionDays] = useState<number | null>(30);
  const [compactedDays, setCompactedDays] = useState<number | null>(null);
  const [applicationScope, setApplicationScope] =
    useState<RetentionApplicationScope>("new_archives_only");
  const [confirmation, setConfirmation] =
    useState<RetentionUpdateConfirmation | null>(null);
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const savedArchiveDays = settingsQuery.data?.archived_session_retention_days;
  const savedCompactedDays = settingsQuery.data?.compacted_event_retention_days;
  const savedApplicationId = settingsQuery.data?.active_application?.id;

  useEffect(() => {
    if (typeof savedArchiveDays !== "undefined") {
      setRetentionDays(savedArchiveDays);
    }
    if (typeof savedApplicationId !== "undefined") {
      setApplicationId(savedApplicationId);
    }
  }, [savedArchiveDays, savedApplicationId]);

  useEffect(() => {
    if (typeof savedCompactedDays !== "undefined") {
      setCompactedDays(savedCompactedDays);
    }
  }, [savedCompactedDays]);

  const previewMutation = trpc.retention.preview.useMutation();
  const compactedMutation =
    trpc.retention.updateCompactedEventRetention.useMutation({
      onSuccess: async () => {
        setSuccessMessage(
          "Compacted-event retention updated. Cleanup runs every five minutes.",
        );
        await utils.retention.getSettings.invalidate();
      },
      onError: async () => {
        await utils.retention.getSettings.invalidate();
      },
    });
  const updateMutation = trpc.retention.updateSettings.useMutation({
    onSuccess: async (result) => {
      setConfirmation(null);
      setApplicationScope("new_archives_only");
      setRetentionDays(result.settings.archived_session_retention_days);
      setApplicationId(
        result.application?.id ??
          result.settings.active_application?.id ??
          null,
      );
      setSuccessMessage(
        result.application === null
          ? "Archive retention settings updated."
          : "Archive retention settings updated. Existing archives are being recalculated.",
      );
      await utils.retention.getSettings.invalidate();
    },
  });
  const applicationQuery = trpc.retention.getApplication.useQuery(
    { applicationId: applicationId ?? "disabled" },
    {
      enabled: applicationId !== null,
      refetchInterval: (query) =>
        query.state.data?.status === "completed" ? false : 3_000,
    },
  );

  useEffect(() => {
    if (applicationQuery.data?.status !== "completed") {
      return;
    }
    void utils.retention.getSettings.invalidate();
  }, [applicationQuery.data?.status, utils.retention.getSettings]);

  const state: RetentionSettingsState = settingsQuery.isPending
    ? { type: "LOADING" }
    : settingsQuery.isError
      ? { type: "ERROR", message: settingsQuery.error.message }
      : { type: "LOADED", settings: settingsQuery.data };

  const applicationState: RetentionApplicationState =
    applicationId === null
      ? { type: "IDLE" }
      : applicationQuery.isPending
        ? { type: "LOADING" }
        : applicationQuery.isError
          ? { type: "ERROR", message: applicationQuery.error.message }
          : { type: "LOADED", application: applicationQuery.data };

  const validRetention =
    retentionDays === null ||
    (Number.isInteger(retentionDays) && retentionDays >= 0);
  const changed =
    state.type === "LOADED" &&
    (retentionDays !== state.settings.archived_session_retention_days ||
      applicationScope === "recalculate_existing");
  const saveDisabled =
    state.type !== "LOADED" ||
    state.settings.active_application !== null ||
    !validRetention ||
    !changed ||
    previewMutation.isPending ||
    compactedMutation.isPending ||
    updateMutation.isPending;

  const compactedSaveDisabled =
    state.type !== "LOADED" ||
    compactedDays === state.settings.compacted_event_retention_days ||
    (compactedDays !== null &&
      (!Number.isInteger(compactedDays) ||
        compactedDays < 0 ||
        compactedDays > 2_147_483_647)) ||
    compactedMutation.isPending ||
    updateMutation.isPending;

  const handleCompactedSave = useCallback((): void => {
    if (!settingsQuery.data || compactedSaveDisabled) {
      return;
    }
    setSuccessMessage(null);
    compactedMutation.mutate({
      expectedRevision: settingsQuery.data.revision,
      retentionDays: compactedDays,
    });
  }, [
    settingsQuery.data,
    compactedSaveDisabled,
    compactedMutation,
    compactedDays,
  ]);

  const performUpdate = useCallback(
    (
      scope: RetentionApplicationScope,
      nextRetentionDays: number | null,
    ): void => {
      if (!settingsQuery.data) {
        return;
      }
      setSuccessMessage(null);
      updateMutation.mutate({
        expectedRevision: settingsQuery.data.revision,
        retentionDays: nextRetentionDays,
        applicationScope: scope,
      });
    },
    [settingsQuery.data, updateMutation],
  );

  const handleSave = useCallback((): void => {
    if (state.type !== "LOADED" || saveDisabled) {
      return;
    }
    setSuccessMessage(null);
    if (applicationScope === "new_archives_only") {
      performUpdate(applicationScope, retentionDays);
      return;
    }
    previewMutation.mutate(
      { retentionDays },
      {
        onSuccess: (preview) => {
          setConfirmation({ preview, retentionDays });
        },
      },
    );
  }, [
    applicationScope,
    performUpdate,
    previewMutation,
    retentionDays,
    saveDisabled,
    state.type,
  ]);

  const handleConfirmUpdate = useCallback((): void => {
    if (confirmation === null) {
      return;
    }
    performUpdate("recalculate_existing", confirmation.retentionDays);
  }, [confirmation, performUpdate]);

  const errorMessage = useMemo(
    () =>
      previewMutation.error?.message ?? updateMutation.error?.message ?? null,
    [previewMutation.error?.message, updateMutation.error?.message],
  );

  const handleCancelConfirmation = useCallback((): void => {
    setConfirmation(null);
  }, []);

  return {
    compactedEvents: {
      retentionDays: compactedDays,
      saving: compactedMutation.isPending,
      saveDisabled: compactedSaveDisabled,
      errorMessage: compactedMutation.error?.message ?? null,
      onChange: setCompactedDays,
      onSave: handleCompactedSave,
    },
    state,
    retentionDays,
    applicationScope,
    confirmation,
    applicationState,
    previewing: previewMutation.isPending,
    saving: updateMutation.isPending,
    saveDisabled,
    errorMessage,
    successMessage,
    onRetentionDaysChange: setRetentionDays,
    onApplicationScopeChange: setApplicationScope,
    onSave: handleSave,
    onCancelConfirmation: handleCancelConfirmation,
    onConfirmUpdate: handleConfirmUpdate,
  };
}
