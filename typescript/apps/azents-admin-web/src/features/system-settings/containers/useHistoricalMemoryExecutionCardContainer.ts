"use client";

import { useEffect, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  editHistoricalMemoryExecutionForm,
  historicalMemoryExecutionConflict,
  historicalMemoryExecutionDirty,
  historicalMemoryExecutionSaveInput,
  loadHistoricalMemoryExecutionForm,
  receiveHistoricalMemoryExecutionDetail,
} from "../historical-memory-execution-state";
import type { HistoricalMemoryExecutionForm } from "../historical-memory-execution-state";
import type {
  HistoricalMemoryExecutionDraft,
  HistoricalMemoryExecutionPageState,
} from "../types";

export interface HistoricalMemoryExecutionCardProps {
  state: HistoricalMemoryExecutionPageState;
  draft: HistoricalMemoryExecutionDraft;
  dirty: boolean;
  saving: boolean;
  saveDisabled: boolean;
  mutationError: string | null;
  conflict: boolean;
  reloading: boolean;
  onMaxTurnsChange: (value: number | string) => void;
  onTimeoutSecondsChange: (value: number | string) => void;
  onSave: () => void;
  onReload: () => void;
}

export function useHistoricalMemoryExecutionCardContainer(): HistoricalMemoryExecutionCardProps {
  const utils = trpc.useUtils();
  const query = trpc.systemSettings.getHistoricalMemoryExecution.useQuery();
  const [form, setForm] = useState<HistoricalMemoryExecutionForm | null>(null);
  const [reloading, setReloading] = useState(false);
  const [reloadError, setReloadError] = useState<string | null>(null);
  useEffect(() => {
    const detail = query.data;
    if (detail) {
      setForm((current) =>
        receiveHistoricalMemoryExecutionDetail(current, detail),
      );
    }
  }, [query.data]);

  const mutation =
    trpc.systemSettings.patchHistoricalMemoryExecution.useMutation({
      onSuccess: async (detail) => {
        setForm(loadHistoricalMemoryExecutionForm(detail));
        setReloadError(null);
        await Promise.all([
          utils.systemSettings.getHistoricalMemoryExecution.invalidate(),
          utils.systemSettings.listAuditEvents.invalidate(),
        ]);
      },
    });

  const currentForm = query.data
    ? receiveHistoricalMemoryExecutionDetail(form, query.data)
    : form;
  const draft = currentForm?.draft ?? {
    maxTurns: "",
    timeoutSeconds: 600,
  };
  let state: HistoricalMemoryExecutionPageState;
  if (currentForm !== null) {
    state = { type: "LOADED", detail: currentForm.baseline };
  } else if (query.isError) {
    state = { type: "ERROR", message: query.error.message };
  } else {
    state = { type: "LOADING" };
  }
  const dirty =
    currentForm !== null &&
    historicalMemoryExecutionDirty(currentForm.draft, currentForm.baseline);
  const saveInput =
    currentForm === null
      ? null
      : historicalMemoryExecutionSaveInput(currentForm);
  const stale = currentForm?.newerVersion != null;
  const conflict = historicalMemoryExecutionConflict(
    currentForm,
    mutation.error?.data?.code ?? null,
  );
  const saveDisabled =
    state.type !== "LOADED" ||
    !dirty ||
    saveInput === null ||
    conflict ||
    mutation.isPending ||
    query.isFetching ||
    reloading;

  const onSave = (): void => {
    if (saveDisabled) {
      return;
    }
    mutation.mutate(saveInput);
  };
  const onReload = async (): Promise<void> => {
    setReloading(true);
    setReloadError(null);
    try {
      await utils.systemSettings.getHistoricalMemoryExecution.invalidate();
      const detail =
        await utils.systemSettings.getHistoricalMemoryExecution.fetch();
      setForm(loadHistoricalMemoryExecutionForm(detail));
      mutation.reset();
    } catch (error) {
      setReloadError(
        error instanceof Error
          ? error.message
          : "Unable to reload Historical Memory execution settings.",
      );
    } finally {
      setReloading(false);
    }
  };

  return {
    state,
    draft,
    dirty,
    saving: mutation.isPending,
    saveDisabled,
    mutationError:
      reloadError ??
      (stale
        ? "Newer settings are available. Your unsaved changes have been preserved."
        : (mutation.error?.message ?? query.error?.message ?? null)),
    conflict,
    reloading: reloading || query.isFetching,
    onMaxTurnsChange: (value) => {
      setForm((current) => {
        const latest = query.data
          ? receiveHistoricalMemoryExecutionDetail(current, query.data)
          : current;
        return latest === null
          ? null
          : editHistoricalMemoryExecutionForm(latest, {
              ...latest.draft,
              maxTurns: value,
            });
      });
    },
    onTimeoutSecondsChange: (value) => {
      setForm((current) => {
        const latest = query.data
          ? receiveHistoricalMemoryExecutionDetail(current, query.data)
          : current;
        return latest === null
          ? null
          : editHistoricalMemoryExecutionForm(latest, {
              ...latest.draft,
              timeoutSeconds: value,
            });
      });
    },
    onSave,
    onReload: () => {
      void onReload();
    },
  };
}
