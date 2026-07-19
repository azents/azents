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

export function useRetentionPageContainer(): RetentionPageContentProps {
  const utils = trpc.useUtils();
  const settingsQuery = trpc.retention.getSettings.useQuery();
  const [retentionDays, setRetentionDays] = useState<number | null>(30);
  const [applicationScope, setApplicationScope] =
    useState<RetentionApplicationScope>("new_archives_only");
  const [confirmation, setConfirmation] =
    useState<RetentionUpdateConfirmation | null>(null);
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!settingsQuery.data) {
      return;
    }
    setRetentionDays(settingsQuery.data.archived_session_retention_days);
    if (settingsQuery.data.active_application) {
      setApplicationId(settingsQuery.data.active_application.id);
    }
  }, [settingsQuery.data]);

  const previewMutation = trpc.retention.preview.useMutation();
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
    updateMutation.isPending;

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
